#include "native_ui_contract.hpp"
#include <atomic>
#include <cstddef>
#include <cstring>
#include <limits>
#include <cmath>

namespace adaptive::native_ui_contract {
namespace {
// Layout and lifetime from this executable's BC1ABB..BC1B43.
// VT_Boolean=2 is also documented by Autodesk's Value::ValueType reference.
struct Value {
    std::uintptr_t previous=std::numeric_limits<std::uintptr_t>::max();
    std::uintptr_t next=std::numeric_limits<std::uintptr_t>::max();
    void* interface_ptr=nullptr;
    std::uint32_t type=0;
    std::uint32_t reserved=0;
    std::uintptr_t data=0;
};
static_assert(sizeof(Value)==40 && offsetof(Value,type)==0x18 && offsetof(Value,data)==0x20);
using GetVariable=bool(*)(void*,Value*,const char*);
using Release=void(*)(void*,Value*,std::uintptr_t);
std::uintptr_t image_base{};
GetVariable get_variable{};
std::atomic<std::uint64_t> queried{},accepted{},missing{};
template<class T> T read(const void* object,std::size_t offset) noexcept {
    T value{};std::memcpy(&value,static_cast<const unsigned char*>(object)+offset,sizeof value);return value;
}
void release_value(Value& value) noexcept {
    // The native caller releases managed results even when the lookup is not
    // the expected type. The normal boolean path needs no release/allocation.
    if((value.type&0x40)&&value.interface_ptr){
        auto* vtable=read<const unsigned char*>(value.interface_ptr,0);
        const auto release=read<Release>(vtable,0x10);
        release(value.interface_ptr,&value,value.data);
    }
}
void* checked_movie(const void* owner) noexcept {
    if(!owner||!image_base||!get_variable)return nullptr;
    if(read<std::uintptr_t>(owner,0)!=image_base+0x1e8ecc8 ||
       read<unsigned char>(owner,0xec)!=3 || read<std::uintptr_t>(owner,0xc8)!=0)return nullptr;
    auto* movie=read<void*>(owner,0x1b0);
    return movie&&read<std::uintptr_t>(movie,0)==image_base+0x1a06e78?movie:nullptr;
}
}

bool configure(std::uintptr_t base) noexcept {
    if(!base||image_base||get_variable)return false;
    image_base=base;
    get_variable=reinterpret_cast<GetVariable>(base+0x10a5390);
    return true;
}

bool owns_2d_transform(const void* owner) noexcept {
    // Never flatten a world-space movie or an unexpected owner/movie class.
    auto* movie=checked_movie(owner);if(!movie)return false;
    Value value;
    queried.fetch_add(1,std::memory_order_relaxed);
    const bool found=get_variable(movie,&value,"root.codexNativeLayoutReady");
    // No coercion: strings, numbers, objects and undefined cannot opt in.
    const bool ready=found&&value.type==0x02&&(value.data&0xff)==1;
    release_value(value);
    (ready?accepted:missing).fetch_add(1,std::memory_order_relaxed);
    return ready;
}

bool read_layout_metrics(const void* owner,LayoutMetrics& result) noexcept {
    auto* movie=checked_movie(owner);if(!movie)return false;
    LayoutMetrics copy{};copy.movie=reinterpret_cast<std::uintptr_t>(movie);
    const auto* bytes=static_cast<const unsigned char*>(owner);
    std::memcpy(copy.viewport,bytes+0x234,sizeof copy.viewport);
    std::memcpy(copy.view,bytes+0x150,sizeof copy.view);
    std::memcpy(copy.projection,bytes+0x110,sizeof copy.projection);
    constexpr const char* paths[]={"root.stage.stageWidth","root.stage.stageHeight",
        "root.scaleX","root.scaleY","root.x","root.y","root.codexLayoutResourceId"};
    for(unsigned i=0;i<7;++i){
        Value value;const bool found=get_variable(movie,&value,paths[i]);
        bool valid=found;
        if(value.type==3)copy.values[i]=static_cast<std::int32_t>(value.data);
        else if(value.type==4)copy.values[i]=static_cast<std::uint32_t>(value.data);
        else if(value.type==5)std::memcpy(&copy.values[i],&value.data,sizeof(double));
        else valid=false;
        if(valid&&std::isfinite(copy.values[i]))copy.valid_fields|=1u<<i;
        release_value(value);
    }
    result=copy;return true;
}

bool get_movie_probe(const void* owner,MovieProbe& result) noexcept {
    auto* movie=checked_movie(owner);
    if(!movie)return false;
    result={reinterpret_cast<std::uintptr_t>(movie),read<unsigned>(owner,0x244),read<unsigned>(owner,0x248)};
    return result.width&&result.height;
}

bool read_probe_number(const MovieProbe& probe,const char* path,double& number) noexcept {
    Value value;
    bool valid=get_variable(reinterpret_cast<void*>(probe.id),&value,path);
    double metric{};
    switch(value.type){
        case 2: metric=(value.data&0xff)!=0;break;
        case 3: metric=static_cast<std::int32_t>(value.data);break;
        case 4: metric=static_cast<std::uint32_t>(value.data);break;
        case 5: std::memcpy(&metric,&value.data,sizeof metric);break;
        default: valid=false;break;
    }
    release_value(value);
    if(!valid||!std::isfinite(metric))return false;
    number=metric;return true;
}

Counters counters() noexcept {
    return {queried.load(std::memory_order_relaxed),accepted.load(std::memory_order_relaxed),missing.load(std::memory_order_relaxed)};
}
}
