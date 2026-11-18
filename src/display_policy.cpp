#include "display_policy.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace detroit::adaptive {
namespace {
void positive(double v) { if(!std::isfinite(v)||v<=0) throw std::invalid_argument("Expected finite positive dimension"); }
void valid(Size s) { positive(s.width); positive(s.height); }
void valid(Rect r) { valid(Size{r.width,r.height}); if(!std::isfinite(r.x)||!std::isfinite(r.y)) throw std::invalid_argument("Invalid origin"); }
void unit(Point p) { if(!std::isfinite(p.x)||!std::isfinite(p.y)||p.x<0||p.x>1||p.y<0||p.y>1) throw std::invalid_argument("Anchor outside unit square"); }
}
Point Transform::to_screen(Point p) const { positive(scale); return {p.x*scale+offset.x,p.y*scale+offset.y}; }
Point Transform::to_local(Point p) const { positive(scale); return {(p.x-offset.x)/scale,(p.y-offset.y)/scale}; }
Projection expand_projection(double vfov,double reference_aspect,Size target) {
    valid(target);positive(reference_aspect);
    if(!std::isfinite(vfov)||vfov<=0||vfov>=3.14159265358979323846) throw std::invalid_argument("FOV must be in (0, pi)");
    const double aspect=target.width/target.height;
    const double half_y=std::tan(vfov/2)*std::max(1.0,reference_aspect/aspect);
    const double half_x=half_y*aspect;
    if(!std::isfinite(half_x)||!std::isfinite(half_y)) throw std::invalid_argument("Projection overflow");
    return {2*std::atan(half_x),2*std::atan(half_y),1/half_x,1/half_y};
}
Transform contain(Size source,Rect destination) {
    valid(source);valid(destination);
    const double s=std::min(destination.width/source.width,destination.height/source.height);
    return {s,{destination.x+(destination.width-source.width*s)/2,
               destination.y+(destination.height-source.height*s)/2}};
}
MediaPlacement place_media(Size source,Rect dest,MediaKind kind,bool crop) {
    valid(source);valid(dest);
    if(crop&&kind!=MediaKind::PrerecordedVideo) throw std::invalid_argument("Only prerecorded video may be cropped");
    if(!crop) {
        auto t=contain(source,dest);
        return {t,{0,0,1,1},{t.offset.x,t.offset.y,source.width*t.scale,source.height*t.scale}};
    }
    const double s=std::max(dest.width/source.width,dest.height/source.height);
    const double u=dest.width/(source.width*s),v=dest.height/(source.height*s);
    Transform t{s,{dest.x+(dest.width-source.width*s)/2,dest.y+(dest.height-source.height*s)/2}};
    return {t,{(1-u)/2,(1-v)/2,u,v},dest};
}
Rect anchor_component(Size original,Rect dest,Point anchor,Point inset,double scale) {
    valid(original);valid(dest);unit(anchor);positive(scale);
    if(!std::isfinite(inset.x)||!std::isfinite(inset.y)||inset.x<0||inset.y<0) throw std::invalid_argument("Invalid inset");
    const double w=original.width*scale,h=original.height*scale;
    if(w+2*inset.x>dest.width||h+2*inset.y>dest.height) throw std::invalid_argument("Component does not fit; reflow required");
    return {dest.x+inset.x+(dest.width-2*inset.x-w)*anchor.x,
            dest.y+inset.y+(dest.height-2*inset.y-h)*anchor.y,w,h};
}
std::vector<Rect> flow_components(const std::vector<Size>& items,Rect dest,double scale,double gap) {
    valid(dest);positive(scale);
    if(!std::isfinite(gap)||gap<0) throw std::invalid_argument("Invalid gap");
    if(items.empty()) return {};
    for(auto i:items) { valid(i);scale=std::min(scale,dest.width/i.width); }
    auto layout=[&](double s) {
        std::vector<Rect> rows;double x=0,y=0,row_height=0;
        for(auto i:items) {
            const double w=i.width*s,h=i.height*s;
            if(x>0&&x+w>dest.width+1e-8) {x=0;y+=row_height+gap*s;row_height=0;}
            rows.push_back({dest.x+x,dest.y+y,w,h});
            x+=w+gap*s;row_height=std::max(row_height,h);
        }
        return rows;
    };
    auto fits=[&](const std::vector<Rect>& rows) {return std::all_of(rows.begin(),rows.end(),[&](auto r){return contains(dest,r);});};
    auto rows=layout(scale);
    if(fits(rows)) return rows;
    double lo=0,hi=scale;
    for(int i=0;i<80;++i) {const double mid=(lo+hi)/2;if(fits(layout(mid)))lo=mid;else hi=mid;}
    return layout(lo);
}
bool contains(Rect a,Rect b,double t) {return b.x>=a.x-t&&b.y>=a.y-t&&b.x+b.width<=a.x+a.width+t&&b.y+b.height<=a.y+a.height+t;}
}
