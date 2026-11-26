#pragma once
#include <windows.h>
#include <d3d11.h>
#include <dxgi1_3.h>
#include <d2d1_1.h>
#include <dwrite_3.h>
#include <dcomp.h>
#include <wrl/client.h>
#include <filesystem>
#include <map>
#include <string>
#include "caelestia/core.hpp"

namespace caelestia {
void check(HRESULT hr, const char* operation);
struct BarScene {
    std::wstring title, clock;
    WorkspaceState workspaces;
    double indicator = 0;
    float hover = 0;
    bool glass_ready = false;
};
class RenderDevice {
public:
    void initialize(HWND window, UINT width, UINT height, float dpi,
                    const Theme& theme, const std::filesystem::path& config);
    void resize(UINT width, UINT height, float dpi);
    void set_theme(const Theme& theme);
    bool draw(const BarScene& scene);
    void compose(float opacity, float offset_y);
    HANDLE frame_ready() const { return frame_ready_; }
    ~RenderDevice();
private:
    void target();
    void text(const std::wstring& value, float left, float top, float width, float size,
              Color color, bool right = false);
    Microsoft::WRL::ComPtr<ID3D11Device> d3d_;
    Microsoft::WRL::ComPtr<ID3D11DeviceContext> context_;
    Microsoft::WRL::ComPtr<IDXGISwapChain2> swap_;
    Microsoft::WRL::ComPtr<ID2D1Factory1> factory_;
    Microsoft::WRL::ComPtr<ID2D1Device> device_;
    Microsoft::WRL::ComPtr<ID2D1DeviceContext> d2d_;
    Microsoft::WRL::ComPtr<ID2D1Bitmap1> bitmap_;
    Microsoft::WRL::ComPtr<ID2D1SolidColorBrush> brush_;
    Microsoft::WRL::ComPtr<IDWriteFactory> write_;
    Microsoft::WRL::ComPtr<IDWriteFontCollection> fonts_;
    Microsoft::WRL::ComPtr<IDCompositionDevice> composition_;
    Microsoft::WRL::ComPtr<IDCompositionTarget> composition_target_;
    Microsoft::WRL::ComPtr<IDCompositionVisual> visual_;
    Microsoft::WRL::ComPtr<IDCompositionEffectGroup> opacity_;
    std::map<std::wstring, Microsoft::WRL::ComPtr<IDWriteTextLayout>> layouts_;
    Theme theme_;
    HANDLE frame_ready_ = nullptr;
    UINT width_ = 1, height_ = 1;
    float dpi_ = 96;
    bool custom_fonts_ = false;
};
}
