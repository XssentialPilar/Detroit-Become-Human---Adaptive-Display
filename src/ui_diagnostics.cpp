#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "ui_diagnostics.hpp"
#include "native_video.hpp"
#include <array>
#include <atomic>
#include <cstdio>

namespace adaptive::ui_diagnostics {
namespace {
constexpr std::uint64_t sample_interval_ms=8;
constexpr std::size_t file_limit=16*1024*1024;
constexpr const char* targets[]={"Root","Group","Page","Controls","Button1","Button2","Button3",
                                "Button4","Button5","Exit","Title","Footer","Back","Select","Video",
                                "Legal","Sony","Rating","Plate","Ring","Label","Chevron","Progress"};
constexpr const char* properties[]={"x","y","z","scaleX","scaleY","width","height","alpha","visible"};
constexpr unsigned field_count=std::size(properties);
constexpr unsigned node_count=std::size(targets);
constexpr unsigned chevron_slot=21;
constexpr unsigned target_bit(unsigned index){return 1u<<index;}
constexpr unsigned target_range(unsigned begin,unsigned end){return target_bit(end+1)-target_bit(begin);}
unsigned mask_for(unsigned resource){
    switch(resource){
        case 63: return target_range(0,9);
        case 64: return target_range(0,7)|target_range(10,13)|target_bit(18);
        case 111:return target_bit(0)|target_bit(19);
        case 193:case 214:return target_range(0,1)|target_bit(18)|target_bit(20)|target_bit(chevron_slot);
        case 203:return target_range(0,1)|target_bit(20)|target_bit(22);
        case 191:case 202:
                 return target_range(0,1)|target_bit(18)|target_bit(20);
        case 125:return target_range(0,1)|target_range(14,17);
        case 217:return target_range(0,8)|target_range(10,13)|target_bit(18);
        default: return 0;
    }
}
struct Node {
    std::array<double,field_count> values{};
    unsigned valid{};
    int change{-2};
    bool operator==(const Node&) const = default;
};
struct Snapshot {
    std::uint64_t tick{};
    std::uintptr_t movie{};
    unsigned resource{},slot{},stage_width{},stage_height{},width{},height{};
    bool layout_owned{};
    Node geometry{};
};
struct Cache {
    std::uintptr_t movie{};
    std::uint64_t sampled_at{};
    unsigned resource{},width{},height{},stage_width{},stage_height{},samples{};
    bool layout_owned{};
    std::array<Node,node_count> previous{};
};
std::array<Cache,32> caches{};
std::array<Snapshot,4096> queue{};
std::atomic<unsigned> head{},tail{},dropped{};
std::atomic_flag collecting{};
std::atomic<bool> enabled{};
HANDLE file=INVALID_HANDLE_VALUE;
std::size_t written{};
std::uint64_t start_tick{};
constexpr char header[]="event,ms,movie,resource,target,stage_w,stage_h,viewport_w,viewport_h,owned,valid,x,y,z,scale_x,scale_y,width,height,alpha,visible,change\r\n";

Cache& entry_for(std::uintptr_t movie){
    Cache* oldest=&caches.front();
    for(auto& entry:caches){
        if(entry.movie==movie)return entry;
        if(entry.sampled_at<oldest->sampled_at)oldest=&entry;
    }
    *oldest={};oldest->movie=movie;return *oldest;
}
bool append(const char* data,unsigned size) noexcept {
    if(!size||file==INVALID_HANDLE_VALUE)return false;
    DWORD done{};
    if(written+size>file_limit){
        // Restart this bounded trace at a row boundary. Readers follow truncation.
        LARGE_INTEGER begin{};
        if(!SetFilePointerEx(file,begin,nullptr,FILE_BEGIN)||!SetEndOfFile(file)||
           !WriteFile(file,header,sizeof header-1,&done,nullptr)||done!=sizeof header-1)return false;
        written=sizeof header-1;
    }
    if(!WriteFile(file,data,size,&done,nullptr)||done!=size)return false;
    written+=done;return true;
}
void enqueue(const Snapshot& snapshot){
    const auto count=head.load(std::memory_order_relaxed);
    if(count-tail.load(std::memory_order_acquire)>=queue.size()){
        dropped.fetch_add(1,std::memory_order_relaxed);return;
    }
    queue[count%queue.size()]=snapshot;
    head.store(count+1,std::memory_order_release);
}
void sample(const native_ui_contract::MovieProbe& movie,bool owned,std::uint64_t now){
    auto& cache=entry_for(movie.id);
    if(now-cache.sampled_at<sample_interval_ms)return;
    cache.sampled_at=now;
    double id{},sw{},sh{};
    if(!native_ui_contract::read_probe_number(movie,"root.codexLayoutResourceId",id)||
       id<1||id>10000)return;
    const auto resource=static_cast<unsigned>(id);
    const unsigned mask=mask_for(resource);
    if(!mask||resource!=id)return;
    native_ui_contract::read_probe_number(movie,"root.stage.stageWidth",sw);
    native_ui_contract::read_probe_number(movie,"root.stage.stageHeight",sh);
    if(sw<=0||sh<=0||sw>65535||sh>65535)return;
    const auto stage_width=static_cast<unsigned>(sw),stage_height=static_cast<unsigned>(sh);
    const bool reflow=cache.resource!=resource||cache.width!=movie.width||cache.height!=movie.height||
                      cache.stage_width!=stage_width||cache.stage_height!=stage_height||cache.layout_owned!=owned;
    cache.resource=resource;cache.width=movie.width;cache.height=movie.height;
    cache.stage_width=stage_width;cache.stage_height=stage_height;cache.layout_owned=owned;
    // Refresh static guides periodically so a reader joining mid-session gets all current elements.
    const bool heartbeat=(cache.samples++%120)==0;
    for(unsigned slot=0;slot<node_count;++slot){
        if(!(mask&target_bit(slot)))continue;
        Node node;
        if(slot==chevron_slot){
            double change{};
            if(native_ui_contract::read_probe_number(movie,"root.codexStatusChange",change)&&change>=-1&&change<=5)
                node.change=static_cast<int>(change);
        }
        for(unsigned field=0;field<field_count;++field){
            char path[64];
            if(slot)std::snprintf(path,sizeof path,"root.codexProbe%s.%s",targets[slot],properties[field]);
            else std::snprintf(path,sizeof path,"root.%s",properties[field]);
            if(native_ui_contract::read_probe_number(movie,path,node.values[field]))node.valid|=1u<<field;
        }
        if(!node.valid&&!cache.previous[slot].valid)continue;
        if(!reflow&&!heartbeat&&node==cache.previous[slot])continue;
        cache.previous[slot]=node;
        enqueue({now-start_tick,movie.id,resource,slot,stage_width,stage_height,movie.width,movie.height,owned,node});
    }
}
}

bool open(const std::wstring& directory){
    const auto path=directory+L"DetroitAdaptiveDisplay.trace.csv";
    file=CreateFileW(path.c_str(),GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    if(!append(header,sizeof header-1)){CloseHandle(file);file=INVALID_HANDLE_VALUE;return false;}
    start_tick=GetTickCount64();
    enabled.store(true,std::memory_order_release);return true;
}

void observe(const void* owner,bool layout_owned) noexcept {
    if(!enabled.load(std::memory_order_acquire)||collecting.test_and_set(std::memory_order_acquire))return;
    native_ui_contract::MovieProbe source{};
    if(native_ui_contract::get_movie_probe(owner,source))sample(source,layout_owned,GetTickCount64());
    collecting.clear(std::memory_order_release);
}

void flush(unsigned output_width,unsigned output_height,unsigned display_mode,unsigned viewport_width,unsigned viewport_height) noexcept {
    if(!enabled.load(std::memory_order_acquire))return;
    static std::array<unsigned,5> previous{};
    const std::array mode{output_width,output_height,display_mode,viewport_width,viewport_height};
    const auto skipped=dropped.exchange(0,std::memory_order_relaxed);
    char line[640];
    if(mode!=previous||skipped){
        previous=mode;
        const int n=std::snprintf(line,sizeof line,"display,%llu,0,0,Output,%u,%u,%u,%u,%u,%u\r\n",
            static_cast<unsigned long long>(GetTickCount64()-start_tick),output_width,output_height,
            viewport_width,viewport_height,display_mode,skipped);
        if(n>0&&n<static_cast<int>(sizeof line))append(line,static_cast<unsigned>(n));
    }
    static std::uint64_t video_sequence=0;
    static std::uint64_t video_time=0;
    native_video::DrawGeometry video{};
    const auto now=GetTickCount64()-start_tick;
    if(native_video::last_draw(video)&&video.sequence!=video_sequence){
        video_sequence=video.sequence;video_time=now;
        // Reuse column positions for source size, target size/origin and UV.
        const int n=std::snprintf(line,sizeof line,
            "video,%llu,0,0,Bink,%u,%u,%u,%u,%u,511,%u,%u,0,%.7f,%.7f,%.7f,%.7f,0,1\r\n",
            static_cast<unsigned long long>(now),video.source_width,video.source_height,video.target_width,video.target_height,
            unsigned(video.corrected),video.target_x,video.target_y,video.uv.scale_x,video.uv.scale_y,video.uv.offset_x,video.uv.offset_y);
        if(n>0&&n<static_cast<int>(sizeof line))append(line,static_cast<unsigned>(n));
    }else if(video_time&&now-video_time>=500){
        const int n=std::snprintf(line,sizeof line,"video,%llu,0,0,Bink,0,0,0,0,0,0\r\n",static_cast<unsigned long long>(now));
        if(n>0&&n<static_cast<int>(sizeof line))append(line,static_cast<unsigned>(n));
        video_time=0;
    }
    auto next=tail.load(std::memory_order_relaxed);
    const auto end=head.load(std::memory_order_acquire);
    while(next!=end){
        const auto& s=queue[next%queue.size()];
        const auto& v=s.geometry.values;
        char change[8]{};
        if(s.slot==chevron_slot && s.geometry.change>=-1)
            std::snprintf(change,sizeof change,"%d",s.geometry.change);
        const int n=std::snprintf(line,sizeof line,
            "ui,%llu,%llx,%u,%s,%u,%u,%u,%u,%u,%u,%.4f,%.4f,%.4f,%.6f,%.6f,%.4f,%.4f,%.4f,%.0f,%s\r\n",
            static_cast<unsigned long long>(s.tick),static_cast<unsigned long long>(s.movie),s.resource,
            targets[s.slot],s.stage_width,s.stage_height,s.width,s.height,unsigned(s.layout_owned),s.geometry.valid,
            v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],change);
        if(n>0&&n<static_cast<int>(sizeof line)&&!append(line,static_cast<unsigned>(n))){
            enabled.store(false,std::memory_order_release);
            CloseHandle(file);file=INVALID_HANDLE_VALUE;break;
        }
        ++next;
    }
    tail.store(next,std::memory_order_release);
}
}
