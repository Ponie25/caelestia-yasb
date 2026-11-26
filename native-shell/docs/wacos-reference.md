# WacOS architecture and license reference

Inspected on 2026-11-27.

Revision examined: abdb1dbad02fbfe3821687b9dd5d92c3ce072cd8 (main at inspection).
Upstream: [renzyxx/WacOS](https://github.com/renzyxx/WacOS)
This is a source review only. No binaries were built, installed, run, benchmarked, or copied.

## License and reuse decision

LICENSE is the custom WacOS Source-Available License, copyright 2026 renzyxx,
all rights reserved. It permits reading/studying and personal non-commercial
builds. It expressly prohibits copying, reusing, or adapting code, written
algorithms, shaders, assets, and configuration into another project without
prior written permission, and prohibits redistribution. It applies from
build-17 (2026-11-20) onward. Earlier snapshots are a separate licensing
question and were not investigated as a route to reuse.

Decision: do not incorporate WacOS source or assets into Caelestia. Use the
repository only as an architectural comparison. Implement from documented
Microsoft APIs, independently written logic, and the existing Caelestia
renderer and tokens. No WacOS code was copied in this audit.

LICENSE also identifies Apple/third-party assets and a separately GPL-3.0
Windhawk-derived lockscreen file. These exceptions do not give permission to
reuse the rest of WacOS, and importing its assets would conflict with the
requested Caelestia visual identity.

## Verified implementation

### Native rendering and composition

src/shell/ui.cpp:149-235 lazily creates a shared process-wide D3D11
device, D2D device/context, and DirectComposition device. Each GpuSurface
has a BGRA premultiplied-alpha, two-buffer, flip-sequential composition
swap chain and a per-HWND composition target/visual. The main GPU path
presents without its own vsync wait; a separate frame clock supplies pace.
Resize reuses the swap chain via ResizeBuffers, rather than recreating the
D3D device. There is a WARP fallback if hardware initialization fails.

The repository is not exclusively GPU-rendered: ui.cpp:101-138 retains a
DIB/DC target and UpdateLayeredWindow/BitBlt path, and common/app2d.h:257
uses CreateHwndRenderTarget for shared app drawing.

### Animation and scheduling

src/shell/anim.cpp uses QueryPerformanceCounter, cubic-bezier easing and
analytic spring evaluation. The public helpers are substantially tailored
to macOS theme timing and should not replace Caelestia motion profiles.

src/shell/ui.cpp:658-707 implements a per-HWND/message clock using a
detached worker that waits for DwmFlush when active and on an event when
inactive. Pending/ack bookkeeping coalesces posted render messages so
expensive painting does not indefinitely queue frames ahead of typing.
It also optionally skips refreshes in a light mode. That is evidence for
refresh-aware scheduling, not proof of frame-time or input-latency targets.
The workers have no explicit teardown/join path, which is unsuitable for
a new modular lifetime model.

src/shell/genio.cpp:149-200 shares the D3D device but creates an additional
DirectComposition device, uploads/captures window surfaces and assigns
compositor animations to multiple visual slices. This demonstrates
retained/compositor animation capability, but the macOS genie effect is
outside the requested Caelestia Phase 1 and should not be imported.

### Glass implementation

src/shell/backdrop.cpp:1684-1715 creates a Windows.UI.Composition
DispatcherQueue/Compositor and DesktopWindowTarget separately from the
DirectComposition UI path. HostBackdropBrush plus tint and rounded
geometry clipping form the normal glass. Content can be drawn on a
CompositionDrawingSurface on the UI D2D device (1724 onward).

Important correction to the file's introductory comments: backdrop.cpp:
220-258 says transforming HostBackdropBrush had failed and falls back
through blur/saturation effect recipes. Do not treat the introductory
lens description as proof that live refraction works on that path.

Optional real glass reconstructs underlying scene from captured windows,
uses Windows.Graphics.Capture and a separate D3D11/D2D device, composes a
monitor-sized texture (1209-1251), and enables 250 ms and 16 ms timers
(1260-1268). It has capture-failure fallback. This is more complex than
simply turning on a compositor blur and is not an idle-free architecture.

src/shell/fotogpu.cpp creates free-threaded WGC frame pools and does
GPU-to-GPU copies into composition surfaces. It also starts up to 60
per-window workers and joins them, then waits for first frames in Grab.
A new shell should bound workers and perform any such waits off the
UI/render thread; shared capture resources must have explicit ownership.

### Windows integration and gaming

src/shell/main.cpp uses RegisterShellHookWindow, foreground WinEvent
hooks, hotkeys, low-level keyboard hooks, and a conventional message
loop. It still has 1000 ms and 200 ms timers (1523-1524). The README claim
that nothing polls at idle is therefore too broad for this revision.

The full WacOS product changes/hides taskbars, can terminate Explorer
(main.cpp:1496), and includes injected title-bar DLLs; main.cpp:1547
onward also offers operation inside Explorer. Those features exceed and
conflict with Caelestia's current requirement to preserve Explorer/DWM
and avoid injection/invasive modification. Do not adopt them.

src/shell/jogo.cpp reduces capture/real glass, raw input/global mouse
work, hot corners, indexing pressure, and location-change event traffic
during games. It consolidates location-change hooks and discards non-
window events immediately. This is evidence that capture and event
traffic can dominate cost even in native C++, so language alone is not a
performance argument.

### Diagnostics and robustness

src/shell/sentinela.cpp checks UI responsiveness, samples a stalled UI
thread and logs stacks; this is useful diagnostic intent, but its
suspension/sentinel mechanism is not necessary for the first prototype.
src/comum/gpu.h selects the adapter driving the primary monitor to avoid
cross-adapter copies. The current implementation dynamically calls GDI
D3DKMT functions; prefer ordinary DXGI output enumeration in Caelestia
where it suffices and report the actual adapter used.

main.cpp:1536-1543 resorts to TerminateProcess after restoring state
because detached background threads could outlive logging/COM. A new
shell should instead cancel callbacks, stop/join workers, release GPU
resources in dependency order, then uninitialize COM normally.

### Build and claimed performance

build.cmd:40 uses C++20/MSVC; build is a batch script over source globs,
not CMake. README lists hardware-specific observations for one author's
desktop. Those are upstream claims, not independently reproduced
baselines and not transferable to Caelestia.

## Recommendations for Caelestia

- Reuse Caelestia theme/motion tokens and owned native glass shaders after
  checking their own attribution. Copy nothing from WacOS.
- Keep Explorer/DWM/Komorebi running. Create ordinary non-activating shell
  windows and give interactive windows explicit focus rules later.
- Use one well-owned D3D11 device per relevant adapter, DXGI composition
  swap chains and Direct2D/DirectWrite, with retained DirectComposition
  visuals. Recreate targets on resize/device loss, not each frame.
- Establish one bounded event-driven scheduler, coalesce invalidations and
  sleep while unchanged. Make input handling independent of animation work.
- Preserve position and velocity when retargeting animations. Treat source
  time curves as mathematics, and test at several sampling rates.
- Separate capture service ownership from material rendering. No duplicate
  capture sessions per widget, no CPU readback to re-upload each frame, and
  no scene reconstruction on the UI thread.
- Start with documented APIs and explicit fallback; neither WacOS's use of
  native C++ nor its README demonstrates Caelestia's performance targets.
- Require Windows visual, IME/focus, device-loss and gaming tests before
  calling integration verified.

## Pinned source links
- <https://github.com/renzyxx/WacOS/blob/abdb1dbad02fbfe3821687b9dd5d92c3ce072cd8/LICENSE>
- <https://github.com/renzyxx/WacOS/blob/abdb1dbad02fbfe3821687b9dd5d92c3ce072cd8/src/shell/ui.cpp>
- <https://github.com/renzyxx/WacOS/blob/abdb1dbad02fbfe3821687b9dd5d92c3ce072cd8/src/shell/anim.cpp>
- <https://github.com/renzyxx/WacOS/blob/abdb1dbad02fbfe3821687b9dd5d92c3ce072cd8/src/shell/backdrop.cpp>
- <https://github.com/renzyxx/WacOS/blob/abdb1dbad02fbfe3821687b9dd5d92c3ce072cd8/src/shell/genio.cpp>
- <https://github.com/renzyxx/WacOS/blob/abdb1dbad02fbfe3821687b9dd5d92c3ce072cd8/src/shell/fotogpu.cpp>
- <https://github.com/renzyxx/WacOS/blob/abdb1dbad02fbfe3821687b9dd5d92c3ce072cd8/src/shell/main.cpp>
- <https://github.com/renzyxx/WacOS/blob/abdb1dbad02fbfe3821687b9dd5d92c3ce072cd8/src/shell/jogo.cpp>
- <https://github.com/renzyxx/WacOS/blob/abdb1dbad02fbfe3821687b9dd5d92c3ce072cd8/src/shell/sentinela.cpp>
- <https://github.com/renzyxx/WacOS/blob/abdb1dbad02fbfe3821687b9dd5d92c3ce072cd8/src/comum/gpu.h>
