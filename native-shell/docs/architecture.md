# Native shell architecture assessment

Baseline: `Ponie25/caelestia-yasb@8c4da7627bf56fa7723306876c25917c72f85d26`.
The detailed [legacy audit](legacy-audit.md) identifies the existing implementation
and measurements. [WacOS](wacos-reference.md) was studied at a pinned revision;
its restrictive source-available license rules out importing its code or assets.
This implementation is independently authored against documented Windows APIs
and reuses Caelestia's own configuration and MIT renderer ABI.

## Decisions and tradeoffs

Use C++20 rather than C++23: the existing renderer already builds as C++20 and the
prototype needs no C++23 facility. CMake builds portable logic separately from
the Windows host. There is no Python/Qt, browser, WebView, Electron, XAML or WinUI
runtime in the native distribution. The existing application is left intact.

Use D3D11 + Direct2D/DirectWrite + DirectComposition for this first experiment.
It matches the existing optical renderer's GPU family, supports premultiplied
transparent HWND composition, retains text shaping, and has a small Win32/COM
integration surface. Direct2D and DirectWrite are complementary, not competing
renderers: one draws primitives, the other shapes/layouts text. Direct3D owns GPU
resources; DirectComposition composes those resources and applies opacity and
translation. This is not a commitment that D3D11 is faster than alternatives.

Windows.UI.Composition remains a candidate for richer compositor-native effects
and backdrop primitives. It needs a dispatcher/compositor ownership model and a
separate evaluation of true optical refraction; a normal backdrop brush is not
equivalent to the existing custom shader. D3D12 offers no demonstrated benefit
for this prototype's retained bar/text workload and would add resource/sync
complexity. Neither alternative is rejected on an invented benchmark.

Keep normal non-activating Win32 tool windows with a documented AppBar work-area
reservation. Do not register as the system shell, terminate Explorer, hook DWM,
inject DLLs into third-party processes, or modify Komorebi configuration. Right
click temporarily permits a normal menu to dismiss correctly. Phase 2 must add
explicit focus/IME/UI Automation contracts for interactive Island/launcher UI.

## Implemented module boundaries

```text
existing config/*.json + palette/fonts
                │ startup / explicit async reload
                ▼
portable core: validated tokens + state model + analytic motion
                │ immutable configuration / UI-owned scene
                ▼
Win32 host ─── Direct2D / DirectWrite ─── D3D11 BGRA swap chain
    │                                      │
    │                              DirectComposition visual/effect
    │                                      │
    ├── DXGI-ready worker ◀── one-frame queue ─── DWM
    │   request → frame message → UI acknowledgement
    ├── WinEvent foreground/location notifications (coalesced)
    ├── clock: next minute boundary; no per-frame clock polling
    └── Komorebi service: command worker + cancellable pipe reader
           subprocess/state/subscribe IO off the UI thread

optional existing glass DLL: independent WGC + D3D11 + DComp worker
    └── HWND underlay via retained ABI; no Qt raster content upload
```

`core.cpp` performs bounded JSON parsing and validates profile paths, colors,
font options and motion values. It imports the selected existing palette,
appearance overrides, glass parameters and all three cubic-bezier families.
Invalid optional values fall back; unreadable/malformed files and invalid profile paths emit warnings. No config polling or Python
process is used. Startup reads happen before interaction; explicit reload runs
on an owned worker and publishes a complete result to the host.

`windows_services.cpp` creates a current-user-only local named pipe and starts
`komorebic subscribe-pipe` (legacy alias fallback). Initial state is queried once;
later notifications are newline-delimited state updates. Commands and reads are
bounded/cancellable. UI posts are coalesced and replace one latest snapshot;
workspace clicks enqueue commands and wait for actual state notification to
change selection. Missing/disconnected Komorebi yields no fabricated indicators.
Reconnect is explicit, avoiding periodic daemon detection. Child process jobs
own only the commands launched by this prototype, not the Komorebi daemon.

## GPU and frame scheduling

The bar owns one BGRA-capable D3D11 device, a Direct2D device/context and a
DirectWrite font/layout cache. A two-buffer premultiplied flip-sequential
composition swap chain is attached to its HWND through a DirectComposition
visual. A private DirectWrite font collection uses the already licensed bundled
fonts without installing fonts globally; Segoe UI is the fallback. Text layouts
are bounded to 128 cache entries. There is no CPU screenshot/readback followed
by per-frame UI texture upload.

The DXGI maximum frame latency is one. An owned worker waits for requests and
the frame-latency waitable object, then posts one frame message and waits for
acknowledgement. Rendering is on the UI owner thread in this small prototype;
it never waits for VBlank, pipe IO, subprocesses or file reads there. Each
scheduled animation tick submits a buffer with Present(1, DO_NOT_WAIT); if the
queue is busy, the dirty scene is retried. Crucially, a frame-ready handle is not
treated as a free-running clock without new Presents. No VBlank waits or animation frame
requests are made while idle/hidden; the worker sleeps on its request/stop events. The minute clock and actual system events
can still cause legitimate redraws.

This ties pacing to the actual display/compositor path rather than a fixed
16 ms timer or arbitrary FPS cap. EnumDisplaySettings reports current display
refresh for diagnostics/material cap; it does not prove physical refresh pacing.
The scheduler supports 60/120/144/165/240 Hz in design; target-display validation
is still required. All current frames redraw the small bar, including an
entrance-only animation, to keep DXGI readiness paired with Presents. Splitting
retained text and animated visuals is a future optimization to measure.

DirectComposition applies root opacity/translation. Direct2D draws vector icons,
workspace stars and a spring-driven selected indicator. Clip-safe text and
premultiplied buffers preserve transparency. GPU resources survive ordinary
frames and are resized rather than recreated on each tick.

## Motion contract

The core samples absolute monotonic time in seconds, never integrates by frame
count. Analytic springs support under/critical/over damping and retain both
position and velocity on retarget. Existing cubic-bezier curves keep their
overshoot. A decaying Hermite velocity correction gives an interrupted bezier
transition the previous derivative and a settled endpoint. Reversals and long
pauses are tested independently of render cadence. Config and Windows reduced
motion are both respected.

The same motion APIs will own Island bounds/radius and launcher transitions in
Phase 2. Do not combine them with geometry updates on a second timer. Native
text input must be ready at opening start; that is a Phase 2 acceptance test,
not a claim about the current bar-only prototype.

## Liquid Glass reuse and remaining duplication

Preserve `native/liquid-glass/lgwin.cpp`, its HLSL and MIT attribution. The
adapter calls the existing exported ABI for optical parameters and a full-bar
preview; this exercises reuse without porting Island features prematurely.
The ordinary transparent bar remains the default. The DLL's WGC path supplies
refraction, frost, tint and reflections; the native bar renders foreground text
directly to GPU instead of supplying Qt BGRA buffers. Readiness checks are
bounded to startup (five seconds), then stop. Capture failure suspends glass.

This is deliberately an interim integration: the DLL still owns a second D3D
device, independent frame cap/Present path, capture resources, locks and legacy
teardown behavior. Therefore the prototype does **not** yet have unified glass
and foreground pacing, and inherited renderer wakeups remain. A shared adapter/
capture/device service and shared-texture material pass are the next rendering
experiment. Establish a measured baseline first; preserve the visual shader
output before replacing the ABI. Late glass device-loss detection/recovery and
its live capture behavior require additional Windows testing.

## Recovery, compatibility and next priorities

Display changes recompute geometry and current HWND DPI; only one chosen monitor
gets a bar for Phase 1. Foreground WinEvents and AppBar fullscreen notifications
hide the bar and suspend glass. No global launcher key is registered. Resume
recreates the bar GPU path. Graphics failures trigger up to three delayed
recovery attempts, followed by ordinary shutdown. The AppBar is removed on exit;
workers are signaled/joined and the inherited glass shutdown runs after the
message loop. No forced termination of the shell itself is used.

Windows acceptance remains necessary for focus/menu behavior, actual high-Hz
frame pacing, display hotplug/rotation, mixed DPI, sleep/resume, hybrid/multi-GPU,
WGC/device loss, accessibility/high contrast, and gaming/fullscreen interaction.
The Win32 bar has no custom UI Automation provider yet; full accessibility parity
must precede native feature parity. The prototype does not read YAML layout or
implement every appearance setting (e.g. gradients/custom CSS); it preserves the
current 34-DIP arrangement and shared JSON palette/typography/motion contracts.

Next: validate the packaged bar on Windows with the supplied measurement
methodology, then unify the material/device/scheduler path; port Island and
launcher with focus/IME/accessibility regression tests; consolidate Phase 3
services; add multi-monitor bars; finally port Settings/wallpaper control. Keep
the legacy distribution until measured stability and feature parity are shown.

## Primary API references

- [Direct2D/D3D device interoperation](https://learn.microsoft.com/en-us/windows/win32/direct2d/devices-and-device-contexts)
- [Initialize DirectComposition](https://learn.microsoft.com/en-us/windows/win32/directcomp/initialize-directcomposition)
- [DXGI frame latency waitable object](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_3/nf-dxgi1_3-idxgiswapchain2-getframelatencywaitableobject)
- [GetDpiForWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getdpiforwindow)
- [Application desktop toolbars](https://learn.microsoft.com/en-us/windows/win32/shell/application-desktop-toolbars)
- [Komorebi subscribe-pipe](https://komorebi.lgug2z.com/cli/subscribe-pipe.html)
