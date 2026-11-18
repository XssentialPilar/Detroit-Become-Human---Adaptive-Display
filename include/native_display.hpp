#pragma once
#include <array>
#include <cstdint>

namespace adaptive::native_display {
struct CallHook {
    std::uint32_t rva;
    std::array<unsigned char,6> before;
    unsigned char length;
    const void* entry;
    const char* name;
};
struct Counters {
    unsigned client_requests;
    unsigned client_confirmed;
    unsigned client_unconfirmed;
    unsigned refresh_requests;
};

// Configure once before publishing any hook. The caller must fingerprint the
// executable and transactionally install ALL three call-site hooks below.
// Each replacement is CALL rel32 to a near tail-jump relay; append NOP at the
// six-byte AdjustWindowRectEx site. No game/process write occurs in configure.
bool configure(std::uintptr_t image_base) noexcept;
std::array<CallHook,3> hooks() noexcept;

// Optional for installation after initialization. Consumption and engine field
// writes happen at the native update call, never on the requesting thread.
void request_refresh() noexcept;
Counters counters() noexcept;
}
