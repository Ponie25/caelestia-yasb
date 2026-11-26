#include "render_device.hpp"
#include <d2d1_1helper.h>
#include <algorithm>
#include <stdexcept>
#include <cstdio>

namespace caelestia {
using Microsoft::WRL::ComPtr;
void check(HRESULT hr, const char* operation) {
    if (FAILED(hr)) {
        char code[32]{};
        std::snprintf(code, sizeof(code), " (0x%08lX)", static_cast<unsigned long>(hr));
        throw std::runtime_error(std::string(operation) + code);
    }
}
RenderDevice::~RenderDevice() { if (frame_ready_) CloseHandle(frame_ready_); }
void RenderDevice::initialize(HWND window, UINT width, UINT height, float dpi,
                              const Theme& theme, const std::filesystem::path& config) {
    width_ = std::max(1u, width); height_ = std::max(1u, height); dpi_ = dpi;
    D3D_FEATURE_LEVEL level{};
    HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION, &d3d_, &level, &context_);
    if (FAILED(hr)) check(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION, &d3d_, &level, &context_), "D3D11 WARP fallback");
    ComPtr<IDXGIDevice> dxgi;
    check(d3d_.As(&dxgi), "DXGI device");
    ComPtr<IDXGIAdapter> adapter;
    check(dxgi->GetAdapter(&adapter), "DXGI adapter");
    ComPtr<IDXGIFactory2> dxgi_factory;
    check(adapter->GetParent(IID_PPV_ARGS(&dxgi_factory)), "DXGI factory");
    DXGI_SWAP_CHAIN_DESC1 desc{};
    desc.Width = width_; desc.Height = height_; desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc.Count = 1; desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.BufferCount = 2; desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
    desc.AlphaMode = DXGI_ALPHA_MODE_PREMULTIPLIED;
    desc.Flags = DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT;
    ComPtr<IDXGISwapChain1> swap;
    check(dxgi_factory->CreateSwapChainForComposition(d3d_.Get(), &desc, nullptr, &swap), "Composition swap chain");
    check(swap.As(&swap_), "DXGI 1.3 swap chain");
    check(swap_->SetMaximumFrameLatency(1), "Frame latency");
    frame_ready_ = swap_->GetFrameLatencyWaitableObject();
    if (!frame_ready_) throw std::runtime_error("Missing DXGI frame latency handle");
    D2D1_FACTORY_OPTIONS options{};
    check(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, __uuidof(ID2D1Factory1), &options,
        reinterpret_cast<void**>(factory_.GetAddressOf())), "Direct2D factory");
    check(factory_->CreateDevice(dxgi.Get(), &device_), "Direct2D device");
    check(device_->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, &d2d_), "Direct2D context");
    check(d2d_->CreateSolidColorBrush(D2D1::ColorF(0.f, 0.f, 0.f), &brush_), "Direct2D brush");
    check(DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory),
        reinterpret_cast<IUnknown**>(write_.GetAddressOf())), "DirectWrite factory");
    // A private DirectWrite font collection avoids installing or modifying system fonts.
    ComPtr<IDWriteFactory3> write3;
    if (SUCCEEDED(write_.As(&write3))) {
        ComPtr<IDWriteFontSetBuilder> builder;
        if (SUCCEEDED(write3->CreateFontSetBuilder(&builder))) {
            for (const auto* name : {L"JetBrainsMonoNerdFontPropo-Light.ttf", L"JetBrainsMonoNerdFontPropo-Regular.ttf", L"JetBrainsMonoNerdFontPropo-SemiBold.ttf"}) {
                auto file = config / L"fonts" / name;
                if (!std::filesystem::exists(file)) continue;
                ComPtr<IDWriteFontFaceReference> reference;
                if (SUCCEEDED(write3->CreateFontFaceReference(file.c_str(), nullptr, 0, DWRITE_FONT_SIMULATIONS_NONE, &reference)))
                    builder->AddFontFaceReference(reference.Get());
            }
            ComPtr<IDWriteFontSet> set;
            ComPtr<IDWriteFontCollection1> collection;
            if (SUCCEEDED(builder->CreateFontSet(&set)) && set->GetFontCount() &&
                SUCCEEDED(write3->CreateFontCollectionFromFontSet(set.Get(), &collection))) collection.As(&fonts_);
        }
    }
    check(DCompositionCreateDevice(dxgi.Get(), __uuidof(IDCompositionDevice),
        reinterpret_cast<void**>(composition_.GetAddressOf())), "DirectComposition device");
    check(composition_->CreateTargetForHwnd(window, TRUE, &composition_target_), "Composition target");
    check(composition_->CreateVisual(&visual_), "Composition visual");
    check(composition_->CreateEffectGroup(&opacity_), "Composition opacity effect");
    check(opacity_->SetOpacity(0.f), "Initial opacity");
    check(visual_->SetEffect(opacity_.Get()), "Composition effect");
    check(visual_->SetContent(swap_.Get()), "Composition content");
    check(composition_target_->SetRoot(visual_.Get()), "Composition root");
    check(composition_->Commit(), "Composition initial commit");
    set_theme(theme); target();
}
void RenderDevice::set_theme(const Theme& theme) {
    theme_ = theme;
    BOOL exists = FALSE; UINT index = 0;
    if (fonts_) fonts_->FindFamilyName(theme_.font_family.c_str(), &index, &exists);
    if (!exists && fonts_) {
        fonts_->FindFamilyName(L"JetBrainsMono NFP", &index, &exists);
        if (exists) theme_.font_family = L"JetBrainsMono NFP";
    }
    custom_fonts_ = exists != FALSE;
    if (!exists) theme_.font_family = L"Segoe UI";
    layouts_.clear();
}
void RenderDevice::target() {
    ComPtr<IDXGISurface> surface;
    check(swap_->GetBuffer(0, IID_PPV_ARGS(&surface)), "Back buffer");
    auto properties = D2D1::BitmapProperties1(D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW,
        D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED), dpi_, dpi_);
    check(d2d_->CreateBitmapFromDxgiSurface(surface.Get(), &properties, &bitmap_), "Direct2D target");
    d2d_->SetTarget(bitmap_.Get()); d2d_->SetDpi(dpi_, dpi_);
    d2d_->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
}
void RenderDevice::resize(UINT width, UINT height, float dpi) {
    width = std::max(1u, width); height = std::max(1u, height);
    if (width == width_ && height == height_ && dpi == dpi_) return;
    d2d_->SetTarget(nullptr); bitmap_.Reset(); context_->ClearState();
    check(swap_->ResizeBuffers(2, width, height, DXGI_FORMAT_UNKNOWN,
        DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT), "Resize composition buffers");
    width_ = width; height_ = height; dpi_ = dpi;
    target();
}
void RenderDevice::compose(float opacity, float offset_y) {
    check(opacity_->SetOpacity(std::clamp(opacity, 0.f, 1.f)), "Visual opacity");
    check(visual_->SetOffsetY(offset_y), "Visual translation");
    check(composition_->Commit(), "Composition commit");
}
void RenderDevice::text(const std::wstring& value, float left, float top, float width,
                        float size, Color color, bool right) {
    if (width <= 0 || value.empty()) return;
    auto key = value + L"|" + std::to_wstring(width) + L"|" + std::to_wstring(size) + (right ? L"R" : L"L");
    auto it = layouts_.find(key);
    if (it == layouts_.end()) {
        if (layouts_.size() >= 128) layouts_.clear();
        ComPtr<IDWriteTextFormat> format;
        check(write_->CreateTextFormat(theme_.font_family.c_str(), custom_fonts_ ? fonts_.Get() : nullptr,
            static_cast<DWRITE_FONT_WEIGHT>(theme_.font_weight), DWRITE_FONT_STYLE_NORMAL,
            DWRITE_FONT_STRETCH_NORMAL, size, L"vi-VN", &format), "Text format");
        format->SetTextAlignment(right ? DWRITE_TEXT_ALIGNMENT_TRAILING : DWRITE_TEXT_ALIGNMENT_LEADING);
        format->SetParagraphAlignment(DWRITE_PARAGRAPH_ALIGNMENT_CENTER);
        format->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
        DWRITE_TRIMMING trim{DWRITE_TRIMMING_GRANULARITY_CHARACTER, 0, 0};
        ComPtr<IDWriteInlineObject> ellipsis;
        if (SUCCEEDED(write_->CreateEllipsisTrimmingSign(format.Get(), &ellipsis))) format->SetTrimming(&trim, ellipsis.Get());
        ComPtr<IDWriteTextLayout> layout;
        check(write_->CreateTextLayout(value.c_str(), static_cast<UINT32>(value.size()), format.Get(),
            width, theme_.bar_height, &layout), "Text layout");
        it = layouts_.emplace(std::move(key), std::move(layout)).first;
    }
    brush_->SetColor(D2D1::ColorF(color.r, color.g, color.b, color.a));
    d2d_->DrawTextLayout(D2D1::Point2F(left, top), it->second.Get(), brush_.Get(), D2D1_DRAW_TEXT_OPTIONS_CLIP);
}
bool RenderDevice::draw(const BarScene& scene) {
    const float w = static_cast<float>(width_) * 96.f / dpi_;
    const float h = theme_.bar_height;
    d2d_->BeginDraw();
    d2d_->Clear(D2D1::ColorF(0.f, 0.f, 0.f, 0.f));
    if (!scene.glass_ready && theme_.background_opacity > 0) {
        const auto c = theme_.mantle;
        brush_->SetColor(D2D1::ColorF(c.r, c.g, c.b, theme_.background_opacity));
        d2d_->FillRectangle(D2D1::RectF(0, 0, w, h), brush_.Get());
    }
    float x = 12;
    text(L"Ponie", x, 0, 48, theme_.font_size, theme_.text); x += 56;
    text(L"│", x, 0, 12, theme_.font_size, theme_.overlay); x += 18;
    if (scene.workspaces.connected && !scene.workspaces.populated.empty()) {
        text(scene.workspaces.layout.empty() ? L"BSP" : scene.workspaces.layout, x, 0, 58, theme_.font_size, theme_.muted); x += 66;
        const auto count = std::min<std::size_t>(scene.workspaces.populated.size(), 12);
        const float sx = x;
        const float highlight = sx + static_cast<float>(scene.indicator) * 24;
        auto c = theme_.accent;
        brush_->SetColor(D2D1::ColorF(c.r, c.g, c.b, .12f));
        d2d_->FillRoundedRectangle(D2D1::RoundedRect(D2D1::RectF(highlight-3, 5, highlight+20, h-5), 7, 7), brush_.Get());
        for (std::size_t i = 0; i < count; ++i) {
            const bool focused = static_cast<int>(i) == scene.workspaces.focused_workspace;
            text(focused || scene.workspaces.populated[i] ? L"✦" : L"✧", x, 0, 24, 15, focused ? theme_.accent : theme_.muted); x += 24;
        }
        x += 8; text(L"│", x, 0, 12, theme_.font_size, theme_.overlay); x += 18;
    }
    if (w > 700) text(scene.title, x, 0, std::max(0.f, w - x - 300), theme_.font_size, theme_.text);
    // Search and settings icons are drawn as vectors, avoiding a dependency on a system icon font.
    auto c = theme_.text;
    brush_->SetColor(D2D1::ColorF(c.r, c.g, c.b, .10f * scene.hover));
    d2d_->FillRoundedRectangle(D2D1::RoundedRect(D2D1::RectF(w-36, 4, w-5, h-4), 8, 8), brush_.Get());
    brush_->SetColor(D2D1::ColorF(c.r, c.g, c.b));
    if (w > 320) {
        d2d_->DrawEllipse(D2D1::Ellipse(D2D1::Point2F(w-262, h/2-1), 4.5f, 4.5f), brush_.Get(), 1.4f);
        d2d_->DrawLine(D2D1::Point2F(w-258, h/2+3), D2D1::Point2F(w-254, h/2+7), brush_.Get(), 1.4f);
    }
    text(scene.clock, std::max(8.f,w-244), 0, std::min(204.f,w-48), theme_.font_size, theme_.text, true);
    for (int i=0; i<3; ++i) {
        const float y = h/2-5+5*static_cast<float>(i);
        d2d_->DrawLine(D2D1::Point2F(w-28,y), D2D1::Point2F(w-13,y), brush_.Get(), 1.3f);
        d2d_->FillEllipse(D2D1::Ellipse(D2D1::Point2F(w-23+static_cast<float>(i%2)*5,y), 2, 2), brush_.Get());
    }
    check(d2d_->EndDraw(), "Direct2D frame");
    const HRESULT hr = swap_->Present(1, DXGI_PRESENT_DO_NOT_WAIT);
    if (hr == DXGI_ERROR_WAS_STILL_DRAWING) return false;
    check(hr, "Present"); return true;
}
}
