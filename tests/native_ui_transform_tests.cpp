#include "../src/native_ui_contract.cpp"
#include "../src/native_ui_transform.cpp"
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <thread>

namespace {
std::array<unsigned char,0x280> owner{};
std::array<std::uintptr_t,0x80/8> movie_table{};
std::array<std::uintptr_t,0x118/8> object_table{};
struct Object {std::uintptr_t* vtable;} movie{movie_table.data()},object{object_table.data()};
bool ready{},found=true;
unsigned scale_mode=1,mode_writes{},matrix_writes{};
double root_scale=1;
template<class T> void write(std::size_t offset,T value){std::memcpy(owner.data()+offset,&value,sizeof value);}
bool lookup(void* p,adaptive::native_ui_contract::Value* v,const char* path){
    assert(p==&movie);
    if(std::strcmp(path,"root.codexNativeLayoutReady")!=0){v->type=4;v->data=1920;return true;}
    v->type=2;v->data=ready?1:0;return found;
}
unsigned get_mode(void* p){assert(p==&movie);return scale_mode;}
void set_mode(void* p,unsigned value){assert(p==&movie&&value==0);scale_mode=value;++mode_writes;}
bool original_matrix(void* p,std::uintptr_t data,const void* matrix){
    assert(p==&object&&data==0x12345678&&matrix==owner.data()+0x180);
    ++matrix_writes;root_scale=1;return false;
}
bool update(){return adaptive::native_ui_transform::set_root_matrix(&object,0x12345678,owner.data()+0x180);}
}
int main(){
    const auto base=reinterpret_cast<std::uintptr_t>(movie_table.data())-0x1a06e78;
    assert(adaptive::native_ui_transform::configure(base));
    adaptive::native_ui_contract::get_variable=&lookup;
    movie_table[0x70/8]=reinterpret_cast<std::uintptr_t>(&set_mode);
    movie_table[0x78/8]=reinterpret_cast<std::uintptr_t>(&get_mode);
    object_table[0x110/8]=reinterpret_cast<std::uintptr_t>(&original_matrix);
    write(0,base+0x1e8ecc8);write<unsigned char>(0xec,3);write(0x1b0,&movie);
    assert(!update()&&matrix_writes==1&&mode_writes==0);
    ready=true;root_scale=10.0/9;assert(update()&&root_scale==10.0/9&&mode_writes==1);
    assert(update()&&mode_writes==1); // Stable frames do not re-emit a mode change.
    scale_mode=1;assert(update()&&mode_writes==2);
    write<std::uintptr_t>(0xc8,1);assert(!update());write<std::uintptr_t>(0xc8,0);
    write<unsigned char>(0xec,1);assert(!update());write<unsigned char>(0xec,3);
    found=false;assert(!update());found=true;
    // Reproduce independently ticking document and renderer clocks. ENTER_FRAME
    // alone loses the scale between document ticks; gated native setters do not.
    unsigned schedules=0,legacy_mismatches=0;
    for(unsigned render_hz:{30u,60u,120u,180u,240u}){
        for(unsigned document_hz:{24u,30u,60u}){
            ready=false;root_scale=1;unsigned previous_tick=~0u;
            for(unsigned frame=0;frame<render_hz*2;++frame){
                const auto tick=frame*document_hz/render_hz;
                update();
                if(tick!=previous_tick){root_scale=10.0/9;ready=true;previous_tick=tick;}
                assert(root_scale==10.0/9);
            }
            double old_scale=1;previous_tick=~0u;
            for(unsigned frame=0;frame<render_hz*2;++frame){
                old_scale=1;const auto tick=frame*document_hz/render_hz;
                if(tick!=previous_tick){old_scale=10.0/9;previous_tick=tick;}
                if(old_scale!=10.0/9)++legacy_mismatches;
            }
            ++schedules;
        }
    }
    assert(legacy_mismatches>0&&schedules==15);
    const auto sites=adaptive::native_ui_transform::hooks();
    assert(sites[0].rva==0xbc2360&&sites[1].rva==0xbc253a&&sites[0].entry==sites[1].entry);
    adaptive::native_ui_contract::LayoutMetrics diagnostic{};
    assert(!adaptive::native_ui_transform::poll_metrics(diagnostic));
    assert(update());assert(adaptive::native_ui_transform::poll_metrics(diagnostic));
    std::atomic<bool> finished=false;
    std::thread renderer([&]{while(!finished.load(std::memory_order_acquire))update();});
    unsigned samples=0;
    while(samples<2000){
        if(adaptive::native_ui_transform::poll_metrics(diagnostic)){
            assert(diagnostic.valid_fields==127&&diagnostic.movie==reinterpret_cast<std::uintptr_t>(&movie));
            for(auto number:diagnostic.values)assert(number==1920);
            ++samples;
        }else std::this_thread::yield();
    }
    finished.store(true,std::memory_order_release);renderer.join();
    assert(diagnostic.valid_fields==127&&diagnostic.values[0]==1920);
    // The producer may have filled one final request before observing stop.
    adaptive::native_ui_transform::poll_metrics(diagnostic);
    assert(!adaptive::native_ui_transform::poll_metrics(diagnostic));
    assert(update());assert(adaptive::native_ui_transform::poll_metrics(diagnostic));
    std::puts("PASS: original ABI/return, world/stock exclusion, NoScale repair, 15 cadence schedules; 2000 concurrent diagnostic snapshots without retained GFx objects");
}
