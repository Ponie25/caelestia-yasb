# Windows performance baseline and comparison protocol

Status: methodology prepared on macOS, 2026-11-27. No new Windows baseline,
native graphical run, frame-pacing, latency or gaming result is asserted here.
The existing fixture results in `../../docs/performance.md` are prior evidence
with a different scope. Portable core tests and successful compilation are not
measurements of display smoothness or full-shell resource usage.

## Freeze the experiment

1. Keep an untouched legacy checkout at
   `8c4da7627bf56fa7723306876c25917c72f85d26`; prepare its isolated Windows install
   with `install.cmd -InstallDir <legacy-test-directory> -NoStart`.
2. Record the native commit, toolchain, SDK, build flags and dependency hashes.
   Compare optimized release builds without a debugger. Keep symbols separately.
3. Record Windows build, physical CPU/logical CPU count, RAM, GPU/driver/adapter,
   monitor geometry, DPI and **actual** active refresh rate, HDR, VRR, power mode,
   AC/battery state, background apps and relevant accessibility preferences.
   Document VM/RDP use; those results are functional checks, not representative
   local-display/gaming measurements.
4. Use the same theme, typography, layout, glass settings, wallpaper and media
   source. Run static and animated Wallpaper Engine scenes separately. Keep
   Explorer, DWM and Komorebi configurations fixed. Do not benchmark two shell
   variants at the same time.
5. Separate three comparisons: shell disabled, complete legacy installation,
   complete native implementation. A minimal bar must not be presented as a
   like-for-like replacement for the entire legacy Island/launcher/services.
   Additionally compare matching Phase 1 functionality with optional services
   disabled in both, clearly labeling the reduced scope.
6. Restart the tested processes between runs; warm up for 60 seconds before
   steady-state sampling. Use at least five runs per condition, alternating
   variant order. Save individual runs, medians, range and any outliers with
   explanations. Do not silently discard shader initialization or crashes.

Ordinary shell operation must run unelevated. ETW/GPU profiling tools may require
an elevated collector; that is separate from an application privilege requirement.
Record collector versions and trace overhead. Keep raw machine-local traces
outside the source repository; publish only sanitized results.

## Workload matrix

| Scenario | Duration / repeat | Purpose |
| --- | --- | --- |
| Static desktop, collapsed shell, no active media | 120 seconds after warmup | Idle CPU, wakeups, redraw count, resident memory and commit |
| Same desktop with animated wallpaper/video | 120 seconds | Required capture work and region invalidation |
| Open/close and reverse the same surface mid-transition | 100 deterministic cycles | Frame pacing, velocity/position continuity and allocations |
| Type immediately after launcher activation, include Vietnamese composition | At least 100 activations with logged timing | Input-to-first-visible-response and dropped input |
| Scroll/catalog/icon churn and repeated theme changes | 5 minutes | Cache bounds and allocation retention |
| Fullscreen/borderless game, shell disabled/legacy/native | 3-5 repeatable game benchmark passes each | Game frame-time impact and focus/overlay behavior |
| Display hotplug, mixed DPI/refresh, sleep/resume and device recovery | 10 cycles per supported case | Recovery correctness and retained resources |
| Long-duration idle/activity rotation | At least 1 hour | Memory, handles, threads and capture resource growth |

Only execute implemented workloads for the prototype; mark unavailable features
as **not implemented**, rather than recording artificial zeros. At each fixed
refresh mode (60, 120, 144, 165, 240 Hz when physically supported), repeat animation
and input workloads. Do not imply a tested rate that the monitor cannot expose.

## CPU and complete process-tree memory

Resolve each application root PID from the process actually launched, plus any
detached helpers belonging to that install path. Capture creation time and parent
relationships from ETW or `Win32_Process`; keep following descendants after
launchers exit. Pair PID with process start time to avoid PID-reuse errors. Record
individual PIDs and totals so optional subprocess changes remain explainable.
Do not include Explorer, DWM, Komorebi, the profiler or unrelated Python programs
in the shell tree. Measure those external processes separately as system impact.

At one-second intervals collect, per member:

- Private commit/private bytes (for example `GetProcessMemoryInfo` /
  `PROCESS_MEMORY_COUNTERS_EX.PrivateUsage` or the .NET process private-memory
  property).
- Resident working set (for example `WorkingSetSize`). If private resident
  working set is separately collected, name it separately; it is not commit.
- Cumulative user+kernel CPU time, handle count and thread count.
- Creation/exit events and process identity so exited helper CPU is retained.

Sum private commit across tree members. Report summed per-process resident
working set as **sum of process working sets**; shared resident pages can occur
in more than one process, so it is not unique physical RAM consumed by the tree.
For each sample calculate:

```text
core_equivalent_cpu_percent = 100 * sum(delta_user_seconds + delta_kernel_seconds) / elapsed_seconds
machine_normalized_cpu_percent = core_equivalent_cpu_percent / logical_cpu_count
```

State which CPU convention is shown. Report idle and animation CPU separately;
include sampling interval, logical CPU count and profiler overhead. Use ETW CPU
sampling/waits to locate hot paths only after reproducing a meaningful cost.
Do not infer Python's share from the process executable name: those processes
also contain Qt, native graphics, WinRT and audio code.

## ETW, present timing and GPU work

Install Windows Performance Toolkit and use WPR/WPA. Check available profiles
on the actual machine before recording:

```powershell
wpr -profiles
wpr -start GeneralProfile -filemode
# Reproduce one bounded, named scenario.
wpr -stop .\results\native-open-close.etl
```

Use the WPR GPU activity profile/UI when available for the installed toolkit;
`GeneralProfile` alone is not a guarantee that every desired GPU provider is
enabled. Save the chosen profile and provider settings with the run. In WPA/
GPUView inspect application CPU work, thread waits, DWM composition, GPU queues,
copy work, present modes and missed display deadlines. Avoid per-frame disk logs
on the UI/render thread; buffer instrumentation or use ETW events.

Use a pinned PresentMon CLI release, preserving its `--help` output and version.
For current CLIs that expose these options, an example is:

```powershell
PresentMon.exe --process_name CaelestiaShell.exe --timed 120 --terminate_after_timed --output_file .\results\native-presents.csv
```

Use the actual native executable name produced by the build. For legacy, capture
each relevant process/swap chain separately; do not merge unrelated swap-chain
timestamps into one apparent animation stream. DWM may continue composing without
a new application present, and Qt UI paths may not expose the same event stream.
Explain missing coverage and supplement with ETW/application markers rather than
inventing comparable FPS. PresentMon CLI schemas/column names vary by version;
save the CSV schema and explicitly state which timing field is analyzed.

Measure GPU engine busy time and allocation/residency using ETW/WPA/GPUView or a
supported vendor GPU profiler. Report GPU model/driver, per-engine utilization,
dedicated/shared memory categories, resource count, resize allocation rate and
capture pool/copy estimates separately. The old `lg_resource_info` reports
texture-byte estimates, not private resident VRAM. Windows per-process GPU
accounting can include shared allocations; do not sum it as exclusive VRAM.
Mark absent GPU instrumentation **unavailable**.

## Frame-time statistics and input latency

Only analyze display/present intervals within explicitly marked active animation
segments. Keep idle periods, intentional clock updates, warmup and pauses out of
the animation sample; report them separately. Store the exact sample count and
percentile definition. One reproducible choice is nearest-rank percentile:
sort N intervals and select index `ceil(p*N)-1` for P95/P99. Also report median,
maximum, count over one/two frame budgets, dropped presents and missed refresh
deadlines when those signals are available. No presents at idle is expected
behavior, not a zero-FPS failure.

```text
frame_budget_ms = 1000 / active_refresh_hz
60 Hz: 16.67 ms; 120 Hz: 8.33 ms; 144 Hz: 6.94 ms;
165 Hz: 6.06 ms; 240 Hz: 4.17 ms
```

An application present interval is not automatically a displayed frame or a
photon timestamp. A dropped-present flag is also different from an intentional
idle gap. Preserve those distinctions in tables.

For input latency, instrument QPC timestamps for input receipt, state change,
render submission and correlation to the relevant presented/displayed frame.
Record activation/key events while an opening animation is in flight; verify
text content and composition results in addition to timestamps. Receipt-to-
submission is an internal proxy; do not label it input-to-visible latency.
If end-to-end latency is required, use a high-speed camera or appropriate
hardware measurement with a visible response marker and a documented input
trigger. Report repetitions, P50/P95/P99 and camera sampling uncertainty.

For startup, use the same launcher and a monotonic timestamp at process creation;
record first successful present, first visible usable bar and input-ready time
separately. Report cold and warm startup separately, with at least ten runs.

## Legacy regression commands

Run from the untouched legacy repository with its prepared Windows runtime:

```powershell
& '<legacy-install>\python\python.exe' tools\check_install.py '<legacy-install>'
& '<legacy-install>\python\python.exe' tools\check_launcher_input.py '<legacy-install>'
& '<legacy-install>\python\python.exe' tools\check_launcher_commands.py '<legacy-install>'
& '<legacy-install>\python\python.exe' tools\check_activities.py '<legacy-install>' '<fresh-activity-output-directory>'
& '<legacy-install>\python\python.exe' tools\check_resources.py '<legacy-install>'
& '<legacy-install>\python\python.exe' tools\benchmark_glass.py '<legacy-install>' '<absolute-dll-path>' '<fresh-output-directory>'
```

Use a fresh process for each native DLL fixture run. The fixture's owned-window
pixel comparison, static redraw and cleanup checks are useful optical regression
evidence, but they remain a separate experiment from full-shell memory, gaming,
battery usage, IME and local display pacing.

## Required result record and acceptance

Every published result should contain variant/commit, build/tool versions,
machine/display metadata, scenario, scope (complete app or matching subset), run
count, raw sanitized sample paths, chosen counters, summary statistics,
failures and limitations. Keep a separate functionality matrix with pass/fail/
not-tested/not-implemented states. Visual comparison must use matched theme,
geometry, DPI and background; do not trade away glass quality to claim a small
resource improvement.

Before calling Phase 1 validated, build and run it on Windows, verify the bar,
text/icons/clock/workspace behavior, theme data, DPI/display changes, reduced
motion, clean exit, idle redraw suspension and interrupted animation behavior.
Record actual results, including any GPU fallback. Passing a compiler or a
portable animation test alone does not satisfy this acceptance gate.

## Primary references

- [Microsoft WPR command-line options](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/wpr-command-line-options)
- [Microsoft GPUView overview](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/using-gpuview)
- [PresentMon source and CLI documentation](https://github.com/GameTechDev/PresentMon)
- [PresentMon command-line parser](https://github.com/GameTechDev/PresentMon/blob/main/PresentMon/CommandLine.cpp)
- [Microsoft GPU accounting explanation](https://devblogs.microsoft.com/directx/gpus-in-the-task-manager/)
