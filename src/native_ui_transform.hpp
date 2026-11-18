#pragma once
#include <array>
#include <cstdint>
#include "native_ui_contract.hpp"

namespace adaptive::native_ui_transform {
struct CallHook {
    std::uint32_t rva;
    std::array<unsigned char,6> before;
    unsigned char length;
    const void* entry;
};
bool configure(std::uintptr_t image_base) noexcept;
using DiagnosticsObserver=void(*)(const void*,bool) noexcept;
void set_diagnostics_observer(DiagnosticsObserver observer) noexcept;
std::array<CallHook,2> hooks() noexcept;
struct Counters {std::uint64_t calls, preserved, owned, scale_mode_repairs;};
Counters counters() noexcept;
// One bounded diagnostic sample per poll, captured on the renderer thread.
bool poll_metrics(native_ui_contract::LayoutMetrics& result) noexcept;
}
