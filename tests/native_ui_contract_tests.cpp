// Includes the implementation only in this isolated process; no game access.
#include "../src/native_ui_contract.cpp"
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>

using namespace adaptive::native_ui_contract;
namespace {
constexpr std::uintptr_t base=0x140000000;
std::array<unsigned char,0x280> owner{};
std::array<std::uintptr_t,4> movie{};
std::array<std::uintptr_t,3> interface_vtable{};
struct Interface {std::uintptr_t* vtable; } interface_object{interface_vtable.data()};
std::uint32_t output_type=2;
std::uintptr_t output_data=1;
bool output_found=true;
bool metric_mode=false;
unsigned lookups{},releases{};
template<class T> void write(std::size_t offset,T value) {std::memcpy(owner.data()+offset,&value,sizeof value);}
void release_fake(void* object,Value* value,std::uintptr_t payload) {
    assert(object==&interface_object&&value->interface_ptr==object&&payload==output_data);
    ++releases;
}
bool lookup_fake(void* object,Value* value,const char* path) {
    ++lookups;
    assert(object==movie.data());
    assert(metric_mode||std::strcmp(path,"root.codexNativeLayoutReady")==0);
    assert(value->previous==UINT64_MAX&&value->next==UINT64_MAX);
    assert(value->interface_ptr==nullptr&&value->type==0&&value->data==0);
    value->type=output_type;value->data=output_data;
    if(output_type&0x40)value->interface_ptr=&interface_object;
    return output_found;
}
void reset_owner() {
    owner.fill(0);write(0,base+0x1e8ecc8);write<unsigned char>(0xec,3);
    movie[0]=base+0x1a06e78;write(0x1b0,movie.data());
}
}
int main() {
    assert(!owns_2d_transform(nullptr));
    assert(!configure(0));assert(configure(base));assert(!configure(base));
    get_variable=&lookup_fake;
    interface_vtable[2]=reinterpret_cast<std::uintptr_t>(&release_fake);
    reset_owner();const auto unchanged=owner;
    assert(owns_2d_transform(owner.data()));assert(owner==unchanged);
    output_data=0;assert(!owns_2d_transform(owner.data()));
    output_data=1;
    for(auto type:{0u,1u,3u,4u,5u,6u,8u,10u}) {
        output_type=type;assert(!owns_2d_transform(owner.data()));
    }
    // Unexpected managed objects must be released, and must not take ownership.
    output_type=0x48;output_data=123;assert(!owns_2d_transform(owner.data()));assert(releases==1);
    output_found=false;assert(!owns_2d_transform(owner.data()));assert(releases==2);
    output_type=2;output_data=1;assert(!owns_2d_transform(owner.data()));
    output_found=true;unsigned before=lookups;
    for(unsigned char mode:{0,1,2,4}) {
        write(0xec,mode);assert(!owns_2d_transform(owner.data()));
    }
    reset_owner();write<std::uintptr_t>(0xc8,1);assert(!owns_2d_transform(owner.data()));
    reset_owner();write<std::uintptr_t>(0,0);assert(!owns_2d_transform(owner.data()));
    reset_owner();write<std::uintptr_t>(0x1b0,0);assert(!owns_2d_transform(owner.data()));
    reset_owner();movie[0]=0;assert(!owns_2d_transform(owner.data()));
    assert(lookups==before);reset_owner();
    // No cached acceptance: resource changes, delayed initialization and
    // teardown must be observed without retaining AS objects or movie pointers.
    for(unsigned i=0;i<1200;++i) {
        output_found=(i%3)!=0;output_data=(i%5)!=0;
        assert(owns_2d_transform(owner.data())==(output_found&&output_data==1));
    }
    assert(owner==unchanged);
    metric_mode=true;LayoutMetrics metrics{};
    output_found=true;output_type=3;output_data=static_cast<std::uint32_t>(-42);
    assert(read_layout_metrics(owner.data(),metrics)&&metrics.valid_fields==127);
    for(auto value:metrics.values)assert(value==-42);
    output_type=4;output_data=1920;assert(read_layout_metrics(owner.data(),metrics));
    for(auto value:metrics.values)assert(value==1920);
    output_type=5;double scalar=1.25;std::memcpy(&output_data,&scalar,sizeof scalar);
    assert(read_layout_metrics(owner.data(),metrics)&&metrics.valid_fields==127);
    for(auto value:metrics.values)assert(value==1.25);
    scalar=std::numeric_limits<double>::quiet_NaN();std::memcpy(&output_data,&scalar,sizeof scalar);
    assert(read_layout_metrics(owner.data(),metrics)&&metrics.valid_fields==0);
    output_type=2;output_data=1;assert(read_layout_metrics(owner.data(),metrics)&&metrics.valid_fields==0);
    output_type=0x48;output_data=123;const auto released_before=releases;
    assert(read_layout_metrics(owner.data(),metrics)&&metrics.valid_fields==0&&releases==released_before+7);
    assert(!read_layout_metrics(nullptr,metrics));
    std::puts("PASS: exact ABI/value initialization, strict boolean opt-in, world/owner/movie rejection, managed-value lifetime, 1200 state transitions, owner untouched");
}
