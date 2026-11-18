#pragma once
#include "native_ui_contract.hpp"
#include <string>

namespace adaptive::ui_diagnostics {
// Sampling runs on the owning movie thread. The loader worker owns file I/O.
bool open(const std::wstring& directory);
void observe(const void* owner, bool layout_owned) noexcept;
void flush(unsigned output_width, unsigned output_height, unsigned display_mode,
           unsigned viewport_width, unsigned viewport_height) noexcept;
}
