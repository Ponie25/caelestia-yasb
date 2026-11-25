# Performance and implementation decision

Measured 25 November 2026. Decision: optimize the current Python/Qt UI and native
C++ renderer; do not replace the application with Rust in this update.

## Why keep the current stack?

YASB 2.0.8 loads Python widgets into PyQt. The Island runs in a separate PySide
process to keep the existing UI and Qt plugin environments isolated. The optical
renderer already uses compiled C++/D3D11 through a C ABI. Rust could implement a
replacement DLL or a standalone Island, but it would still need the same capture
buffers and GPU resources. A Rust DLL behind the same Qt UI would keep both Qt
runtimes. It has not been benchmarked and no language-level speedup is claimed.

| Approach | Expected benefit and cost | Decision |
| --- | --- | --- |
| Remove unused native allocations and bound caches | Targets measured waste; retains existing animation, IME and customization | Implemented |
| Replace the C++ renderer with a Rust DLL | Similar D3D/WGC resource requirements; substantial interop work, no demonstrated saving | Defer |
| Rewrite the Island UI in Rust and replace Qt | Could remove the Island's Python/Qt overhead, but requires rebuilding text input, accessibility, media/audio, global shortcuts, themes and glass composition | Separate future project |

These are architecture assessments, not comparative Rust benchmarks. Upstream
[YASB](https://github.com/amnweb/yasb) is a Python application; this bundle stays
pinned to the supported source/bytecode version in its dependency manifest.

## What changed

- WGC no longer initializes Desktop Duplication, which previously allocated
  unused monitor-sized textures alongside the actual window-capture backend.
- One frame-pool buffer is copied and released inside the callback, replacing
  two queued full-window buffers. The shader and the 120 FPS user defaults remain.
- Closed pills discover only layers intersecting their optical shape plus a
  64-pixel margin. Open/morphing surfaces retain the full Qt host region so their
  background is ready as they expand.
- Hidden material startup no longer polls its health timer at 60 Hz. Visibility
  synchronization resumes polling/rendering when needed. Existing hide/suspend
  paths stop the timer too.
- Launcher icons use a 64-entry LRU cache, so browsing many apps does not retain
  every icon indefinitely.
- Missing Windows media timeline/control data no longer tears down and reconnects
  the entire media listener. Transport remains available; seek waits for a valid
  timeline.

## Controlled native fixture

Each DLL was run in a fresh process against the same opaque owned background and
an off-pill layer, at 150% scaling on a 28-logical-CPU Windows machine. Both native
fixtures used the same Python 3.10/PySide 6.12 host. The baseline DLL came from
commit `50eaa06`. The portable installer was separately smoke-tested with its
pinned Python 3.14 runtime. The source
fixture is `tools/benchmark_glass.py`. It shows non-activating test windows and
reads only its renderer's output textures; it does not take desktop screenshots.
The host was 728×32 logical pixels closed and 728×456 open.

The figures below cover the **test process**, not the entire YASB installation.

| Stage | Before: private commit | After: private commit | Before: resident working set | After: resident working set |
| --- | ---: | ---: | ---: | ---: |
| Closed | 153.0 MiB | 90.3 MiB | 90.7 MiB | 89.8 MiB |
| Open | 167.9 MiB | 106.5 MiB | 94.4 MiB | 102.2 MiB |
| After three resize cycles | 169.0 MiB | 108.1 MiB | 103.9 MiB | 105.6 MiB |

Private commit fell by about 61–63 MiB in this fixture. **Resident RAM did not
meaningfully decrease**, and the open-state sample was higher. Private commit is
not the same as physical RAM or dedicated GPU memory. The optimization removes
unnecessary allocations; it does not turn a two-Qt-runtime desktop app into a
sub-100-MiB app.

Both DLLs produced zero additional native frames during the static 1.4-second
interval. Dynamic updates, three resize cycles, suspend/resume and shutdown passed.
CPU samples were short and affected by compositor scheduling; no fixed CPU,
animation-FPS or gaming improvement is claimed. This is not a long-duration leak
or battery-life study.

The full open shader output and the closed pill plus refraction margin matched
byte-for-byte in the controlled scene. The native debug dump includes backdrop
pixels in otherwise transparent host space; differences outside the closed
optical region are expected after excluding irrelevant layers.

Raw sanitized results and pixel-comparison figures are in
[`performance/`](performance/). Per-process Windows GPU memory counters can count
cross-process shared allocations more than once; do not interpret them as private
VRAM or sum them across apps. See [Microsoft's GPU accounting explanation](https://devblogs.microsoft.com/directx/gpus-in-the-task-manager/).

## Reproduce

Run these from the repository using a prepared install's Python runtime:

```powershell
& '<install>\python\python.exe' tools\check_install.py '<install>'
& '<install>\python\python.exe' tools\check_launcher_input.py '<install>'
& '<install>\python\python.exe' tools\check_resources.py '<install>'
& '<install>\python\python.exe' tools\benchmark_glass.py '<install>' '<dll>' '<output-directory>'
```

The benchmark requires Windows graphics capture support. Rebuild the DLL from an
x64 Visual Studio developer prompt using `native/liquid-glass/build.cmd`. Use
fresh processes, the same desktop geometry and the same scene when comparing
versions. Keep a copy of the old DLL outside the installed runtime. Compare
working set, private commit and capture estimates separately; include UI state,
scaling, wallpaper activity and Settings usage with any full-app measurement.

Remaining costs include two Qt runtimes, Windows graphics/audio components and
the full-window capture surfaces required by WGC. The optimization does not crop
the WGC source frame pool to the small pill. Further large RAM reductions would
require a separate UI/runtime consolidation project with regression testing.
