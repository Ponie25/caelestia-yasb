#include "caelestia/core.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <map>
#include <stdexcept>
#include <variant>

namespace caelestia {
namespace {

struct Json {
    using Object=std::map<std::string,Json,std::less<>>;
    using Array=std::vector<Json>;
    std::variant<std::nullptr_t,bool,double,std::string,Array,Object> data{nullptr};
    const Json& operator[](std::string_view key) const {
        static const Json empty;
        const auto* object=std::get_if<Object>(&data);
        if (!object) return empty;
        const auto it=object->find(key);
        return it==object->end()?empty:it->second;
    }
    std::string string(std::string fallback={}) const {
        const auto* value=std::get_if<std::string>(&data); return value?*value:fallback;
    }
    double number(double fallback) const {
        const auto* value=std::get_if<double>(&data); return value?*value:fallback;
    }
    bool boolean(bool fallback) const {
        const auto* value=std::get_if<bool>(&data); return value?*value:fallback;
    }
};

void append_utf8(std::string& text,unsigned code) {
    if (code<=0x7f) text.push_back(static_cast<char>(code));
    else if (code<=0x7ff) {
        text.push_back(static_cast<char>(0xc0|(code>>6)));
        text.push_back(static_cast<char>(0x80|(code&0x3f)));
    } else if (code<=0xffff) {
        text.push_back(static_cast<char>(0xe0|(code>>12)));
        text.push_back(static_cast<char>(0x80|((code>>6)&0x3f)));
        text.push_back(static_cast<char>(0x80|(code&0x3f)));
    } else {
        text.push_back(static_cast<char>(0xf0|(code>>18)));
        text.push_back(static_cast<char>(0x80|((code>>12)&0x3f)));
        text.push_back(static_cast<char>(0x80|((code>>6)&0x3f)));
        text.push_back(static_cast<char>(0x80|(code&0x3f)));
    }
}

class Parser {
public:
    explicit Parser(std::string_view text):text_(text){}
    Json parse() {
        auto result=value(0); space();
        if (position_!=text_.size()) fail();
        return result;
    }
private:
    std::string_view text_;
    std::size_t position_{};
    [[noreturn]] void fail() const { throw std::runtime_error("invalid JSON at byte "+std::to_string(position_)); }
    void space() { while (position_<text_.size() && (text_[position_]==' '||text_[position_]=='\n'||text_[position_]=='\r'||text_[position_]=='\t')) ++position_; }
    bool take(char ch) { space(); if (position_<text_.size() && text_[position_]==ch) {++position_;return true;} return false; }
    void expect(char ch) { if (!take(ch)) fail(); }
    unsigned hex4() {
        unsigned result=0;
        for (int i=0;i<4;++i) {
            if (position_>=text_.size()) fail();
            const char c=text_[position_++];
            const int digit=c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;
            if (digit<0) fail();
            result=result*16+static_cast<unsigned>(digit);
        }
        return result;
    }
    std::string string() {
        expect('"'); std::string result;
        while (position_<text_.size()) {
            const unsigned char c=static_cast<unsigned char>(text_[position_++]);
            if (c=='"') return result;
            if (c<0x20) fail();
            if (c!='\\') {result.push_back(static_cast<char>(c));continue;}
            if (position_>=text_.size()) fail();
            switch (text_[position_++]) {
            case '"': result+='"';break; case '\\': result+='\\';break; case '/': result+='/';break;
            case 'b': result+='\b';break; case 'f': result+='\f';break; case 'n': result+='\n';break;
            case 'r': result+='\r';break; case 't': result+='\t';break;
            case 'u': {
                unsigned code=hex4();
                if (code>=0xd800&&code<=0xdbff) {
                    if (position_+2>text_.size()||text_[position_]!='\\'||text_[position_+1]!='u') fail();
                    position_+=2; const unsigned low=hex4();
                    if (low<0xdc00||low>0xdfff) fail();
                    code=0x10000+((code-0xd800)<<10)+(low-0xdc00);
                } else if (code>=0xdc00&&code<=0xdfff) fail();
                append_utf8(result,code);break;
            }
            default: fail();
            }
        }
        fail();
    }
    Json value(unsigned depth) {
        if (depth>64) fail();
        space(); if (position_>=text_.size()) fail();
        if (text_[position_]=='{') {
            ++position_; Json::Object object;
            if (take('}')) return Json{object};
            do {const auto key=string();expect(':');object[key]=value(depth+1);} while (take(','));
            expect('}');return Json{object};
        }
        if (text_[position_]=='[') {
            ++position_; Json::Array array;
            if (take(']')) return Json{array};
            do {array.push_back(value(depth+1));} while (take(','));
            expect(']');return Json{array};
        }
        if (text_[position_]=='"') return Json{string()};
        for (const auto word:{std::string_view("true"),std::string_view("false"),std::string_view("null")}) {
            if (text_.substr(position_,word.size())==word) {
                position_+=word.size();
                if (word=="null") return {};
                return Json{word=="true"};
            }
        }
        const auto start=position_;
        if (text_[position_]=='-') ++position_;
        if (position_>=text_.size()) fail();
        if (text_[position_]=='0') ++position_;
        else {
            if (text_[position_]<'1'||text_[position_]>'9') fail();
            while (position_<text_.size()&&text_[position_]>='0'&&text_[position_]<='9') ++position_;
        }
        if (position_<text_.size()&&text_[position_]=='.') {
            ++position_;const auto digits=position_;
            while (position_<text_.size()&&text_[position_]>='0'&&text_[position_]<='9') ++position_;
            if (digits==position_) fail();
        }
        if (position_<text_.size()&&(text_[position_]=='e'||text_[position_]=='E')) {
            ++position_;if (position_<text_.size()&&(text_[position_]=='+'||text_[position_]=='-')) ++position_;
            const auto digits=position_;
            while (position_<text_.size()&&text_[position_]>='0'&&text_[position_]<='9') ++position_;
            if (digits==position_) fail();
        }
        const std::string token(text_.substr(start,position_-start));
        char* end=nullptr;const double number=std::strtod(token.c_str(),&end);
        if (!end||*end||!std::isfinite(number)) fail();
        return Json{number};
    }
};

Json read_json(const std::filesystem::path& path,std::vector<std::string>& warnings) {
    try {
        std::ifstream file(path,std::ios::binary|std::ios::ate);
        if (!file) throw std::runtime_error("file unavailable");
        const auto size=file.tellg();
        if (size<0||size>2*1024*1024) throw std::runtime_error("file exceeds 2 MiB limit");
        std::string text(static_cast<std::size_t>(size),'\0');
        file.seekg(0);if (!text.empty()&&!file.read(text.data(),size)) throw std::runtime_error("read failed");
        if (text.size()>=3&&text.substr(0,3)=="\xef\xbb\xbf") text.erase(0,3);
        Json result=Parser(text).parse();
        if (!std::holds_alternative<Json::Object>(result.data)) throw std::runtime_error("root must be an object");
        return result;
    } catch (const std::exception& error) {
        warnings.push_back(path.filename().string()+": "+error.what()+"; defaults retained");
        return {};
    }
}

double bounded(const Json& value,double fallback,double low,double high) {
    const double number=value.number(fallback);
    return std::isfinite(number)&&number>=low&&number<=high?number:fallback;
}

Color color(const Json& value,Color fallback) {
    const auto text=value.string();if (text.size()!=7||text[0]!='#') return fallback;
    unsigned channels[3]{};
    for (int i=0;i<6;++i) {
        const char c=text[static_cast<std::size_t>(i)+1];
        const int n=c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;
        if (n<0) return fallback;
        channels[i/2]=channels[i/2]*16+static_cast<unsigned>(n);
    }
    return {channels[0]/255.f,channels[1]/255.f,channels[2]/255.f,1.f};
}

double luminance(Color c) {
    const auto linear=[](double n){return n<=.04045?n/12.92:std::pow((n+.055)/1.055,2.4);};
    return linear(c.r)*.2126+linear(c.g)*.7152+linear(c.b)*.0722;
}
double contrast(Color a,Color b) {
    const auto low=std::min(luminance(a),luminance(b));
    return (std::max(luminance(a),luminance(b))+.05)/(low+.05);
}
Color readable(Color ink,const std::array<Color,4>& backgrounds,double minimum) {
    const auto worst=[&](Color c){double result=100.;for (auto bg:backgrounds)result=std::min(result,contrast(c,bg));return result;};
    if (worst(ink)>=minimum) return ink;
    const Color dark{17/255.f,17/255.f,24/255.f,1.f},light{1.f,1.f,1.f,1.f};
    const auto target=worst(dark)>worst(light)?dark:light;
    for (int step=1;step<=100;++step) {
        const float amount=step/100.f;
        const Color candidate{ink.r+(target.r-ink.r)*amount,ink.g+(target.g-ink.g)*amount,ink.b+(target.b-ink.b)*amount,1.f};
        if (worst(candidate)>=minimum) return candidate;
    }
    return target;
}

std::wstring wide(std::string_view utf8) {
    std::wstring result;
    for (std::size_t i=0;i<utf8.size();) {
        const auto first=static_cast<unsigned char>(utf8[i++]);
        unsigned code=first;int remaining=0;
        if (first>=0xc2&&first<=0xdf) {code=first&0x1f;remaining=1;}
        else if (first>=0xe0&&first<=0xef) {code=first&0x0f;remaining=2;}
        else if (first>=0xf0&&first<=0xf4) {code=first&7;remaining=3;}
        else if (first>=0x80) return {};
        if (i+static_cast<std::size_t>(remaining)>utf8.size()) return {};
        for (int n=0;n<remaining;++n) {
            const auto next=static_cast<unsigned char>(utf8[i++]);if ((next&0xc0)!=0x80) return {};
            code=(code<<6)|(next&0x3f);
        }
        if ((remaining==1&&code<0x80)||(remaining==2&&code<0x800)||(remaining==3&&code<0x10000)||code>0x10ffff||(code>=0xd800&&code<=0xdfff)) return {};
        if constexpr (sizeof(wchar_t)==2) {
            if (code>0xffff) {code-=0x10000;result+=static_cast<wchar_t>(0xd800+(code>>10));result+=static_cast<wchar_t>(0xdc00+(code&0x3ff));continue;}
        }
        result+=static_cast<wchar_t>(code);
    }
    return result;
}

CubicBezier curve(const Json& node,CubicBezier fallback) {
    const auto* values=std::get_if<Json::Array>(&node.data);
    if (!values||values->size()!=4) return fallback;
    std::array<double,4> v{};
    for (std::size_t i=0;i<4;++i) {
        v[i]=(*values)[i].number(99.);
        if (!std::isfinite(v[i])||v[i]<-1.||v[i]>3.) return fallback;
    }
    if (v[0]<0.||v[0]>1.||v[2]<0.||v[2]>1.) return fallback;
    return {v[0],v[1],v[2],v[3]};
}

double polynomial(double t,double a,double b) {const double u=1.-t;return 3*u*u*t*a+3*u*t*t*b+t*t*t;}
double derivative(double t,double a,double b) {const double u=1.-t;return 3*u*u*a+6*u*t*(b-a)+3*t*t*(1.-b);}
double parameter(double progress,const CubicBezier& c) {
    progress=std::clamp(progress,0.,1.);
    double low=0.,high=1.,t=progress;
    for (int i=0;i<40;++i) {
        const double x=polynomial(t,c.x1,c.x2);
        if (std::abs(x-progress)<1e-12) break;
        if (x<progress) low=t;else high=t;
        const double dx=derivative(t,c.x1,c.x2);
        const double next=dx>1e-9?t-(x-progress)/dx:(low+high)/2.;
        t=next>low&&next<high?next:(low+high)/2.;
    }
    return t;
}
double elapsed(double now,double started) {return std::isfinite(now)?std::max(0.,now-started):0.;}

} // namespace

double CubicBezier::value(double progress) const {
    if (progress<=0.) return 0.;if (progress>=1.) return 1.;
    return polynomial(parameter(progress,*this),y1,y2);
}
double CubicBezier::slope(double progress) const {
    const double t=parameter(progress,*this);
    const double dx=derivative(t,x1,x2);
    return dx>1e-9?derivative(t,y1,y2)/dx:0.;
}

double MotionProfile::duration(std::string_view kind) const {
    if (!enabled) return 0.;
    const double ms=kind=="launcher"?launcher_ms:kind=="popup"?popup_ms:kind=="menu"?menu_ms:
        kind=="dialog"?dialog_ms:kind=="page"?page_ms:kind=="section"?section_ms:kind=="control"?control_ms:kind=="close"?close_ms:menu_ms;
    return ms*scale/1000.;
}

Config load_config(const std::filesystem::path& root) {
    Config result;
    const Json selection=read_json(root/"theme.json",result.warnings);
    const auto name=selection["name"].string(result.profile);
    const bool safe=!name.empty()&&name.size()<=64&&std::all_of(name.begin(),name.end(),[](unsigned char c){return (c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-';});
    if (safe) result.profile=name;
    else result.warnings.emplace_back("theme.json: unsafe profile name; default retained");
    const Json palette=read_json(root/"theme-profiles"/result.profile/"palette.json",result.warnings);
    const Json preferences=read_json(root/"bar-settings.json",result.warnings);
    const auto& overrides=preferences["palette"];
    auto token=[&](std::string_view key,Color fallback){return color(overrides[key],color(palette[key],fallback));};
    auto& theme=result.theme;
    theme.base=token("BASE",theme.base);theme.mantle=token("MANTLE",theme.mantle);
    theme.surface=token("SURFACE",theme.surface);theme.surface2=token("SURFACE2",theme.surface2);
    theme.text=token("TEXT",theme.text);theme.muted=token("MUTED",theme.muted);
    theme.accent=token("MAUVE",theme.accent);theme.pink=token("PINK",theme.pink);
    theme.lavender=token("LAVENDER",theme.lavender);theme.overlay=token("OVERLAY",theme.overlay);
    const std::array<Color,4> backgrounds{theme.mantle,theme.base,theme.surface,theme.surface2};
    theme.text=readable(theme.text,backgrounds,7.);theme.muted=readable(theme.muted,backgrounds,4.8);
    theme.accent=readable(theme.accent,backgrounds,4.5);theme.pink=readable(theme.pink,backgrounds,4.5);
    theme.lavender=readable(theme.lavender,backgrounds,4.5);theme.overlay=readable(theme.overlay,backgrounds,3.);
    const auto& appearance=preferences["appearance"];
    const auto family=wide(appearance["font_family"].string());
    if (!family.empty()&&family.size()<=128) theme.font_family=family;
    theme.font_size=static_cast<float>(bounded(appearance["font_size"],theme.font_size,8.,48.));
    theme.font_weight=static_cast<int>(bounded(appearance["font_weight"],theme.font_weight,100.,900.));
    theme.background_opacity=static_cast<float>(bounded(appearance["background_opacity"],0.,0.,1.));
    if (appearance["background_source"].string()=="custom") theme.mantle=color(appearance["background_color"],theme.mantle);
    if (appearance["foreground"].string()=="custom") theme.text=color(appearance["text_color"],theme.text);
    const Json motion=read_json(root/"motion-profile.json",result.warnings);
    auto& profile=result.motion;
    profile.spatial=curve(motion["curves"]["spatial"],profile.spatial);
    profile.fast=curve(motion["curves"]["fast"],profile.fast);
    profile.effects=curve(motion["curves"]["effects"],profile.effects);
    const auto& durations=motion["durations"];
    profile.launcher_ms=bounded(durations["launcher"],profile.launcher_ms,40.,1000.);
    profile.popup_ms=bounded(durations["popup"],profile.popup_ms,40.,1000.);
    profile.menu_ms=bounded(durations["menu"],profile.menu_ms,40.,1000.);
    profile.dialog_ms=bounded(durations["dialog"],profile.dialog_ms,40.,1000.);
    profile.page_ms=bounded(durations["page"],profile.page_ms,40.,1000.);
    profile.section_ms=bounded(durations["section"],profile.section_ms,40.,1000.);
    profile.control_ms=bounded(durations["control"],profile.control_ms,40.,1000.);
    profile.close_ms=bounded(durations["close"],profile.close_ms,40.,1000.);
    const auto& animations=preferences["animations"];
    const auto& island=preferences["island"];
    const auto popup_ms=bounded(animations["popup_ms"],220.,0.,1000.);
    const auto speed=bounded(island["speed"],1.,.15,3.);
    profile.enabled=animations["enabled"].boolean(true)&&popup_ms>0.;
    profile.scale=std::clamp(popup_ms/220.*speed,.15,3.);
    profile.fps=static_cast<int>(bounded(island["fps"],120.,30.,240.));
    auto& glass=result.glass;
    glass.enabled=island["glass"].boolean(true);
    glass.contrast=island["liquid_contrast"].boolean(true);
    glass.refraction=static_cast<float>(bounded(island["liquid_refraction"],1.,0.,2.));
    glass.frost=static_cast<float>(bounded(island["liquid_frost"],.4,0.,1.));
    glass.tint=static_cast<float>(bounded(island["liquid_tint"],.32,0.,.85));
    glass.reflection=static_cast<float>(bounded(island["liquid_reflection"],1.,0.,2.));
    glass.max_fps=static_cast<int>(bounded(island["liquid_fps"],120.,30.,240.));
    result.island_idle_width=bounded(island["idle_width"],116.,60.,600.);
    return result;
}

WorkspaceState parse_komorebi_state(std::string_view json,int monitor_index) {
    WorkspaceState result;
    if (json.size()>16*1024*1024||monitor_index<0) return result;
    try {
        const Json document=Parser(json).parse();
        const Json& state=std::holds_alternative<Json::Object>(document["state"].data)?document["state"]:document;
        const auto* monitors=std::get_if<Json::Array>(&state["monitors"]["elements"].data);
        if (!monitors||static_cast<std::size_t>(monitor_index)>=monitors->size()) return result;
        const auto& workspaces=(*monitors)[static_cast<std::size_t>(monitor_index)]["workspaces"];
        const auto* elements=std::get_if<Json::Array>(&workspaces["elements"].data);
        const double focused=workspaces["focused"].number(-1.);
        if (!elements||elements->empty()||elements->size()>1024||focused<0.||focused>=elements->size()||std::floor(focused)!=focused) return result;
        const auto nonempty=[](const Json& value) {
            const auto* array=std::get_if<Json::Array>(&value.data);
            return array&&!array->empty();
        };
        for (const auto& workspace:*elements) {
            bool populated=nonempty(workspace["floating_windows"])||nonempty(workspace["floating_windows"]["elements"])
                ||std::holds_alternative<Json::Object>(workspace["monocle_container"].data)
                ||std::holds_alternative<Json::Object>(workspace["maximized_window"].data);
            if (const auto* containers=std::get_if<Json::Array>(&workspace["containers"]["elements"].data)) {
                for (const auto& container:*containers) populated=populated||nonempty(container["windows"]["elements"]);
            }
            result.populated.push_back(populated);
        }
        const auto& layout=(*elements)[static_cast<std::size_t>(focused)]["layout"];
        result.layout=wide(layout.string(layout["Default"].string()));
        if (result.layout.empty()&&std::holds_alternative<Json::Object>(layout["Custom"].data)) result.layout=L"Custom";
        if (result.layout.empty()) result.layout=L"BSP";
        result.monitor_index=monitor_index;result.focused_workspace=static_cast<int>(focused);result.connected=true;
    } catch (const std::exception&) {return {};}
    return result;
}

Spring::Spring(double value,double angular_frequency,double damping_ratio):
    initial_(std::isfinite(value)?value:0.),target_(initial_),
    omega_(std::isfinite(angular_frequency)?std::clamp(angular_frequency,.01,1000.):20.),
    damping_(std::isfinite(damping_ratio)?std::clamp(damping_ratio,.01,10.):.85) {}

MotionState Spring::sample(double now) const {
    const double t=elapsed(now,started_),a=initial_-target_;
    double y{},v{};
    if (std::abs(damping_-1.)<1e-4) {
        const double b=velocity_+omega_*a,e=std::exp(-omega_*t);
        y=e*(a+b*t);v=e*(b-omega_*(a+b*t));
    } else if (damping_<1.) {
        const double decay=damping_*omega_,wd=omega_*std::sqrt(1.-damping_*damping_);
        const double b=(velocity_+decay*a)/wd,e=std::exp(-decay*t),c=std::cos(wd*t),s=std::sin(wd*t);
        y=e*(a*c+b*s);v=e*((-decay*a+wd*b)*c+(-decay*b-wd*a)*s);
    } else {
        const double root=std::sqrt(damping_*damping_-1.);
        const double r1=-omega_*(damping_-root),r2=-omega_*(damping_+root);
        const double c1=(velocity_-r2*a)/(r1-r2),c2=a-c1,e1=std::exp(r1*t),e2=std::exp(r2*t);
        y=c1*e1+c2*e2;v=c1*r1*e1+c2*r2*e2;
    }
    return {target_+y,v};
}
void Spring::retarget(double target,double now,bool animate) {
    if (!std::isfinite(target)||!std::isfinite(now)) return;
    if (!animate) {snap(target,now);return;}
    const auto state=sample(now);initial_=state.position;velocity_=state.velocity;target_=target;started_=now;
}
void Spring::snap(double value,double now) {
    if (!std::isfinite(value)||!std::isfinite(now)) return;
    initial_=target_=value;velocity_=0.;started_=now;
}
bool Spring::active(double now) const {const auto state=sample(now);return std::abs(state.position-target_)>.001||std::abs(state.velocity)>.001;}

BezierTransition::BezierTransition(double value):initial_(std::isfinite(value)?value:0.),target_(initial_){}
MotionState BezierTransition::sample(double now) const {
    const double t=elapsed(now,started_);
    if (duration_<=0.||t>=duration_) return {target_,0.};
    const double u=t/duration_,difference=target_-initial_;
    // h(u)=u(1-u)^2 has h(0)=h(1)=h'(1)=0 and h'(0)=1.
    const double residual=correction_*u*(1.-u)*(1.-u)+end_correction_*u*u*(u-1.);
    const double derivative_residual=correction_*(1.-4.*u+3.*u*u)+end_correction_*(3.*u*u-2.*u);
    return {initial_+difference*curve_.value(u)+residual,
            (difference*curve_.slope(u)+derivative_residual)/duration_};
}
void BezierTransition::retarget(double target,double now,double duration_seconds,CubicBezier curve,bool animate) {
    if (!std::isfinite(target)||!std::isfinite(now)) return;
    if (!animate||!std::isfinite(duration_seconds)||duration_seconds<=0.) {snap(target,now);return;}
    const auto previous=sample(now);
    initial_=previous.position;target_=target;started_=now;duration_=duration_seconds;curve_=curve;
    correction_=previous.velocity*duration_-(target_-initial_)*curve_.slope(0.);
    end_correction_=-(target_-initial_)*curve_.slope(1.);
}
void BezierTransition::snap(double value,double now) {
    if (!std::isfinite(value)||!std::isfinite(now)) return;
    initial_=target_=value;started_=now;duration_=correction_=end_correction_=0.;
}
bool BezierTransition::active(double now) const {return duration_>0.&&elapsed(now,started_)<duration_;}

} // namespace caelestia
