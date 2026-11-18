#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winternl.h>
#include "native_transaction.hpp"

namespace adaptive::native {
namespace {
static_assert(sizeof(void*) == 8, "The game and transaction ABI are x64 only");
static_assert(sizeof(SYSTEM_PROCESS_INFORMATION) == 0x100);
static_assert(sizeof(SYSTEM_THREAD_INFORMATION) == 0x50);
static_assert(offsetof(SYSTEM_THREAD_INFORMATION, ClientId) == 0x28);
constexpr std::size_t max_patches = 32;
constexpr std::size_t max_threads = 4096;
constexpr unsigned max_passes = 16;
constexpr ULONG max_snapshot = 64 * 1024 * 1024;
constexpr NTSTATUS length_mismatch = static_cast<NTSTATUS>(0xc0000004u);
volatile LONG transaction_busy = 0;

// These native C/system-call interfaces return NTSTATUS; they do not throw C++
// exceptions. Express that in the type so the compiler does not insert a CRT
// terminate/catch path around an indirect call in the held phase.
using QuerySystem = NTSTATUS (NTAPI*)(SYSTEM_INFORMATION_CLASS, PVOID, ULONG, PULONG) noexcept;
using OpenThread = NTSTATUS (NTAPI*)(PHANDLE, ACCESS_MASK, POBJECT_ATTRIBUTES, PCLIENT_ID) noexcept;
using QueryThread = NTSTATUS (NTAPI*)(HANDLE, THREADINFOCLASS, PVOID, ULONG, PULONG) noexcept;
using SuspendThread = NTSTATUS (NTAPI*)(HANDLE, PULONG) noexcept;
using ResumeThread = NTSTATUS (NTAPI*)(HANDLE, PULONG) noexcept;
using GetContext = NTSTATUS (NTAPI*)(HANDLE, PCONTEXT) noexcept;
using QueryMemory = NTSTATUS (NTAPI*)(HANDLE, PVOID, INT, PVOID, SIZE_T, PSIZE_T) noexcept;
using ReadMemory = NTSTATUS (NTAPI*)(HANDLE, PVOID, PVOID, SIZE_T, PSIZE_T) noexcept;
using WriteMemory = NTSTATUS (NTAPI*)(HANDLE, PVOID, PVOID, SIZE_T, PSIZE_T) noexcept;
using ProtectMemory = NTSTATUS (NTAPI*)(HANDLE, PVOID*, PSIZE_T, ULONG, PULONG) noexcept;
using FlushCache = NTSTATUS (NTAPI*)(HANDLE, PVOID, ULONG) noexcept;
using FreeMemory = NTSTATUS (NTAPI*)(HANDLE, PVOID*, PSIZE_T, ULONG) noexcept;
using Close = NTSTATUS (NTAPI*)(HANDLE) noexcept;
struct Api {
    QuerySystem query_system{};
    OpenThread open_thread{};
    QueryThread query_thread{};
    SuspendThread suspend_thread{};
    ResumeThread resume_thread{};
    GetContext get_context{};
    QueryMemory query_memory{};
    ReadMemory read_memory{};
    WriteMemory write_memory{};
    ProtectMemory protect_memory{};
    FlushCache flush_cache{};
    FreeMemory free_memory{};
    Close close{};
    bool load() noexcept {
        HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
        if (!ntdll) return false;
#define RESOLVE(member, name) member = reinterpret_cast<decltype(member)>(GetProcAddress(ntdll, name)); if (!member) return false
        RESOLVE(query_system, "NtQuerySystemInformation");
        RESOLVE(open_thread, "NtOpenThread");
        RESOLVE(query_thread, "NtQueryInformationThread");
        RESOLVE(suspend_thread, "NtSuspendThread");
        RESOLVE(resume_thread, "NtResumeThread");
        RESOLVE(get_context, "NtGetContextThread");
        RESOLVE(query_memory, "NtQueryVirtualMemory");
        RESOLVE(read_memory, "NtReadVirtualMemory");
        RESOLVE(write_memory, "NtWriteVirtualMemory");
        RESOLVE(protect_memory, "NtProtectVirtualMemory");
        RESOLVE(flush_cache, "NtFlushInstructionCache");
        RESOLVE(free_memory, "NtFreeVirtualMemory");
        RESOLVE(close, "NtClose");
#undef RESOLVE
        return true;
    }
};
HANDLE current_process() noexcept { return reinterpret_cast<HANDLE>(static_cast<LONG_PTR>(-1)); }
bool success(NTSTATUS status) noexcept { return status >= 0; }
struct ThreadTimes { LARGE_INTEGER create, exit, kernel, user; };
struct HeldThread { HANDLE handle{}; HANDLE tid{}; LONGLONG born{}; ULONG previous_count{}; bool suspended{}; };
struct Snapshot { SYSTEM_THREAD_INFORMATION* threads{}; ULONG count{}; };

// Volatile scalar accesses prevent a compiler from substituting a CRT memcmp.
bool equal_bytes(const volatile unsigned char* a, const volatile unsigned char* b, std::size_t count) noexcept {
    for (std::size_t i = 0; i < count; ++i) if (a[i] != b[i]) return false;
    return true;
}
void issue(Result& result, Error error, NTSTATUS status = 0) noexcept {
    result.error = error;
    result.native_status = status;
}

bool snapshot(const Api& api, void* buffer, ULONG capacity, HANDLE pid, Snapshot& out, Result& result) noexcept {
    ULONG used = 0;
    NTSTATUS status = api.query_system(SystemProcessInformation, buffer, capacity, &used);
    if (!success(status)) { issue(result, Error::enumeration_failed, status); return false; }
    if (used > capacity || used < sizeof(SYSTEM_PROCESS_INFORMATION)) {
        issue(result, Error::malformed_snapshot); return false;
    }
    auto* bytes = static_cast<unsigned char*>(buffer);
    std::size_t offset = 0;
    for (;;) {
        if (offset > used || used - offset < sizeof(SYSTEM_PROCESS_INFORMATION)) {
            issue(result, Error::malformed_snapshot); return false;
        }
        auto* process = reinterpret_cast<SYSTEM_PROCESS_INFORMATION*>(bytes + offset);
        const std::size_t remaining = used - offset;
        const std::size_t record_size = process->NextEntryOffset ? process->NextEntryOffset : remaining;
        if (record_size > remaining || record_size < sizeof(*process) ||
            (process->NextEntryOffset && (process->NextEntryOffset & 7))) {
            issue(result, Error::malformed_snapshot); return false;
        }
        if (process->UniqueProcessId == pid) {
            if (process->NumberOfThreads > (record_size - sizeof(*process)) / sizeof(SYSTEM_THREAD_INFORMATION)) {
                issue(result, Error::malformed_snapshot); return false;
            }
            out.threads = reinterpret_cast<SYSTEM_THREAD_INFORMATION*>(bytes + offset + sizeof(*process));
            out.count = process->NumberOfThreads;
            return true;
        }
        if (!process->NextEntryOffset) break;
        offset += process->NextEntryOffset;
    }
    issue(result, Error::process_missing); return false;
}

bool read_matches(const Api& api, const Patch& patch, const unsigned char* expected,
                  unsigned char* scratch, Result& result, Error mismatch) noexcept {
    SIZE_T count = 0;
    const auto status = api.read_memory(current_process(), reinterpret_cast<void*>(patch.address), scratch, patch.length, &count);
    if (!success(status) || count != patch.length) { issue(result, Error::memory_read_failed, status); return false; }
    if (!equal_bytes(scratch, expected, patch.length)) { issue(result, mismatch); return false; }
    return true;
}

bool query_protection(const Api& api, const Patch& patch, ULONG& protection, Result& result) noexcept {
    MEMORY_BASIC_INFORMATION memory; // Filled by the kernel; no zeroing/CRT call.
    SIZE_T size = 0;
    const auto status = api.query_memory(current_process(), reinterpret_cast<void*>(patch.address), 0, &memory, sizeof(memory), &size);
    if (!success(status) || size != sizeof(memory)) { issue(result, Error::memory_query_failed, status); return false; }
    const auto begin = reinterpret_cast<std::uintptr_t>(memory.BaseAddress);
    if (memory.State != MEM_COMMIT || (memory.Protect & (PAGE_GUARD | PAGE_NOACCESS)) ||
        patch.address < begin || patch.length > memory.RegionSize || patch.address - begin > memory.RegionSize - patch.length) {
        issue(result, Error::memory_query_failed); return false;
    }
    protection = memory.Protect;
    return true;
}

bool write_patch(const Api& api, const Patch& patch, const unsigned char* bytes, ULONG original_protection,
                 unsigned char* scratch, bool& touched, Result& result) noexcept {
    void* region = reinterpret_cast<void*>(patch.address);
    SIZE_T size = patch.length;
    ULONG ignored = 0;
    auto status = api.protect_memory(current_process(), &region, &size, PAGE_EXECUTE_READWRITE, &ignored);
    if (!success(status)) { issue(result, Error::protection_failed, status); return false; }
    touched = true; // Even a failed write now requires protection restoration.
    SIZE_T written = 0;
    status = api.write_memory(current_process(), reinterpret_cast<void*>(patch.address), const_cast<unsigned char*>(bytes), patch.length, &written);
    bool ok = success(status) && written == patch.length;
    if (!ok) issue(result, Error::memory_write_failed, status);
    if (ok) ok = read_matches(api, patch, bytes, scratch, result, Error::write_verification_failed);
    if (ok) {
        status = api.flush_cache(current_process(), reinterpret_cast<void*>(patch.address), static_cast<ULONG>(patch.length));
        ok = success(status);
        if (!ok) issue(result, Error::cache_flush_failed, status);
    }
    // Always restore protection, including after partial/error writes.
    status = api.protect_memory(current_process(), &region, &size, original_protection, &ignored);
    if (!success(status)) { issue(result, Error::protection_restore_failed, status); return false; }
    ULONG actual = 0;
    if (!query_protection(api, patch, actual, result) || actual != original_protection) {
        issue(result, Error::protection_restore_failed); return false;
    }
    return ok;
}

#ifdef DETROIT_NATIVE_TRANSACTION_TESTING
std::size_t injected_write_count = 0;
#endif
} // namespace

#ifdef DETROIT_NATIVE_TRANSACTION_TESTING
void test_fail_after_writes(std::size_t count) noexcept { injected_write_count = count; }
#endif

Result transact(std::span<const Patch> supplied) noexcept {
    Result result;
    if (InterlockedCompareExchange(&transaction_busy, 1, 0) != 0) {
        result.outcome = Outcome::retryable; result.error = Error::busy; return result;
    }
    // Everything below that can allocate/resolve DLL symbols happens before the
    // first suspension. Arrays and CONTEXT are zeroed now, not in the held phase.
    Api api;
    std::array<Patch, max_patches> patches{};
    std::array<HeldThread, max_threads> held{};
    std::array<ULONG, max_patches> protections{};
    std::array<bool, max_patches> touched{};
    std::array<unsigned char, 16> scratch{};
    CONTEXT context{};
    OBJECT_ATTRIBUTES attributes{};
    ThreadTimes times{};
    Snapshot current{};
    void* buffer = nullptr;
    ULONG capacity = 0;
    std::size_t held_count = 0;
    const std::size_t count = supplied.size();
    const auto pid = reinterpret_cast<HANDLE>(static_cast<ULONG_PTR>(GetCurrentProcessId()));
    const auto self = reinterpret_cast<HANDLE>(static_cast<ULONG_PTR>(GetCurrentThreadId()));
    attributes.Length = sizeof(attributes);
    context.ContextFlags = CONTEXT_CONTROL;
    bool ready = count > 0 && count <= max_patches;
    if (!ready) issue(result, Error::invalid_patch);
    for (std::size_t i = 0; ready && i < count; ++i) {
        patches[i] = supplied[i];
        const auto& p = patches[i];
        if (!p.address || !p.length || p.length > p.before.size() || p.address + p.length < p.address) ready = false;
        for (std::size_t j = 0; ready && j < i; ++j)
            if (p.address < patches[j].address + patches[j].length && patches[j].address < p.address + p.length) ready = false;
        if (!ready) issue(result, Error::invalid_patch);
    }
    if (ready && !api.load()) { issue(result, Error::unavailable_api); ready = false; }
    if (ready) {
        ULONG required = 0;
        const auto status = api.query_system(SystemProcessInformation, nullptr, 0, &required);
        if (status != length_mismatch || required > max_snapshot - 1024 * 1024) {
            issue(result, Error::enumeration_failed, status); ready = false;
        } else {
            capacity = required + 1024 * 1024;
            buffer = VirtualAlloc(nullptr, capacity, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
            if (!buffer) { issue(result, Error::allocation_failed); ready = false; }
        }
    }
    // Establish original bytes/protections before suspension, then revalidate
    // under suspension. This also warms all memory API paths before freezing.
    for (std::size_t i = 0; ready && i < count; ++i)
        ready = query_protection(api, patches[i], protections[i], result) &&
                read_matches(api, patches[i], patches[i].before.data(), scratch.data(), result, Error::expected_bytes_mismatch);
    result.originals_verified = ready;
    bool stable = false;
    unsigned empty_passes = 0;
    if (ready) result.outcome = Outcome::retryable;
    // HELD PHASE: NT syscalls through prepared pointers + scalar/stack operations.
    for (unsigned pass = 0; ready && pass < max_passes; ++pass) {
        ++result.enumeration_passes;
        if (!snapshot(api, buffer, capacity, pid, current, result)) { ready = false; break; }
        std::size_t fresh = 0;
        bool saw_self = false;
        for (ULONG i = 0; ready && i < current.count; ++i) {
            const auto& item = current.threads[i];
            if (item.ClientId.UniqueProcess != pid) { issue(result, Error::malformed_snapshot); ready = false; break; }
            if (item.ClientId.UniqueThread == self) { saw_self = true; continue; }
            bool known = false;
            for (std::size_t j = 0; j < held_count; ++j)
                if (held[j].tid == item.ClientId.UniqueThread && held[j].born == item.Reserved1[2].QuadPart) { known = true; break; }
            if (known) continue;
            if (held_count == max_threads) { issue(result, Error::too_many_threads); ready = false; break; }
            auto& thread = held[held_count];
            CLIENT_ID client = item.ClientId;
            auto status = api.open_thread(&thread.handle, THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,
                                          &attributes, &client);
            if (!success(status)) { issue(result, Error::thread_open_failed, status); ready = false; break; }
            ++held_count;
            thread.tid = client.UniqueThread;
            thread.born = item.Reserved1[2].QuadPart;
            status = api.query_thread(thread.handle, static_cast<THREADINFOCLASS>(1), &times, sizeof(times), nullptr);
            if (!success(status) || times.create.QuadPart != thread.born) {
                issue(result, Error::thread_identity_changed, status); ready = false; break;
            }
            status = api.suspend_thread(thread.handle, &thread.previous_count);
            if (!success(status)) { issue(result, Error::thread_suspend_failed, status); ready = false; break; }
            thread.suspended = true;
            ++result.suspended_threads;
            result.threads_resumed = false;
            status = api.get_context(thread.handle, &context); // Wait until suspension actually took effect.
            if (!success(status)) { issue(result, Error::thread_context_failed, status); ready = false; break; }
            for (std::size_t j = 0; j < count; ++j)
                if (context.Rip >= patches[j].address && context.Rip < patches[j].address + patches[j].length) {
                    issue(result, Error::thread_in_patch); ready = false; break;
                }
            ++fresh;
        }
        if (!ready) break;
        if (!saw_self) { issue(result, Error::malformed_snapshot); ready = false; break; }
        empty_passes = fresh ? 0 : empty_passes + 1;
        if (empty_passes == 2) { stable = true; break; }
    }
    if (ready && !stable) { issue(result, Error::thread_list_unstable); ready = false; }
    for (std::size_t i = 0; ready && i < count; ++i) {
        ULONG actual = 0;
        ready = query_protection(api, patches[i], actual, result) && actual == protections[i] &&
                read_matches(api, patches[i], patches[i].before.data(), scratch.data(), result, Error::expected_bytes_mismatch);
        if (!ready && result.error == Error::none) issue(result, Error::protection_failed);
    }
    if (!ready && result.error == Error::expected_bytes_mismatch) {
        result.originals_verified = false;
        result.outcome = Outcome::fatal; // Another patch/build owns these bytes; no retry.
    }
    bool attempted_write = false;
    if (ready) {
        result.originals_verified = true;
        for (std::size_t i = 0; ready && i < count; ++i) {
            ready = write_patch(api, patches[i], patches[i].after.data(), protections[i], scratch.data(), touched[i], result);
            attempted_write = attempted_write || touched[i];
            if (ready) ++result.patches_written;
#ifdef DETROIT_NATIVE_TRANSACTION_TESTING
            if (ready && injected_write_count && result.patches_written == injected_write_count) {
                issue(result, Error::test_injected_failure); ready = false;
            }
#endif
        }
        if (attempted_write) result.originals_verified = false;
        if (ready) {
            for (std::size_t i = 0; ready && i < count; ++i)
                ready = read_matches(api, patches[i], patches[i].after.data(), scratch.data(), result, Error::write_verification_failed);
            result.replacements_verified = ready;
        }
        if (ready) result.outcome = Outcome::committed;
        else if (attempted_write) {
            const auto cause = result.error;
            const auto cause_status = result.native_status;
            bool rollback_ok = true;
            for (std::size_t i = count; i > 0; --i) if (touched[i - 1]) {
                bool ignored = false;
                if (!write_patch(api, patches[i - 1], patches[i - 1].before.data(), protections[i - 1], scratch.data(), ignored, result)) rollback_ok = false;
            }
            for (std::size_t i = 0; i < count; ++i)
                if (!read_matches(api, patches[i], patches[i].before.data(), scratch.data(), result, Error::rollback_failed)) rollback_ok = false;
            result.originals_verified = rollback_ok;
            result.replacements_verified = false;
            result.outcome = rollback_ok ? Outcome::rolled_back : Outcome::fatal;
            result.safe_to_continue = rollback_ok;
            if (rollback_ok) issue(result, cause, cause_status);
            else issue(result, Error::rollback_failed, result.native_status);
        }
    }
    // Release exactly our increment, including every failure path. Do not claim
    // success if someone else changed a suspend count or a resume syscall failed.
    bool resumes_ok = true;
    for (std::size_t i = held_count; i > 0; --i) {
        auto& thread = held[i - 1];
        if (thread.suspended && result.safe_to_continue) {
            ULONG previous = 0;
            NTSTATUS status = 0;
            for (unsigned retry = 0; retry < 3; ++retry) {
                status = api.resume_thread(thread.handle, &previous);
                if (success(status)) break;
            }
            if (success(status)) {
                ++result.resumed_threads;
                thread.suspended = false;
                if (previous != thread.previous_count + 1) {
                    issue(result, Error::suspend_count_changed); resumes_ok = false;
                }
            } else { issue(result, Error::thread_resume_failed, status); resumes_ok = false; }
        }
        // If rollback could not establish valid original code/protection, do
        // not let game threads execute an ambiguous instruction stream. The
        // caller's required fatal path terminates immediately after this return.
        if (thread.suspended) resumes_ok = false;
        api.close(thread.handle);
    }
    result.threads_resumed = result.resumed_threads == result.suspended_threads;
    if (!resumes_ok) { result.outcome = Outcome::fatal; result.safe_to_continue = false; }
    // NtFreeVirtualMemory is safe even on a fatal path with a retained suspend:
    // neither it nor the interlocked release needs a user-mode heap/loader lock.
    if (buffer) { SIZE_T zero = 0; api.free_memory(current_process(), &buffer, &zero, MEM_RELEASE); }
    InterlockedExchange(&transaction_busy, 0);
    return result;
}
} // namespace adaptive::native
