#include "native_video.hpp"
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>

namespace adaptive::native_video {
bool cover_uv(unsigned sw,unsigned sh,unsigned tw,unsigned th,
              const UvTransform& original,UvTransform& result) noexcept {
    if(!sw||!sh||!tw||!th||!std::isfinite(original.scale_x)||!std::isfinite(original.scale_y)||
       !std::isfinite(original.offset_x)||!std::isfinite(original.offset_y)||
       original.scale_x<=0||original.scale_y<=0)return false;
    const double scale=std::max(static_cast<double>(tw)/sw,static_cast<double>(th)/sh);
    const double fraction_x=std::min(1.0,static_cast<double>(tw)/(scale*sw));
    const double fraction_y=std::min(1.0,static_cast<double>(th)/(scale*sh));
    result={static_cast<float>(original.scale_x*fraction_x),
            static_cast<float>(original.scale_y*fraction_y),
            static_cast<float>(original.offset_x+original.scale_x*(1.0-fraction_x)*0.5),
            static_cast<float>(original.offset_y+original.scale_y*(1.0-fraction_y)*0.5)};
    return true;
}
namespace {
// ABI derived from 0x63aed0 and its one fullscreen Bink caller 0xbd9fd5.
// Argument 14 is not initialized/read in that native call; preserve its slot.
using Blit=void(*)(void*,void*,void*,unsigned,unsigned,unsigned,unsigned,
                  unsigned,unsigned,unsigned,unsigned,unsigned char,unsigned char,
                  std::uintptr_t,unsigned);
Blit original_blit{};
std::atomic<std::uint64_t> calls{},adjusted{},invalid{};
std::atomic_flag publishing{};
DrawGeometry latest{};
void publish(const DrawGeometry& source) noexcept {
    if(publishing.test_and_set(std::memory_order_acquire))return;
    latest=source;
    publishing.clear(std::memory_order_release);
}

void fullscreen_bink_blit(void* blitter,void* source,void* target,
        unsigned source_x,unsigned source_y,unsigned source_width,unsigned source_height,
        unsigned target_x,unsigned target_y,unsigned target_width,unsigned target_height,
        unsigned char option12,unsigned char option13,std::uintptr_t option14,unsigned option15) noexcept {
    original_blit(blitter,source,target,source_x,source_y,source_width,source_height,
                  target_x,target_y,target_width,target_height,option12,option13,option14,option15);
    const auto sequence=calls.fetch_add(1,std::memory_order_relaxed)+1;
    DrawGeometry geometry{source_width,source_height,target_x,target_y,target_width,target_height,{},false,sequence};
    // A null render target is valid in the native binding path (0x6415e0).
    // Geometry comes from the explicit destination rectangle, not this pointer.
    if(!blitter||!source){invalid.fetch_add(1,std::memory_order_relaxed);publish(geometry);return;}
    // The original function has just written these four floats. The caller
    // invokes its draw virtual immediately afterward, so no shared player data,
    // decoded pixels, UI movie, camera, or global blit implementation is changed.
    auto* uv=static_cast<unsigned char*>(blitter)+0x50;
    UvTransform before{},after{};std::memcpy(&before,uv,sizeof before);
    if(!cover_uv(source_width,source_height,target_width,target_height,before,after)){
        invalid.fetch_add(1,std::memory_order_relaxed);publish(geometry);return;
    }
    std::memcpy(uv,&after,sizeof after);
    if(after.scale_x!=before.scale_x||after.scale_y!=before.scale_y)adjusted.fetch_add(1,std::memory_order_relaxed);
    geometry.uv=after;geometry.corrected=true;publish(geometry);
}
}
bool configure(std::uintptr_t base) noexcept {
    if(!base||original_blit)return false;
    original_blit=reinterpret_cast<Blit>(base+0x63aed0);return true;
}
CallHook hook() noexcept {
    return {0xbd9fd5,{0xe8,0xf6,0x0e,0xa6,0xff},5,reinterpret_cast<const void*>(&fullscreen_bink_blit),"prerecorded fullscreen video cover"};
}
Counters counters() noexcept {return {calls.load(std::memory_order_relaxed),adjusted.load(std::memory_order_relaxed),invalid.load(std::memory_order_relaxed)};}
bool last_draw(DrawGeometry& geometry) noexcept {
    if(publishing.test_and_set(std::memory_order_acquire))return false;
    geometry=latest;
    publishing.clear(std::memory_order_release);
    return geometry.sequence!=0;
}
}
