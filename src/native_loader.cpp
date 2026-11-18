// Persistent loader for this exact game build. All WinMM calls are forwarded to
// the system implementation. Game work runs in a dedicated worker, after DLL
// initialization has completed. The first forwarded call can hold loader lock;
// it therefore only resolves forwarding and starts (never waits for) the worker.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>
#include <vector>
#include "winmm_exports.hpp"
#include "engine_identity.hpp"
#include "native_transaction.hpp"
#include "native_display.hpp"
#include "native_video.hpp"
#include "native_ui_transform.hpp"
#include "ui_diagnostics.hpp"

extern "C" void* winmm_api_table[];
extern "C" {
void adaptive_camera_entry();
std::uintptr_t adaptive_engine_global{};
std::uintptr_t adaptive_native_fov{};
}
namespace {
HMODULE self_module{};
INIT_ONCE api_once=INIT_ONCE_STATIC_INIT;
std::wstring directory;
void log(const char* message) {
    if(directory.empty())return;
    auto path=directory+L"DetroitAdaptiveDisplay.log";
    HANDLE f=CreateFileW(path.c_str(),FILE_APPEND_DATA,FILE_SHARE_READ,nullptr,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(f==INVALID_HANDLE_VALUE)return;
    SYSTEMTIME t;GetLocalTime(&t);char line[1024];
    int n=snprintf(line,sizeof line,"%04u-%02u-%02u %02u:%02u:%02u %s\r\n",t.wYear,t.wMonth,t.wDay,t.wHour,t.wMinute,t.wSecond,message);
    if(n>0){DWORD written;WriteFile(f,line,static_cast<DWORD>(n<static_cast<int>(sizeof line)?n:sizeof line-1),&written,nullptr);}
    CloseHandle(f);
}
bool readable(std::uintptr_t p,size_t n) {
    MEMORY_BASIC_INFORMATION m{};
    if(!p||VirtualQuery(reinterpret_cast<void*>(p),&m,sizeof m)!=sizeof m||m.State!=MEM_COMMIT||(m.Protect&(PAGE_GUARD|PAGE_NOACCESS)))return false;
    const auto begin=reinterpret_cast<std::uintptr_t>(m.BaseAddress);
    return p>=begin&&n<=m.RegionSize&&p-begin<=m.RegionSize-n;
}
template<class T> bool read(std::uintptr_t p,T& value){
    SIZE_T copied=0;
    return p&&ReadProcessMemory(GetCurrentProcess(),reinterpret_cast<const void*>(p),&value,sizeof value,&copied)&&copied==sizeof value;
}
void* allocate_near(std::uintptr_t address) {
    auto anchor=address&~std::uintptr_t(0xffff);
    for(std::uintptr_t delta=0x10000;delta<0x70000000;delta+=0x10000){
        for(auto candidate:{anchor-delta,anchor+delta}){
            if(candidate<0x10000)continue;
            if(void* p=VirtualAlloc(reinterpret_cast<void*>(candidate),4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE))return p;
        }
    }
    return nullptr;
}
bool prepare_relay(std::uintptr_t site,const void* entry,void*& allocation) {
    allocation=allocate_near(site);if(!allocation)return false;
    // A leaf tail-jump relay changes no registers or stack; the destination is
    // a statically linked function with its own .pdata/.xdata unwind records.
    std::array<unsigned char,14> relay{0xff,0x25,0,0,0,0};
    auto target=reinterpret_cast<std::uintptr_t>(entry);
    std::memcpy(relay.data()+6,&target,8);std::memcpy(allocation,relay.data(),relay.size());DWORD old;
    return VirtualProtect(allocation,4096,PAGE_EXECUTE_READ,&old)&&FlushInstructionCache(GetCurrentProcess(),allocation,relay.size());
}
bool call_relay(adaptive::native::Patch& patch,const void* entry) {
    void* relay=nullptr;if(!prepare_relay(patch.address,entry,relay))return false;
    const auto displacement=static_cast<std::int64_t>(reinterpret_cast<std::uintptr_t>(relay))-
        static_cast<std::int64_t>(patch.address+5);
    if(displacement<std::numeric_limits<std::int32_t>::min()||displacement>std::numeric_limits<std::int32_t>::max())return false;
    const auto relative=static_cast<std::int32_t>(displacement);
    patch.after.fill(0x90);patch.after[0]=0xe8;std::memcpy(patch.after.data()+1,&relative,4);return true;
}
DWORD WINAPI initialize_display(void*) {
    wchar_t path[32768];DWORD length=GetModuleFileNameW(nullptr,path,32768);
    if(!length||length>=32768)return 0;
    std::wstring full(path,length);auto slash=full.find_last_of(L"\\/");
    if(slash==std::wstring::npos||_wcsicmp(full.c_str()+slash+1,L"DetroitBecomeHuman.exe"))return 0;
    directory=full.substr(0,slash+1);log("Starting own aspect/camera/video integration v0.8; menu, loading and HUD geometry trace");
    if(!adaptive::matches_engine_image(path)){log("Unrecognized engine image; native display integration is inactive");return 0;}
    const auto base=reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
    std::array<adaptive::native::Patch,10> patches{{
        {base+0x151294,{0x44,0x0f,0xb6,0x89,0xad,0x15,0,0},{0x41,0xb9,2,0,0,0,0x90,0x90},8},
        {base+0x15c4c0,{0x0f,0xb6,0x51,0x45},{0x31,0xd2,0xb2,2},4},
        {base+0x1e44f8,{0xe8,0x63,0x3d,0,0},{},5},
        // The game's NoBorder mode crops UI movies. ShowAll preserves every
        // authored element uniformly; individual responsive movies may opt
        // into NoScale and perform their own component layout afterwards.
        {base+0xbc1aa9,{3},{1},1}
    }};
    if(!adaptive::native_display::configure(base)){log("Could not configure native display wrappers; no code changed");return 0;}
    auto display_hooks=adaptive::native_display::hooks();
    for(size_t i=0;i<display_hooks.size();++i){
        auto& target=patches[i+4];auto& hook=display_hooks[i];
        target.address=base+hook.rva;target.length=hook.length;
        std::memcpy(target.before.data(),hook.before.data(),hook.length);
    }
    if(!adaptive::native_video::configure(base)){log("Could not configure prerecorded video wrapper; no code changed");return 0;}
    const auto video_hook=adaptive::native_video::hook();
    patches[7].address=base+video_hook.rva;patches[7].length=video_hook.length;
    std::memcpy(patches[7].before.data(),video_hook.before.data(),video_hook.length);
    if(!adaptive::native_ui_transform::configure(base)){log("Could not configure UI transform ownership; no code changed");return 0;}
    if(adaptive::ui_diagnostics::open(directory))adaptive::native_ui_transform::set_diagnostics_observer(adaptive::ui_diagnostics::observe);
    else log("UI geometry trace could not open its output file");
    const auto ui_hooks=adaptive::native_ui_transform::hooks();
    for(size_t i=0;i<ui_hooks.size();++i){
        auto& target=patches[i+8];const auto& hook=ui_hooks[i];
        target.address=base+hook.rva;target.length=hook.length;
        std::memcpy(target.before.data(),hook.before.data(),hook.length);
    }
    for(auto& p:patches)if(!readable(p.address,p.length)||std::memcmp(reinterpret_cast<void*>(p.address),p.before.data(),p.length)){log("Patch site differs; no game code changed");return 0;}
    adaptive_engine_global=base+0x2a10158;adaptive_native_fov=base+0x1e8260;
    DWORD64 unwind_base=0;
    if(!RtlLookupFunctionEntry(reinterpret_cast<DWORD64>(&adaptive_camera_entry),&unwind_base,nullptr)||
       !call_relay(patches[2],reinterpret_cast<const void*>(&adaptive_camera_entry))){log("Could not prepare camera relay; no code changed");return 0;}
    for(size_t i=0;i<display_hooks.size();++i)if(!call_relay(patches[i+4],display_hooks[i].entry)){
        log("Could not prepare display relay; no code changed");return 0;
    }
    if(!call_relay(patches[7],video_hook.entry)){log("Could not prepare prerecorded video relay; no code changed");return 0;}
    for(size_t i=0;i<ui_hooks.size();++i)if(!call_relay(patches[i+8],ui_hooks[i].entry)){
        log("Could not prepare UI transform relay; no code changed");return 0;
    }
    bool installed=false;
    for(int attempt=0;attempt<100;++attempt){
        auto result=adaptive::native::transact(patches);
        if(result.outcome==adaptive::native::Outcome::committed){installed=true;break;}
        if(result.outcome==adaptive::native::Outcome::fatal){
            // Do not touch CRT, logging, or any lock after an unresumable thread
            // or unverified rollback. Continuing could execute damaged code.
            if(!result.safe_to_continue){TerminateProcess(GetCurrentProcess(),0xada00001);return 0;}
            log("Patch transaction refused an unexpected state; no retry attempted");return 0;
        }
        if(result.outcome!=adaptive::native::Outcome::retryable){log("Patch transaction did not commit; no retry attempted");return 0;}
        Sleep(10);
    }
    if(!installed){log("Patch transaction not committed after bounded retries");return 0;}
    adaptive::native_display::request_refresh();
    log("Installed aspect selectors, selected-camera projection, UI baseline, client sizing, refresh, fullscreen Bink crop and opted-in UI transform ownership");
    // Observe initialization and later resolution changes. Recalculation is left
    // to the engine's display lifecycle; no renderer is called from this thread.
    unsigned last_width=0,last_height=0;
    unsigned last_requests=0,last_confirmed=0,last_unconfirmed=0;
    std::uint64_t last_video_calls=0,last_video_invalid=0;
    std::uint64_t last_ui_calls=0,last_ui_owned=0,last_ui_repairs=0;
    adaptive::native_ui_contract::LayoutMetrics last_geometry[5]{};
    unsigned previous_mode=~0u,previous_view_width=0,previous_view_height=0;
    std::uint64_t last_poll=0;
    for(;;){
        std::uintptr_t engine=0;unsigned width=0,height=0,view_width=0,view_height=0,display_mode=~0u;
        if(read(base+0x2a10158,engine)&&read(engine+0x11dc,width)&&read(engine+0x11e0,height)&&
           read(engine+0x11cc,view_width)&&read(engine+0x11d0,view_height)&&width&&height){
            unsigned char mode{};
            if(read(engine+0x1550,mode))display_mode=mode;
            if(width!=last_width||height!=last_height||view_width!=previous_view_width||view_height!=previous_view_height||display_mode!=previous_mode){
                char line[256];snprintf(line,sizeof line,"Output %ux%u; viewport %ux%u; display mode %u",width,height,view_width,view_height,display_mode);log(line);
                last_width=width;last_height=height;previous_view_width=view_width;previous_view_height=view_height;previous_mode=display_mode;
            }
        }
        adaptive::ui_diagnostics::flush(width,height,display_mode,view_width,view_height);
        const auto now=GetTickCount64();
        if(now-last_poll<1000){Sleep(100);continue;}
        last_poll=now;
        auto stats=adaptive::native_display::counters();
        if(stats.client_requests!=last_requests||stats.client_confirmed!=last_confirmed||stats.client_unconfirmed!=last_unconfirmed){
            char line[256];snprintf(line,sizeof line,"Window client requests=%u confirmed=%u unconfirmed=%u",stats.client_requests,stats.client_confirmed,stats.client_unconfirmed);log(line);
            last_requests=stats.client_requests;last_confirmed=stats.client_confirmed;last_unconfirmed=stats.client_unconfirmed;
        }
        auto video=adaptive::native_video::counters();
        if((video.calls>0&&last_video_calls==0)||video.calls>=last_video_calls+300||video.invalid!=last_video_invalid){
            char line[256];snprintf(line,sizeof line,"Fullscreen prerecorded video draws=%llu adjusted=%llu invalid=%llu",
                static_cast<unsigned long long>(video.calls),static_cast<unsigned long long>(video.adjusted),static_cast<unsigned long long>(video.invalid));log(line);
            last_video_calls=video.calls;last_video_invalid=video.invalid;
        }
        const auto ui=adaptive::native_ui_transform::counters();
        adaptive::native_ui_contract::LayoutMetrics metrics{};
        if(adaptive::native_ui_transform::poll_metrics(metrics)){
            const unsigned slot=metrics.values[6]==63?0:metrics.values[6]==64?1:metrics.values[6]==125?2:metrics.values[6]==217?3:4;
            if(std::memcmp(&metrics,&last_geometry[slot],sizeof metrics)!=0){
            last_geometry[slot]=metrics;
            char line[768];snprintf(line,sizeof line,
                "UI geometry resource=%.0f movie=%llx valid=%x buffer=%ux%u viewport=%u,%u,%u,%u stage=%.3fx%.3f rootScale=%.6f,%.6f rootXY=%.3f,%.3f viewXY=%.6f,%.6f viewTranslate=%.3f,%.3f projectionXY=%.9f,%.9f",
                metrics.values[6],static_cast<unsigned long long>(metrics.movie),metrics.valid_fields,
                metrics.viewport[0],metrics.viewport[1],metrics.viewport[2],metrics.viewport[3],metrics.viewport[4],metrics.viewport[5],
                metrics.values[0],metrics.values[1],metrics.values[2],metrics.values[3],metrics.values[4],metrics.values[5],
                metrics.view[0],metrics.view[5],metrics.view[3],metrics.view[7],metrics.projection[0],metrics.projection[5]);log(line);
            }
        }
        if((ui.calls>0&&last_ui_calls==0)||(ui.owned>0&&last_ui_owned==0)||
           ui.calls>=last_ui_calls+5000||ui.scale_mode_repairs!=last_ui_repairs){
            char line[256];snprintf(line,sizeof line,"UI matrix calls=%llu original=%llu owned2D=%llu NoScale repairs=%llu",
                static_cast<unsigned long long>(ui.calls),static_cast<unsigned long long>(ui.preserved),
                static_cast<unsigned long long>(ui.owned),static_cast<unsigned long long>(ui.scale_mode_repairs));log(line);
            last_ui_calls=ui.calls;last_ui_owned=ui.owned;last_ui_repairs=ui.scale_mode_repairs;
        }
        Sleep(100);
    }
    return 0;
}
BOOL CALLBACK load_system_api(PINIT_ONCE,PVOID,PVOID*) {
    wchar_t path[MAX_PATH];UINT n=GetSystemDirectoryW(path,MAX_PATH);
    if(!n||n+11>=MAX_PATH)return FALSE;
    std::wcscat(path,L"\\winmm.dll");
    HMODULE system=LoadLibraryExW(path,nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);
    if(!system||system==self_module)return FALSE;
    std::array<void*,winmm_export_count> functions{};
    for(unsigned i=0;i<winmm_export_count;++i){
        auto name=winmm_export_names[i];
        functions[i]=reinterpret_cast<void*>(GetProcAddress(system,name?name:MAKEINTRESOURCEA(winmm_export_ordinals[i])));
        if(!functions[i])return FALSE;
    }
    for(unsigned i=0;i<winmm_export_count;++i)InterlockedExchangePointer(&winmm_api_table[i],functions[i]);
    // Pin before publishing hooks. No hot-unload or hook restoration in DllMain.
    HMODULE pinned{};
    if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,
                         reinterpret_cast<LPCWSTR>(&initialize_display),&pinned))return FALSE;
    // Thread execution starts only after DLL initialization notifications have
    // completed. Never wait for this thread from a forwarding call or DllMain.
    if(HANDLE worker=CreateThread(nullptr,0,initialize_display,nullptr,0,nullptr))CloseHandle(worker);
    return TRUE;
}
}
extern "C" void* resolve_winmm(unsigned index) {
    if(index>=winmm_export_count||!InitOnceExecuteOnce(&api_once,load_system_api,nullptr,nullptr)){
        // A missing OS API cannot be substituted without changing its semantics.
        RaiseFailFastException(nullptr,nullptr,0);return nullptr;
    }
    return winmm_api_table[index];
}
BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,LPVOID) {
    if(reason==DLL_PROCESS_ATTACH){self_module=module;DisableThreadLibraryCalls(module);}
    return TRUE;
}
