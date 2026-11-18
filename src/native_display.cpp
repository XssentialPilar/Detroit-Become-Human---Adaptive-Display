#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <limits>
#include "native_display.hpp"

namespace adaptive::native_display {
namespace {
using NativeUpdate=void(*)(void*);
using AdjustDpi=BOOL(WINAPI*)(LPRECT,DWORD,BOOL,DWORD,UINT);
using WindowDpi=UINT(WINAPI*)(HWND);
std::uintptr_t image{};
NativeUpdate original_prepare{};
NativeUpdate original_update{};
AdjustDpi adjust_dpi{};
WindowDpi window_dpi{};
std::atomic<bool> refresh_pending{false};
std::atomic<unsigned> requests{},confirmed{},unconfirmed{},refreshes{};

// Indirection permits offline integration tests without creating a window or
// running the game. Production entries are ordinary Win32 APIs.
struct WindowApi {
    decltype(&GetWindowThreadProcessId) owner=&GetWindowThreadProcessId;
    decltype(&GetWindowLongPtrW) style=&GetWindowLongPtrW;
    decltype(&GetMenu) menu=&GetMenu;
    decltype(&GetClientRect) client=&GetClientRect;
    decltype(&GetWindowRect) outer=&GetWindowRect;
    decltype(&IsIconic) iconic=&IsIconic;
    decltype(&AdjustWindowRectEx) adjust=&AdjustWindowRectEx;
} api;

// Accessed only by the same native update path, after original_prepare. No
// worker thread touches these fields; request_refresh uses a separate atomic.
struct PendingClient {
    void* engine{};
    HWND window{};
    unsigned width{},height{},frames_left{};
} pending_client;
bool verify_pending_after_update{};

template<class T>T field(const void* p,std::size_t offset) noexcept {
    T v;std::memcpy(&v,static_cast<const unsigned char*>(p)+offset,sizeof v);return v;
}
template<class T>void put(void* p,std::size_t offset,T value) noexcept {
    std::memcpy(static_cast<unsigned char*>(p)+offset,&value,sizeof value);
}
bool readable(std::uintptr_t address,std::size_t size) noexcept {
    MEMORY_BASIC_INFORMATION m{};
    if(!address||VirtualQuery(reinterpret_cast<void*>(address),&m,sizeof m)!=sizeof m||
       m.State!=MEM_COMMIT||(m.Protect&(PAGE_GUARD|PAGE_NOACCESS)))return false;
    const auto first=reinterpret_cast<std::uintptr_t>(m.BaseAddress);
    return address>=first&&size<=m.RegionSize&&address-first<=m.RegionSize-size;
}
HWND game_window() noexcept {
    if(!image)return nullptr;
    auto h=field<HWND>(reinterpret_cast<void*>(image),0x2a10150);
    DWORD pid{};
    return h&&api.owner(h,&pid)&&pid==GetCurrentProcessId()?h:nullptr;
}
bool selected_client(void* e,unsigned& w,unsigned& h) noexcept {
    const auto count=field<unsigned>(e,0x1530)>>1;
    const auto index=field<unsigned>(e,0x15b0);
    const auto data=field<std::uintptr_t>(e,0x1528);
    if(!count||count>4096||index>=count||!readable(data+index*8,8))return false;
    w=field<unsigned>(reinterpret_cast<void*>(data),index*8);
    h=field<unsigned>(reinterpret_cast<void*>(data),index*8+4);
    return w&&h&&w<=32768&&h<=32768;
}
bool adjust_frame(HWND hwnd,RECT& rect,DWORD style,BOOL menu,DWORD ex) noexcept {
    // Both the desired-client conversion and the engine's inverse calculation
    // use this same implementation and window DPI. Retain legacy behavior when
    // the DPI APIs are unavailable or the window does not yet exist.
    if(hwnd&&adjust_dpi&&window_dpi){
        const UINT dpi=window_dpi(hwnd);
        if(dpi){RECT candidate=rect;if(adjust_dpi(&candidate,style,menu,ex,dpi)){rect=candidate;return true;}}
    }
    return api.adjust(&rect,style,menu,ex)!=FALSE;
}
bool get_styles(HWND h,DWORD& style,DWORD& ex) noexcept {
    SetLastError(0);const auto s=api.style(h,GWL_STYLE);
    if(!s&&GetLastError())return false;
    SetLastError(0);const auto x=api.style(h,GWL_EXSTYLE);
    if(!x&&GetLastError())return false;
    style=static_cast<DWORD>(s);ex=static_cast<DWORD>(x);return true;
}
void flags_or(void* e,unsigned short bits) noexcept {
    put(e,0x1a,static_cast<unsigned short>(field<unsigned short>(e,0x1a)|bits));
}
bool dimensions(const RECT& r,unsigned& w,unsigned& h) noexcept {
    const auto width=static_cast<std::int64_t>(r.right)-r.left;
    const auto height=static_cast<std::int64_t>(r.bottom)-r.top;
    if(width<=0||height<=0||width>std::numeric_limits<int>::max()||height>std::numeric_limits<int>::max())return false;
    w=static_cast<unsigned>(width);h=static_cast<unsigned>(height);return true;
}
void clear_pending(bool success) noexcept {
    if(pending_client.frames_left){if(success)confirmed.fetch_add(1,std::memory_order_relaxed);else unconfirmed.fetch_add(1,std::memory_order_relaxed);}
    pending_client={};
}

void stage_client_request(void* e,unsigned short flags) noexcept {
    clear_pending(false);
    HWND h=game_window();unsigned w{},height{};DWORD style{},ex{};
    if(!h||api.iconic(h)||!selected_client(e,w,height)||!get_styles(h,style,ex))return;
    // 0x150c50 later ORs this exact mask when entering native window mode.
    // Account for that future style before it is actually applied at frame end.
    if(flags&0x01)style|=WS_OVERLAPPEDWINDOW;
    RECT r{0,0,static_cast<LONG>(w),static_cast<LONG>(height)};
    if(!adjust_frame(h,r,style,api.menu(h)!=nullptr,ex))return;
    unsigned outer_w{},outer_h{};if(!dimensions(r,outer_w,outer_h))return;
    put(e,0x1660,outer_w);put(e,0x1664,outer_h);flags_or(e,0x10);
    requests.fetch_add(1,std::memory_order_relaxed);
    pending_client={e,h,w,height,4};
}

void observe_pending_client(void* e) noexcept {
    // Native SetWindowPos/style changes occur after this call. On a subsequent
    // frame, confirm the actual client and recompute using its now-current
    // style. This resolves the one-frame old-style calculation on mode changes.
    verify_pending_after_update=false;
    if(pending_client.frames_left){
        if(pending_client.engine!=e||field<unsigned char>(e,0x1550)!=2||game_window()!=pending_client.window){
            clear_pending(false);
        } else {
            RECT client{},outer{};unsigned cw{},ch{},ow{},oh{};
            if(api.client(pending_client.window,&client)&&dimensions(client,cw,ch)&&
               cw==pending_client.width&&ch==pending_client.height){
                if(field<unsigned>(e,0x11dc)!=cw||field<unsigned>(e,0x11e0)!=ch){
                    if(api.outer(pending_client.window,&outer)&&dimensions(outer,ow,oh)){
                        put(e,0x1660,ow);put(e,0x1664,oh);flags_or(e,0x90);
                    }
                }
                verify_pending_after_update=true;
            }
            --pending_client.frames_left;
            // A zero countdown still needs to count an unconfirmed request.
            if(!pending_client.frames_left&&!verify_pending_after_update){unconfirmed.fetch_add(1,std::memory_order_relaxed);pending_client={};}
        }
    }
}

void prepare_window(void* e) noexcept {
    // This hook precedes 0x191e8e's dirty-state capture and 0x15e510. Introducing
    // flags only at the later viewport call would bypass those notifications.
    if(refresh_pending.exchange(false,std::memory_order_acq_rel)){
        flags_or(e,0x80);refreshes.fetch_add(1,std::memory_order_relaxed);
    }
    original_prepare(e);
    verify_pending_after_update=false;
    const auto mode=field<unsigned char>(e,0x1550);
    const auto flags=field<unsigned short>(e,0x1a);
    if(mode!=2){clear_pending(false);return;}
    // Only change the interpretation of a selected resolution at its boundary.
    // Native resize/move events and saved window dimensions retain their meaning.
    if(flags&0x09)stage_client_request(e,flags);
    observe_pending_client(e);
}

void update_display(void* e) noexcept {
    original_update(e);
    if(verify_pending_after_update){
        verify_pending_after_update=false;
        const bool exact=field<unsigned>(e,0x11dc)==pending_client.width&&field<unsigned>(e,0x11e0)==pending_client.height;
        if(exact){confirmed.fetch_add(1,std::memory_order_relaxed);pending_client={};}
        else if(!pending_client.frames_left){unconfirmed.fetch_add(1,std::memory_order_relaxed);pending_client={};}
    }
}

BOOL WINAPI adjust_for_engine(LPRECT rect,DWORD style,BOOL menu,DWORD ex) noexcept {
    if(!rect)return FALSE;
    return adjust_frame(game_window(),*rect,style,menu,ex)?TRUE:FALSE;
}
}

bool configure(std::uintptr_t base) noexcept {
    if(image||!readable(base+0x2a10150,16)||!readable(base+0x150db0,1)||!readable(base+0x150eb0,1))return false;
    const auto user32=GetModuleHandleW(L"user32.dll");if(!user32)return false;
    adjust_dpi=reinterpret_cast<AdjustDpi>(GetProcAddress(user32,"AdjustWindowRectExForDpi"));
    window_dpi=reinterpret_cast<WindowDpi>(GetProcAddress(user32,"GetDpiForWindow"));
    original_prepare=reinterpret_cast<NativeUpdate>(base+0x150db0);
    original_update=reinterpret_cast<NativeUpdate>(base+0x150eb0);
    image=base;return true;
}
std::array<CallHook,3> hooks() noexcept {
    return {{
        {0x191e3f,{0xe8,0x6c,0xef,0xfb,0xff,0},5,reinterpret_cast<const void*>(&prepare_window),"native window prepare"},
        {0x191eac,{0xe8,0xff,0xef,0xfb,0xff,0},5,reinterpret_cast<const void*>(&update_display),"native viewport refresh"},
        {0x150f86,{0xff,0x15,0x8c,0x4a,0x76,0x01},6,reinterpret_cast<const void*>(&adjust_for_engine),"native frame DPI"}
    }};
}
void request_refresh() noexcept {refresh_pending.store(true,std::memory_order_release);}
Counters counters() noexcept {
    return {requests.load(std::memory_order_relaxed),confirmed.load(std::memory_order_relaxed),
            unconfirmed.load(std::memory_order_relaxed),refreshes.load(std::memory_order_relaxed)};
}
}
