#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <span>

namespace adaptive::native {
struct Patch {
    std::uintptr_t address{};
    std::array<unsigned char, 16> before{};
    std::array<unsigned char, 16> after{};
    std::size_t length{};
};

enum class Outcome { committed, rolled_back, retryable, fatal };
enum class Error {
    none, busy, invalid_patch, unavailable_api, allocation_failed,
    enumeration_failed, malformed_snapshot, process_missing, too_many_threads,
    thread_open_failed, thread_identity_changed, thread_suspend_failed,
    thread_context_failed, thread_in_patch, thread_list_unstable,
    memory_query_failed, memory_read_failed, expected_bytes_mismatch,
    protection_failed, memory_write_failed, write_verification_failed,
    cache_flush_failed, protection_restore_failed, rollback_failed,
    thread_resume_failed, suspend_count_changed, test_injected_failure
};

struct Result {
    Outcome outcome{Outcome::fatal};
    Error error{Error::none};
    std::int32_t native_status{};
    std::size_t suspended_threads{};
    std::size_t resumed_threads{};
    std::size_t enumeration_passes{};
    std::size_t patches_written{};
    bool originals_verified{};
    bool replacements_verified{};
    bool threads_resumed{true};
    bool safe_to_continue{true};
};

// Current-process x64 code changes only. Buffers/API pointers are prepared before
// suspension. No heap, CRT, loader, logging, or Toolhelp calls occur while held.
// The caller must own the target code and must not concurrently free its memory.
// External debuggers/injectors must not create/resume threads during the commit.
// `retryable` means no changes and all acquired suspensions released.
// `rolled_back` means originals/protections verified and all threads released.
// `fatal` must never be retried. If safe_to_continue is false, terminate directly:
// logging/allocating first can deadlock on a still-suspended thread's heap lock.
[[nodiscard]] Result transact(std::span<const Patch> patches) noexcept;

#ifdef DETROIT_NATIVE_TRANSACTION_TESTING
// Test-only, thread-local-free fault injection; set before transact, never during.
// This symbol does not exist in production builds.
void test_fail_after_writes(std::size_t count) noexcept;
#endif
} // namespace adaptive::native
