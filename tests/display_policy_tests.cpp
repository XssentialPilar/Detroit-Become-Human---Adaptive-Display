#include "display_policy.hpp"
#include <array>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
using namespace detroit::adaptive;
int checks=0;
void check(bool v,const char* message) {++checks;if(!v)throw std::runtime_error(message);}
bool close(double a,double b) {return std::abs(a-b)<1e-7;}
template<class F> void rejects(F f) {bool rejected=false;try{f();}catch(const std::invalid_argument&){rejected=true;}check(rejected,"Invalid operation was accepted");}
int main() {
    try {
        const std::array<Size,21> screens{{{1920,1200},{1200,1200},{1600,1200},{1800,1200},{1500,1200},
          {1200,1500},{2400,1200},{2520,1080},{2850,1200},{2220,1200},{2820,1200},
          {2868,1200},{2880,1200},{3312,1200},{1080,1920},{2160,1080},{2340,1080},
          {2400,1080},{1920,1080},{3440,1440},{7800,400}}};
        const double base_v=0.7504161596298218,base_a=16.0/9;
        const double base_y=std::tan(base_v/2),base_x=base_y*base_a;
        for(auto screen:screens) {
            Rect area{17,23,screen.width,screen.height};
            auto p=expand_projection(base_v,base_a,screen);
            // Reference frustum boundary rays must remain visible on both axes.
            for(double x:{-base_x,0.0,base_x})for(double y:{-base_y,0.0,base_y}) {
                check(std::abs(x*p.x_scale)<=1+1e-8,"Original scene cropped horizontally");
                check(std::abs(y*p.y_scale)<=1+1e-8,"Original scene cropped vertically");
            }
            // Equal world-space X/Y lengths at equal depth must occupy equal pixels.
            check(close(p.x_scale*screen.width,p.y_scale*screen.height),"Projection stretches geometry");
            auto fit=contain({1920,1080},area);
            for(Point point:std::array<Point,5>{{{0,0},{1920,0},{0,1080},{1920,1080},{1000,321}}}) {
                auto out=fit.to_screen(point);auto back=fit.to_local(out);
                check(close(back.x,point.x)&&close(back.y,point.y),"Mouse hit coordinates do not round trip");
                check(contains(area,{out.x,out.y,0,0}),"UI point clipped");
            }
            std::vector<Size> items{{300,50},{300,50},{300,50},{300,50},{300,50}};
            auto rows=flow_components(items,area,1,50);
            check(rows.size()==items.size(),"Lost menu option");
            for(size_t i=0;i<rows.size();++i) {
                auto r=rows[i];check(contains(area,r),"Menu option off screen");
                check(close(r.width/r.height,6),"Menu option deformed");
                for(size_t j=0;j<i;++j) {auto q=rows[j];check(r.x>=q.x+q.width-1e-8||q.x>=r.x+r.width-1e-8||r.y>=q.y+q.height-1e-8||q.y>=r.y+r.height-1e-8,"Menu options overlap");}
            }
            for(auto anchor:std::array<Point,5>{{{0,0},{1,0},{0,1},{1,1},{.5,.5}}}) {
                auto r=anchor_component({160,80},area,anchor,{24,24},1);
                check(contains(area,r)&&close(r.width/r.height,2),"Anchored element clipped or deformed");
            }
            auto still=place_media({1920,1080},area,MediaKind::StillImage,false);
            check(close(still.source_uv.width,1)&&close(still.source_uv.height,1),"Still image cropped");
            check(contains(area,still.destination),"Still image outside screen");
            rejects([&]{place_media({1920,1080},area,MediaKind::StillImage,true);});
            auto video=place_media({1920,1080},area,MediaKind::PrerecordedVideo,true);
            check(close(video.destination.width,area.width)&&close(video.destination.height,area.height),"Video does not cover screen");
            check(close(video.source_uv.width*1920/(video.source_uv.height*1080),screen.width/screen.height),"Video UV crop deforms pixels");
        }
        // Portrait menus must reflow, not merely remain in one compressed row.
        auto portrait=flow_components(std::vector<Size>(5,{300,50}),{0,0,1080,1920},1,50);
        check(portrait[3].y>portrait[0].y&&close(portrait[0].height,50),"Portrait menu failed to reflow at readable scale");
        rejects([]{expand_projection(1,16.0/9,{0,1200});});
        rejects([]{expand_projection(std::numeric_limits<double>::quiet_NaN(),16.0/9,{1920,1200});});
        rejects([]{anchor_component({300,50},{0,0,200,100},{0,0},{0,0},1);});
        rejects([]{flow_components({{300,50}},{0,0,1920,1080},1,-1);});
        std::cout<<"PASS: "<<checks<<" invariant checks across "<<screens.size()<<" display sizes. Engine integration is not tested here.\n";
    }catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
