// Exercise the actual writer and numeric GFx adapter with a controlled movie.
#include "../src/native_ui_contract.cpp"
#include "../src/ui_diagnostics.cpp"
#include <cassert>
#include <cstring>
#include <filesystem>

using namespace adaptive::native_ui_contract;
namespace {
constexpr std::uintptr_t base=0x140000000;
std::array<unsigned char,0x280> owner{};
std::array<std::uintptr_t,4> movie{base+0x1a06e78};
bool alternate=false;
unsigned resource_id=63;
template<class T> void write(unsigned offset,T value){std::memcpy(owner.data()+offset,&value,sizeof value);}
bool get_fake(void* object,Value* value,const char* path){
    assert(object==movie.data());
    if(std::strstr(path,"Button1")&&std::strstr(path,".y")){
        const double position=alternate?950.0:88.0;
        value->type=5;std::memcpy(&value->data,&position,sizeof position);return true;
    }
    if(std::strstr(path,".visible")){value->type=2;value->data=1;return true;}
    value->type=4;
    if(std::strstr(path,"LayoutResourceId"))value->data=resource_id;
    else if(std::strstr(path,"stageWidth"))value->data=1920;
    else if(std::strstr(path,"stageHeight"))value->data=1200;
    else if(std::strstr(path,"scale")||std::strstr(path,"alpha"))value->data=1;
    else value->data=0;
    return true;
}
}

int main(){
    using namespace adaptive::ui_diagnostics;
    assert(configure(base));get_variable=&get_fake;
    write(0,base+0x1e8ecc8);write<unsigned char>(0xec,3);write(0x1b0,movie.data());
    write<unsigned>(0x244,1920);write<unsigned>(0x248,1200);
    std::filesystem::create_directories(L"build/diagnostic_test");
    assert(open(L"build/diagnostic_test/"));
    for(unsigned index=0;index<8;++index){
        alternate=index%2==0;
        observe(owner.data(),false);
        flush(1920,1200,0,1920,1200);
        Sleep(16);
    }
    // A viewport/mode transition must start its own geometry sequence.
    write<unsigned>(0x244,1440);write<unsigned>(0x248,1080);
    observe(owner.data(),false);
    flush(1440,1080,2,1440,1080);
    for (const unsigned id : {64u, 111u, 191u, 193u, 202u, 203u, 214u, 217u}) {
        resource_id=id;
        Sleep(16);
        observe(owner.data(),false);
        flush(1440,1080,2,1440,1080);
        const auto& cache=entry_for(reinterpret_cast<std::uintptr_t>(movie.data()));
        assert(cache.resource==id);
        for(unsigned index=0; index<node_count; ++index)
            if(mask_for(id)&target_bit(index)) assert(cache.previous[index].valid==511);
    }
}
