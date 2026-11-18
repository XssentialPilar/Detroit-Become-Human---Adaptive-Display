#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "native_transaction.hpp"
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <vector>

using adaptive::native::Error;
using adaptive::native::Outcome;
using adaptive::native::Patch;
using adaptive::native::Result;
using adaptive::native::transact;

namespace {
std::atomic<bool> running{true};
std::atomic<unsigned> calls{0};
std::atomic<unsigned> bad_results{0};
std::atomic<unsigned> children{0};
using Function = unsigned (*)();
Function target{};
void require(bool ok, const char* what) {
    if (!ok) { std::fprintf(stderr, "FAIL: %s\n", what); TerminateProcess(GetCurrentProcess(), 1); }
}
Result safe_transact(const std::array<Patch, 3>& patches) {
    auto result = transact(patches);
    // Never use CRT if the transaction reports that a heap-owning thread might
    // still be frozen or that restored code/protections are not trustworthy.
    if (!result.safe_to_continue || !result.threads_resumed) TerminateProcess(GetCurrentProcess(), 2);
    return result;
}
DWORD WINAPI execute_target(void*) {
    while (running.load(std::memory_order_relaxed)) {
        unsigned n = target();
        if (n != 1 && n != 2) ++bad_results;
        ++calls;
        Sleep(0);
    }
    return 0;
}
DWORD WINAPI short_thread(void*) { ++children; return 0; }
DWORD WINAPI spawn_threads(void*) {
    while (running.load(std::memory_order_relaxed)) {
        HANDLE child = CreateThread(nullptr, 0, short_thread, nullptr, 0, nullptr);
        if (child) { WaitForSingleObject(child, INFINITE); CloseHandle(child); }
    }
    return 0;
}
DWORD WINAPI exercise_heap(void*) {
    const auto heap = GetProcessHeap();
    while (running.load(std::memory_order_relaxed)) {
        void* p = HeapAlloc(heap, 0, 1024);
        if (p) HeapFree(heap, 0, p);
        // If the transaction calls an allocator while this thread is suspended
        // here, the test would hang until the outer command timeout catches it.
        if (HeapLock(heap)) { Sleep(1); HeapUnlock(heap); }
        Sleep(0);
    }
    return 0;
}
void assert_protection(void* page) {
    MEMORY_BASIC_INFORMATION info{};
    require(VirtualQuery(page, &info, sizeof(info)) == sizeof(info), "query test page");
    require(info.Protect == PAGE_EXECUTE_READ, "original RX protection restored");
}
}

int main() {
    void* allocation = VirtualAlloc(nullptr, 4096, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    require(allocation != nullptr, "allocate own code page");
    auto* page = static_cast<unsigned char*>(allocation);
    const std::array<unsigned char, 6> function{0xb8, 1, 0, 0, 0, 0xc3}; // mov eax,1; ret
    std::memcpy(page, function.data(), function.size());
    page[64] = 0x11; page[128] = 0x22;
    DWORD old = 0;
    require(VirtualProtect(page, 4096, PAGE_EXECUTE_READ, &old), "RX code page");
    require(FlushInstructionCache(GetCurrentProcess(), page, 4096), "flush own test code");
    target = reinterpret_cast<Function>(page);
    std::array<Patch, 3> forward{{
        {reinterpret_cast<std::uintptr_t>(page), {0xb8,1,0,0,0}, {0xb8,2,0,0,0}, 5},
        {reinterpret_cast<std::uintptr_t>(page+64), {0x11}, {0x33}, 1},
        {reinterpret_cast<std::uintptr_t>(page+128), {0x22}, {0x44}, 1}
    }};
    auto reverse = forward;
    for (auto& patch : reverse) std::swap(patch.before, patch.after);
    auto first = safe_transact(forward);
    require(first.outcome == Outcome::committed && first.replacements_verified, "single-thread commit");
    require(target() == 2 && page[64] == 0x33 && page[128] == 0x44, "all replacements present");
    assert_protection(page);
    auto mismatch = safe_transact(forward);
    require(mismatch.outcome == Outcome::fatal && mismatch.error == Error::expected_bytes_mismatch && mismatch.patches_written == 0,
            "mismatched originals rejected without writes");
    require(safe_transact(reverse).outcome == Outcome::committed && target() == 1, "restore test code");
    auto overlap = forward;
    overlap[1].address = overlap[0].address;
    require(safe_transact(overlap).error == Error::invalid_patch, "overlapping patch ranges rejected");

    adaptive::native::test_fail_after_writes(1);
    auto rollback = safe_transact(forward);
    require(rollback.outcome == Outcome::rolled_back && rollback.originals_verified && rollback.patches_written == 1,
            "forced partial commit restores originals");
    require(target() == 1 && page[64] == 0x11 && page[128] == 0x22, "rollback preserves every original byte");
    assert_protection(page);
    adaptive::native::test_fail_after_writes(0);

    HANDLE already_suspended = CreateThread(nullptr, 0, short_thread, nullptr, CREATE_SUSPENDED, nullptr);
    require(already_suspended != nullptr, "create originally suspended thread");
    require(safe_transact(forward).outcome == Outcome::committed, "commit with a preexisting suspension");
    require(WaitForSingleObject(already_suspended, 0) == WAIT_TIMEOUT, "preexisting suspension preserved");
    require(ResumeThread(already_suspended) == 1, "transaction removed exactly its own suspend increment");
    require(WaitForSingleObject(already_suspended, 5000) == WAIT_OBJECT_0, "originally suspended thread finishes after owner resumes");
    CloseHandle(already_suspended);
    require(safe_transact(reverse).outcome == Outcome::committed, "restore after preexisting-suspension test");

    std::array<HANDLE, 5> workers{
        CreateThread(nullptr,0,execute_target,nullptr,0,nullptr),
        CreateThread(nullptr,0,execute_target,nullptr,0,nullptr),
        CreateThread(nullptr,0,execute_target,nullptr,0,nullptr),
        CreateThread(nullptr,0,spawn_threads,nullptr,0,nullptr),
        CreateThread(nullptr,0,exercise_heap,nullptr,0,nullptr)
    };
    for (auto worker : workers) require(worker != nullptr, "create stress worker");
    adaptive::native::test_fail_after_writes(2);
    bool rolled_back_with_workers = false;
    for (unsigned attempt = 0; attempt < 100 && !rolled_back_with_workers; ++attempt) {
        auto result = safe_transact(forward);
        if (result.outcome == Outcome::rolled_back) {
            require(result.originals_verified && result.patches_written == 2 && result.suspended_threads > 0,
                    "partial two-patch commit rolled back while workers held");
            rolled_back_with_workers = true;
        } else require(result.outcome == Outcome::retryable, "threaded rollback preparation failed cleanly");
    }
    require(rolled_back_with_workers, "threaded rollback exercised");
    require(target() == 1 && page[64] == 0x11 && page[128] == 0x22, "threaded rollback restored all originals");
    adaptive::native::test_fail_after_writes(0);
    unsigned commits = 0, retries = 0;
    std::size_t maximum_passes = 0;
    bool applied = false;
    // Exercise the complete race: targets executing, heap held, short-lived
    // threads created concurrently, and repeated forward/reverse transitions.
    for (unsigned attempt = 0; attempt < 1000 && commits < 60; ++attempt) {
        auto result = safe_transact(applied ? reverse : forward);
        if (result.enumeration_passes > maximum_passes) maximum_passes = result.enumeration_passes;
        require(result.suspended_threads == result.resumed_threads, "every suspension removed");
        if (result.outcome == Outcome::committed) { applied = !applied; ++commits; }
        else {
            ++retries;
            require(result.outcome == Outcome::retryable, "only clean transient failures may retry");
        }
    }
    running = false;
    for (auto worker : workers) { require(WaitForSingleObject(worker, 5000) == WAIT_OBJECT_0, "worker resumed and finished"); CloseHandle(worker); }
    require(commits == 60 && !applied, "60 successful alternating commits");
    require(calls.load() > 0 && children.load() > 0 && bad_results.load() == 0, "live callers saw only intact code");
    require(target() == 1 && page[64] == 0x11 && page[128] == 0x22, "final originals restored");
    assert_protection(page);
    VirtualFree(allocation, 0, MEM_RELEASE);
    std::printf("PASS: commit/rejection/rollback + %u threaded commits, %u clean retries, %zu enumeration passes max; %u calls, %u created threads\n",
                commits, retries, maximum_passes, calls.load(), children.load());
}
