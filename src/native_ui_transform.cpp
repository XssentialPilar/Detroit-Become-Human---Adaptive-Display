#include "native_ui_transform.hpp"
#include "native_ui_contract.hpp"
#include <atomic>
#include <cstddef>
#include <cstring>

namespace adaptive::native_ui_transform {
namespace {
using SetMatrix=bool(*)(void*,std::uintptr_t,const void*);
using GetScaleMode=unsigned(*)(void*);
using SetScaleMode=void(*)(void*,unsigned);
bool configured{};
DiagnosticsObserver diagnostics_observer{};
std::atomic<std::uint64_t> calls{},preserved{},owned{},scale_mode_repairs{};
// 0=idle,1=requested,2=producer owns,3=ready,4=consumer owns.
std::atomic<unsigned> metrics_state{};
native_ui_contract::LayoutMetrics metrics_payload{};
template<class T> T read(const void* object,std::size_t offset) noexcept {
    T value{};std::memcpy(&value,static_cast<const unsigned char*>(object)+offset,sizeof value);return value;
}

bool set_root_matrix(void* interface_ptr,std::uintptr_t object_data,const void* matrix) noexcept {
    // Both exact call sites pass owner+0x180 in R8. They otherwise share the
    // normal ObjectInterface SetDisplayMatrix3D ABI (RCX, RDX, R8).
    calls.fetch_add(1,std::memory_order_relaxed);
    const auto address=reinterpret_cast<std::uintptr_t>(matrix);
    const auto* owner=address>=0x180?reinterpret_cast<const void*>(address-0x180):nullptr;
    if(configured&&native_ui_contract::owns_2d_transform(owner)){
        auto* movie=read<void*>(owner,0x1b0);
        auto* vtable=read<const unsigned char*>(movie,0);
        const auto get_mode=read<GetScaleMode>(vtable,0x78);
        if(get_mode(movie)!=0){
            // Creation can overwrite an AS3 constructor's NoScale with ShowAll.
            // Correct only a real mismatch, allowing the normal resize event.
            const auto set_mode=read<SetScaleMode>(vtable,0x70);
            set_mode(movie,0);
            scale_mode_repairs.fetch_add(1,std::memory_order_relaxed);
        }
        // AS3 owns this root's stable 2D transform. Do not replace it with a 3D
        // matrix between document frames. The preceding DisplayInfo alpha and
        // following view/projection/Advance calls remain completely native.
        owned.fetch_add(1,std::memory_order_relaxed);
        unsigned requested=1;
        if(metrics_state.compare_exchange_strong(requested,2,std::memory_order_acquire)){
            const bool captured=native_ui_contract::read_layout_metrics(owner,metrics_payload);
            metrics_state.store(captured?3u:1u,std::memory_order_release);
        }
        if(diagnostics_observer)diagnostics_observer(owner,true);
        return true;
    }
    auto* vtable=read<const unsigned char*>(interface_ptr,0);
    const auto original=read<SetMatrix>(vtable,0x110);
    preserved.fetch_add(1,std::memory_order_relaxed);
    const bool applied=original(interface_ptr,object_data,matrix);
    if(diagnostics_observer)diagnostics_observer(owner,false);
    return applied;
}
}
void set_diagnostics_observer(DiagnosticsObserver observer) noexcept {diagnostics_observer=observer;}
bool configure(std::uintptr_t base) noexcept {
    if(configured||!native_ui_contract::configure(base))return false;
    configured=true;return true;
}
std::array<CallHook,2> hooks() noexcept {
    const auto* entry=reinterpret_cast<const void*>(&set_root_matrix);
    return {{{0xbc2360,{0xff,0x90,0x10,0x01,0,0},6,entry},
             {0xbc253a,{0xff,0x90,0x10,0x01,0,0},6,entry}}};
}
Counters counters() noexcept {
    return {calls.load(std::memory_order_relaxed),preserved.load(std::memory_order_relaxed),
            owned.load(std::memory_order_relaxed),scale_mode_repairs.load(std::memory_order_relaxed)};
}
bool poll_metrics(native_ui_contract::LayoutMetrics& result) noexcept {
    unsigned ready=3;
    if(metrics_state.compare_exchange_strong(ready,4,std::memory_order_acquire)){
        result=metrics_payload;metrics_state.store(1,std::memory_order_release);return true;
    }
    unsigned idle=0;metrics_state.compare_exchange_strong(idle,1,std::memory_order_release);
    return false;
}
}
