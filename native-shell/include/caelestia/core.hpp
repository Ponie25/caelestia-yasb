#pragma once

#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

namespace caelestia {

struct Color { float r{}, g{}, b{}, a{1.f}; };

struct Theme {
    Color base{.118f,.118f,.18f}, mantle{.094f,.094f,.145f};
    Color surface{.192f,.196f,.267f}, surface2{.271f,.278f,.353f};
    Color text{.804f,.839f,.957f}, muted{.651f,.678f,.784f};
    Color accent{.796f,.651f,.969f}, pink{.961f,.761f,.906f};
    Color lavender{.706f,.745f,.996f}, overlay{.424f,.439f,.525f};
    std::wstring font_family{L"JetBrainsMono NFP Light"};
    float font_size{12.f}, bar_height{34.f}, background_opacity{0.f};
    int font_weight{600};
};

struct CubicBezier {
    double x1{.38}, y1{1.21}, x2{.22}, y2{1.};
    [[nodiscard]] double value(double progress) const;
    [[nodiscard]] double slope(double progress) const;
};

struct MotionProfile {
    CubicBezier spatial{}, fast{.42,1.67,.21,.9}, effects{.34,.8,.34,1.};
    bool enabled{true};
    double scale{1.};
    int fps{120};
    double launcher_ms{560}, popup_ms{440}, menu_ms{320}, dialog_ms{360};
    double page_ms{280}, section_ms{320}, control_ms{160}, close_ms{220};
    // Seconds, already scaled; returns zero when animation is disabled.
    [[nodiscard]] double duration(std::string_view kind) const;
};

struct GlassOptions {
    bool enabled{true}, contrast{true};
    float refraction{1.f}, frost{.4f}, tint{.32f}, reflection{1.f};
    int max_fps{120};
};

struct Config {
    Theme theme{};
    MotionProfile motion{};
    GlassOptions glass{};
    double island_idle_width{116.};
    std::string profile{"catppuccin"};
    std::vector<std::string> warnings;
};

// Reads existing Caelestia JSON once during startup. Invalid optional values use
// defaults. No Python, Qt, filesystem polling or platform runtime is required.
[[nodiscard]] Config load_config(const std::filesystem::path& config_root);

struct WorkspaceState {
    bool connected{false};
    int monitor_index{0}, focused_workspace{0};
    std::vector<bool> populated;
    std::wstring layout;
};
// Accepts `komorebic state` JSON or a named-pipe notification {"state":...}.
// Invalid, incomplete or oversized input returns disconnected, never demo data.
[[nodiscard]] WorkspaceState parse_komorebi_state(std::string_view json, int monitor_index=0);

struct MotionState { double position{}, velocity{}; };

// Analytic damped spring, sampled at absolute monotonic seconds. Retargeting
// preserves position and velocity even during a reversal or a missed frame.
class Spring {
public:
    explicit Spring(double value=0., double angular_frequency=20., double damping_ratio=.85);
    [[nodiscard]] MotionState sample(double now) const;
    void retarget(double target, double now, bool animate=true);
    void snap(double value, double now);
    [[nodiscard]] bool active(double now) const;
private:
    double initial_{}, velocity_{}, target_{}, started_{};
    double omega_{20.}, damping_{.85};
};

// Preserves the existing cubic-bezier path, adding a decaying Hermite residual
// on interruption so the new path starts at the previous position AND velocity.
class BezierTransition {
public:
    explicit BezierTransition(double value=0.);
    [[nodiscard]] MotionState sample(double now) const;
    void retarget(double target, double now, double duration_seconds,
                  CubicBezier curve={}, bool animate=true);
    void snap(double value, double now);
    [[nodiscard]] bool active(double now) const;
private:
    double initial_{}, target_{}, started_{}, duration_{}, correction_{}, end_correction_{};
    CubicBezier curve_{};
};

} // namespace caelestia
