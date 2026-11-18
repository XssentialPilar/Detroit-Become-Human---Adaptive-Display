#pragma once
#include <cstdint>

namespace adaptive::native_ui_contract {
// Called only for a live native UI owner, on its own Scaleform update thread.
// Read-only handshake. It neither changes transforms nor installs hooks.
bool configure(std::uintptr_t image_base) noexcept;
bool owns_2d_transform(const void* owner) noexcept;
struct LayoutMetrics {
    std::uintptr_t movie{};
    std::uint32_t viewport[6]{};
    // Stage width/height, root scale X/Y, root X/Y, resource ID.
    double values[7]{};
    std::uint32_t valid_fields{};
    float view[12]{}, projection[16]{};
};
// Diagnostic copy on the live owner thread; never retain a GFx value/object.
bool read_layout_metrics(const void* owner,LayoutMetrics& result) noexcept;
struct MovieProbe {
    std::uintptr_t id{};
    unsigned width{},height{};
};
bool get_movie_probe(const void* owner,MovieProbe& result) noexcept;
bool read_probe_number(const MovieProbe& probe,const char* path,double& number) noexcept;
struct Counters { std::uint64_t queried, accepted, missing_or_wrong_type; };
Counters counters() noexcept;
}
