#include "caelestia/core.hpp"

#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace {
int checks=0;
void expect(bool condition,const char* message) {
    ++checks;
    if (!condition) throw std::runtime_error(message);
}
void near(double actual,double expected,double tolerance,const char* message) {
    expect(std::isfinite(actual)&&std::abs(actual-expected)<=tolerance,message);
}
void write(const std::filesystem::path& path,const char* contents) {
    std::filesystem::create_directories(path.parent_path());
    std::ofstream file(path,std::ios::binary);file<<contents;
    if (!file) throw std::runtime_error("fixture write failed");
}
struct TemporaryDirectory {
    std::filesystem::path path=std::filesystem::temp_directory_path()/
        ("caelestia-core-tests-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    TemporaryDirectory() {std::filesystem::create_directories(path);}
    ~TemporaryDirectory() {std::error_code error;std::filesystem::remove_all(path,error);}
};

void test_motion() {
    using namespace caelestia;
    CubicBezier spatial;
    near(spatial.value(0.),0.,0.,"bezier starts exactly");
    near(spatial.value(1.),1.,0.,"bezier ends exactly");
    expect(spatial.value(.8)>1.,"spatial token retains overshoot");
    const double h=1e-6;
    near(spatial.slope(.27),(spatial.value(.27+h)-spatial.value(.27-h))/(2*h),1e-6,"bezier derivative matches position");
    near(CubicBezier{0.,0.,1.,1.}.value(.42),.42,1e-10,"linear bezier inversion");

    Spring reference(0.);reference.retarget(120.,0.);
    const auto first=reference.sample(.137);
    reference.retarget(-20.,.137);
    near(reference.sample(.137).position,first.position,1e-10,"spring reversal preserves position");
    near(reference.sample(.137).velocity,first.velocity,1e-10,"spring reversal preserves velocity");
    const auto expected=reference.sample(.683);
    for (const int hz:{60,120,144,165,240}) {
        Spring sampled(0.);sampled.retarget(120.,0.);
        for (int frame=0;static_cast<double>(frame)/hz<.137;++frame) (void)sampled.sample(static_cast<double>(frame)/hz);
        sampled.retarget(-20.,.137);
        for (int frame=0;static_cast<double>(frame)/hz<.683;++frame) (void)sampled.sample(static_cast<double>(frame)/hz);
        near(sampled.sample(.683).position,expected.position,1e-10,"spring position independent of display rate");
        near(sampled.sample(.683).velocity,expected.velocity,1e-10,"spring velocity independent of display rate");
    }
    reference.retarget(40.,1.,false);
    near(reference.sample(1.).position,40.,0.,"spring reduced motion snaps");
    near(reference.sample(1.).velocity,0.,0.,"spring reduced motion stops velocity");
    expect(!reference.active(1.),"snapped spring does not request idle frames");
    for (const double damping:{.2,.85,1.,1.2,3.}) {
        Spring spring(4.,20.,damping);spring.retarget(80.,2.);
        near(spring.sample(2.).position,4.,1e-10,"all damping cases preserve initial position");
        near(spring.sample(2.).velocity,0.,1e-10,"all damping cases preserve initial velocity");
        near(spring.sample(10000.).position,80.,1e-10,"spring settles after long pause");
        expect(!spring.active(10000.),"settled spring allows idle sleep");
    }

    BezierTransition tween(10.);tween.retarget(100.,0.,.56,spatial);
    near(tween.sample(0.).velocity,0.,1e-10,"bezier begins from rest without velocity jump");
    const auto before=tween.sample(.173);
    tween.retarget(-15.,.173,.22,spatial);
    near(tween.sample(.173).position,before.position,1e-10,"bezier retarget preserves position");
    near(tween.sample(.173).velocity,before.velocity,1e-9,"bezier retarget preserves velocity");
    near(tween.sample(.173+.22).position,-15.,1e-10,"bezier ends at reverse target");
    near(tween.sample(.173+.22).velocity,0.,1e-8,"bezier ends at rest");
    expect(!tween.active(1.),"finished bezier allows idle sleep");
    BezierTransition fast(0.);fast.retarget(1.,0.,.3,{.42,1.67,.21,.9});
    near(fast.sample(.3-1e-8).velocity,0.,1e-5,"fast curve ends without velocity snap");
    fast.retarget(20.,1.,.5,spatial,false);
    near(fast.sample(1.).position,20.,0.,"reduced motion bypasses transition");
    expect(!fast.active(1.),"reduced motion requests no animation frames");
    MotionProfile profile;
    near(profile.duration("launcher"),.56,1e-10,"duration units are seconds");
    profile.scale=2.;near(profile.duration("close"),.44,1e-10,"duration uses shared scale");
    profile.enabled=false;near(profile.duration("launcher"),0.,0.,"disabled motion has zero duration");
}

void test_configuration(const std::filesystem::path& actual_config) {
    using namespace caelestia;
    const Config actual=load_config(actual_config);
    expect(actual.warnings.empty(),"repository configuration parses without warning");
    expect(actual.profile=="light","repository selected light palette is retained");
    near(actual.theme.mantle.r,250/255.,1e-6,"existing palette is loaded");
    near(actual.motion.spatial.y1,1.21,1e-10,"existing spatial overshoot is loaded");
    near(actual.motion.duration("popup"),.44,1e-10,"existing popup duration is loaded");
    near(actual.glass.frost,.2,1e-6,"existing optical preferences are loaded");
    expect(actual.theme.font_family==L"JetBrainsMono NFP Light","existing typography is loaded");
    expect(actual.theme.font_weight==600,"existing font weight is retained");

    TemporaryDirectory temporary;
    write(temporary.path/"theme.json",R"({"name":"custom"})");
    write(temporary.path/"theme-profiles/custom/palette.json",R"({"MANTLE":"#112233","BASE":"#112233","SURFACE":"#112233","SURFACE2":"#112233","TEXT":"#ffffff"})");
    write(temporary.path/"bar-settings.json",R"({"appearance":{"font_family":"Ph\u00f4ng \ud83c\udf19","font_size":15,"font_weight":700},"island":{"fps":165,"speed":1.5,"liquid_fps":240,"liquid_refraction":99},"animations":{"enabled":false},"palette":{"MANTLE":"#223344"}})");
    write(temporary.path/"motion-profile.json",R"({"curves":{"spatial":[0.38,1.21,0.22,1]},"durations":{"control":200}})");
    const auto custom=load_config(temporary.path);
    expect(custom.warnings.empty(),"custom JSON and unicode escapes parse");
    near(custom.theme.mantle.r,34/255.,1e-6,"custom palette overrides selected preset");
    expect(custom.theme.font_family==L"Ph\u00f4ng \U0001f319","UTF8 and surrogate pairs convert correctly");
    expect(custom.motion.fps==165&&custom.glass.max_fps==240,"UI and glass caps stay distinct");
    near(custom.glass.refraction,1.,0.,"out of range glass value retains default");
    near(custom.motion.duration("control"),0.,0.,"disabled preference reaches motion engine");

    write(temporary.path/"theme.json",R"({"name":"../../outside"})");
    write(temporary.path/"bar-settings.json",R"({"appearance":{"font_size":1e999},"animations":true})");
    write(temporary.path/"motion-profile.json",R"({"durations":{"popup":-12},"curves":{"spatial":[2,1,2,1]}})");
    const auto invalid=load_config(temporary.path);
    expect(!invalid.warnings.empty(),"corrupt and unsafe configuration produces diagnostics");
    expect(invalid.profile=="catppuccin","profile traversal is rejected");
    near(invalid.theme.font_size,12.,0.,"corrupt preferences retain safe typography");
    near(invalid.motion.popup_ms,440.,0.,"invalid duration retains shared default");
    near(invalid.motion.spatial.x1,.38,0.,"non-monotone bezier token rejected");

    write(temporary.path/"bar-settings.json",R"({"appearance":{"font_family":"\ud800"}})");
    const auto malformed_unicode=load_config(temporary.path);
    expect(malformed_unicode.theme.font_family==L"JetBrainsMono NFP Light","unpaired surrogate does not reach Windows text rendering");
}

void test_komorebi() {
    using namespace caelestia;
    const auto raw=R"({"monitors":{"elements":[{"workspaces":{"focused":1,"elements":[{"containers":{"elements":[]},"floating_windows":[],"layout":{"Default":"BSP"}},{"containers":{"elements":[{"windows":{"elements":[{"hwnd":123}]}}]},"layout":{"Default":"Columns"}},{"containers":{"elements":[]},"floating_windows":{"elements":[{"hwnd":456}]}},{"monocle_container":{"windows":{"elements":[]}}},{"maximized_window":{"hwnd":789}}]}}]}})";
    const auto state=parse_komorebi_state(raw);
    expect(state.connected,"real state schema connects");
    expect(state.focused_workspace==1&&state.monitor_index==0,"focused workspace comes from state");
    expect(state.layout==L"Columns","actual focused layout is read");
    expect(state.populated.size()==5&&!state.populated[0]&&state.populated[1]&&state.populated[2]&&state.populated[3]&&state.populated[4],"workspace window kinds determine occupied stars");
    const auto notification=parse_komorebi_state(std::string("{\"event\":{},\"state\":")+raw+"}");
    expect(notification.connected&&notification.populated==state.populated,"named pipe notification schema is accepted");
    expect(!parse_komorebi_state(raw,2).connected,"unavailable monitor is disconnected");
    expect(!parse_komorebi_state(raw,-1).connected,"negative monitor is disconnected");
    expect(!parse_komorebi_state("garbage").connected,"corrupt notification does not fabricate workspaces");
    expect(!parse_komorebi_state(R"({"monitors":{"elements":[{"workspaces":{"focused":3,"elements":[{}]}}]}})").connected,"out of range focus rejects partial state");
    expect(!parse_komorebi_state(R"({"monitors":{"elements":[{"workspaces":{"focused":0.5,"elements":[{}]}}]}})").connected,"nonintegral focus is rejected");
}
} // namespace

int main(int argc,char** argv) {
    try {
        const auto config=argc>1?std::filesystem::path(argv[1]):std::filesystem::path(__FILE__).parent_path().parent_path().parent_path()/"config";
        test_motion();test_configuration(config);test_komorebi();
        std::cout<<"Passed "<<checks<<" native core checks\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"Native core check failed: "<<error.what()<<'\n';return 1;
    }
}
