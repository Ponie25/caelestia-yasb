#include "glass_bridge.hpp"
#include <algorithm>
namespace caelestia {
GlassBridge::~GlassBridge() { close(); }
bool GlassBridge::open(HWND owner, const std::filesystem::path& dll) {
    close();
    // Absolute path + restricted dependency search: never search the working directory.
    module_ = LoadLibraryExW(dll.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!module_) return false;
    const auto create = reinterpret_cast<Create>(GetProcAddress(module_, "lg_create_wgc"));
    set_ = reinterpret_cast<Set>(GetProcAddress(module_, "lg_set"));
    look_ = reinterpret_cast<Look>(GetProcAddress(module_, "lg_set_look"));
    look2_ = reinterpret_cast<Look>(GetProcAddress(module_, "lg_set_look2"));
    fps_ = reinterpret_cast<Fps>(GetProcAddress(module_, "lg_set_fps"));
    suspend_ = reinterpret_cast<Fps>(GetProcAddress(module_, "lg_suspend"));
    destroy_ = reinterpret_cast<Destroy>(GetProcAddress(module_, "lg_destroy"));
    shutdown_ = reinterpret_cast<Shutdown>(GetProcAddress(module_, "lg_shutdown"));
    info_ = reinterpret_cast<Info>(GetProcAddress(module_, "lg_info"));
    error_ = reinterpret_cast<Error>(GetProcAddress(module_, "lg_error"));
    if (!create || !set_ || !look_ || !look2_ || !fps_ || !suspend_ || !destroy_ || !shutdown_ || !info_ || !error_) {
        close(); return false;
    }
    context_ = create(owner, 1);
    if (!context_) { close(); return false; }
    return true;
}
void GlassBridge::configure(UINT width, UINT height, float dpi, const Config& config, int refresh) {
    if (!context_) return;
    const auto& o = config.glass;
    const float scale = dpi / 96.f;
    const bool light = config.theme.mantle.r > .5f;
    float params[] = {1.45f, 7.f*o.refraction, 3.5f, .003f, .85f*o.frost/.4f,
        .04f, .15f, 0.f, .10f, 2.f, .15f, scale, o.contrast ? (light ? -1.f : 1.f) : 0.f};
    const auto tint = light ? Color{.96f,.965f,.98f,1} : Color{.025f,.018f,.025f,1};
    float shape[] = {width/2.f, height/2.f, width/2.f, height/2.f, 0.f,
        1.f,1.f,0.f,tint.r,tint.g,tint.b,o.tint};
    set_(context_, params, 13, shape, 1);
    look_(context_, o.reflection, 1.f); look2_(context_, 0.f, 1.f);
    fps_(context_, std::clamp(refresh, 30, 240));
}
void GlassBridge::suspend(bool hidden) { if (context_) suspend_(context_, hidden ? 1 : 0); }
bool GlassBridge::ready() const {
    if (!context_ || failed()) return false;
    long frames=0, updates=0; int us=0; info_(context_, &frames, &updates, &us);
    return frames > 0;
}
bool GlassBridge::failed() const {
    if (!context_) return true;
    int stage=0; long hr=0; error_(context_, &stage, &hr); return stage != 0;
}
void GlassBridge::close() {
    if (context_ && destroy_) destroy_(context_);
    context_ = nullptr;
    if (module_) {
        if (shutdown_) shutdown_();
        FreeLibrary(module_); module_ = nullptr;
    }
    shutdown_ = nullptr;
}
}
