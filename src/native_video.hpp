#pragma once
#include <array>
#include <cstdint>

namespace adaptive::native_video {
struct UvTransform {float scale_x,scale_y,offset_x,offset_y;};
// Compose centered proportional cover with an existing source UV rectangle.
// This helper is only wired into the prerecorded fullscreen-video call site.
bool cover_uv(unsigned source_width,unsigned source_height,unsigned target_width,
              unsigned target_height,const UvTransform& original,UvTransform& result) noexcept;
struct CallHook {
    std::uint32_t rva;
    std::array<unsigned char,5> before;
    unsigned char length;
    const void* entry;
    const char* name;
};
struct Counters {std::uint64_t calls,adjusted,invalid;};
struct DrawGeometry {
    unsigned source_width{},source_height{},target_x{},target_y{},target_width{},target_height{};
    UvTransform uv{};
    bool corrected{};
    std::uint64_t sequence{};
};
// Configure after fingerprint verification, before installing hook(). No game
// or process writes occur in configure. Install a CALL to a near tail-jump relay.
bool configure(std::uintptr_t image_base) noexcept;
CallHook hook() noexcept;
Counters counters() noexcept;
bool last_draw(DrawGeometry& geometry) noexcept;
}
