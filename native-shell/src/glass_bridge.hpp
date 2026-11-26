#pragma once
#include <windows.h>
#include <filesystem>
#include "caelestia/core.hpp"
namespace caelestia {
// Adapter to the existing MIT renderer ABI. The renderer retains its own worker
// and GPU device in Phase 1; it is not represented as a unified pipeline yet.
class GlassBridge {
public:
    ~GlassBridge();
    bool open(HWND owner, const std::filesystem::path& dll);
    void configure(UINT width, UINT height, float dpi, const Config& config, int refresh);
    void suspend(bool hidden);
    bool ready() const;
    bool failed() const;
    void close();
private:
    HMODULE module_ = nullptr;
    void* context_ = nullptr;
    using Create = void* (__cdecl*)(HWND,int);
    using Set = void (__cdecl*)(void*,const float*,int,const float*,int);
    using Look = void (__cdecl*)(void*,float,float);
    using Fps = void (__cdecl*)(void*,int);
    using Destroy = void (__cdecl*)(void*);
    using Shutdown = void (__cdecl*)();
    using Info = void (__cdecl*)(void*,long*,long*,int*);
    using Error = void (__cdecl*)(void*,int*,long*);
    Set set_ = nullptr;
    Look look_ = nullptr, look2_ = nullptr;
    Fps fps_ = nullptr, suspend_ = nullptr;
    Destroy destroy_ = nullptr;
    Shutdown shutdown_ = nullptr;
    Info info_ = nullptr;
    Error error_ = nullptr;
};
}
