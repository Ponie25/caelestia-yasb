# Existing implementation audit

Audit baseline: `Ponie25/caelestia-yasb` commit
`8c4da7627bf56fa7723306876c25917c72f85d26` (2026-11-27).
This is a source and existing-results audit. The current session runs on macOS;
the existing Windows installation and graphics fixture have not been rerun here.
References below name source paths and baseline line numbers.

## Current architecture and observed costs

The status bar is the pinned YASB 2.0.8 application with PyQt patches. The Island
and launcher are a separate Python/PySide process; `patches/bar_manager.py:395`
starts `pythonw.exe` and removes inherited Qt plugin environment variables.
The separation is deliberate isolation of two Qt plugin environments. Consolidating
the native distribution can remove this duplicated UI stack, but no full-process
baseline in this repository quantifies the resulting memory or CPU saving.

`dependencies.json:1` pins the YASB MSI, Python embedded distribution, PySide,
WinRT projections, audio libraries and other wheels by SHA-256.
`patches/manifest.json:1` maps 23 source modules into the prepared YASB runtime,
including stock-module hashes. This is reproducible but tightly coupled to the
upstream package layout, bytecode/runtime version and private widget interfaces.
Do not change or remove that installer while developing the standalone shell.
`patches/motion_spec.py` and `patches/theme_tokens.py` are byte-identical to their
Island copies at this baseline. That preserves current consistency but creates a
maintenance drift risk; the native implementation should consume one data
contract and keep parity cases rather than maintain two translated token engines.

The optical material is **already native C++/D3D11**, not a Python shader.
`native/liquid-glass/lgwin.cpp:377` creates a BGRA D3D11 device, a protected
immediate context and a DirectComposition device. `:460` creates a premultiplied
flip-sequential composition swap chain. `:158` onward captures relevant windows
using Windows Graphics Capture (WGC); frame callbacks copy GPU textures, release
the frame, and wake the renderer. `hlsl.inc` implements the optical shader,
masking, blur and blit passes. The existing MIT notice and exact upstream pin are
in `native/liquid-glass/LICENSE` and `UPSTREAM.md`.

The status bar, Island Qt animation timers, and glass worker have independent
render schedules. `island.pyw:180` uses precise Qt timers and `:949` applies a
user FPS interval; `lgwin.cpp:940` uses a time cap and `Present(0, 0)`. A cap of
120 or 240 does not establish refresh synchronization or stable display pacing.
This is an architectural reason to evaluate a shared native schedule, not a
measured statement that either path is currently slow.

## Visual and behavior contract to retain

| Contract | Existing evidence |
| --- | --- |
| 34 logical-pixel top bar; Komorebi control, layout, workspace stars and current window on the left; search, clock and controls on the right | `config/config.yaml:8-61` |
| Bar font `JetBrainsMono NFP Light`, size 12, weight 600; configured spacing and padding | `config/bar-settings.json:5-28`; preserve the bundled OFL font notices |
| Idle Island width 116; 28-pixel optical pill inside a 32-pixel host | `config/bar-settings.json:63`; `config/dynamic-island/island.pyw:128,176` |
| Click anywhere on the collapsed pill opens its menu; activity badges have no separate collapsed action | Root `AGENTS.md`; this remains a regression requirement |
| Spatial, fast and effects cubic curves, including overshoot values above 1 | `config/motion-profile.json`; `patches/motion_spec.py:6-20` |
| Launcher 560 ms, popup 440 ms, menu 320 ms and close 220 ms before user scaling | `config/motion-profile.json`; `patches/motion_spec.py:37-52` |
| Palette roles plus contrast normalization, rather than arbitrary RGB replacements | `patches/theme_tokens.py:26-59`; `config/dynamic-island/palette.py:7-35` |
| Six manual themes and 18 curated wallpaper presets; wallpaper colors choose an existing preset, never synthesize UI colors | `config/theme-profiles/`; `config/wallpaper-presets/catalog.json`; `wallpaper_data.py:99-124` |
| Input exists and receives focus during launcher opening, before the first painted frame | `config/dynamic-island/launcher.py:106-128`; `tools/check_launcher_input.py:41-98` |
| Escape, focus restoration, Vietnamese IME and keyboard selection have existing regression fixtures | `launcher_focus.py`; `launcher_view.py`; `tools/check_launcher_input.py` |

The existing easing curves are data worth reusing. The current Island retarget
captures its present position and restarts elapsed-time interpolation
(`island.pyw:451-477`). It does not retain an explicit velocity state, so position
continuity is supported but velocity continuity across reversals is not
guaranteed by this implementation. A native motion engine should test both.
`patches/motion_spec.py:27-36` already respects the Windows client-animation
preference; the native version must preserve that behavior.

Visual review used `docs/screenshots/closed-island.png` and
`dynamic-island-showcase-16x9.png`. The closed state is a thin, rounded pill with
a centered four-square accent glyph and a restrained border. The showcase uses
the Catppuccin palette, rounded inset cards, consistent line icons, a selected
tab fill plus accent underline, and clear text hierarchy. It explicitly uses
sample data; treat it as a layout/color reference, not performance evidence or
proof of a live system integration. Phase 1 should retain the bar's existing
placement, proportions and typography rather than introduce a new app chrome.

## Integration audit

**Launcher and commands.** `launcher_core.py` provides Qt-independent result
types, matching, calculations, command groups and opt-in dangerous actions.
`launcher_windows.py:40-139` indexes on workers and uses a 64-entry icon LRU;
there is no case for reintroducing an unbounded cache. `launcher.py` owns UI
state, asynchronous local control, confirmation, focus and transition sequencing.
`launcher_focus.py:32` attaches thread input only for explicit activation.
Port the command semantics and fixtures, but use a real native edit control or
proper text-services integration in Phase 2. DirectWrite drawing alone does not
supply editable text, IME composition or accessibility.

**Media.** `media.py:85-161` subscribes to manager/session WinRT changes and also
uses a 1.25-second timed wake for snapshots and metadata retry. It is already
partially event-driven. Session generation checks, bounded async reads, missing
timeline handling and explicit unsubscription are useful designs. `player.py`
and the painters are Qt-specific. Rebuild the service against native WinRT,
retaining transport when timeline data is absent.

**Audio.** `volume.py:10-25,57-73` already registers Core Audio endpoint/device
notifications. However `island.pyw:556-564` calls the mixer from a one-second UI
timer; `audio_mixer.py:85-125` synchronously enumerates sessions and queries
volume. This is a potential blocking boundary, not a profiled stall. Native
Core Audio services should own apartment/callback lifetimes and publish immutable
snapshots. Default-output switching needs a separately documented API review;
do not assume the Python helper's entire implementation is a supported Win32 API.

**Notifications and Live Activities.** `patches/bar_manager.py:268-393` bridges
YASB's WinRT notification listener into per-user local IPC. `activities.py:120`
uses bounded newline-delimited packets and `UserAccessOption`; keep those trust
and size boundaries when migrating. The notification access grant, unavailable
listener state, DND handling, batching and individual/confirmed-clear actions
must remain visible behaviors. `live_activity.py` owns countdown, stopwatch,
selection and a 200 ms timer. The clock should run only when an active timer or
visible display requires it. `activities.py:38-117` reads Codex lock files and
only lifecycle columns in a local read-only SQLite connection, polling every
one or two seconds. That is a fragile external schema, so keep it behind an
optional adapter that can fail idle. It is not a shell-core dependency.

**Metrics and weather.** `resources.py:90,109-145` already collects metrics on a
single bounded executor, coalesces pending requests and bounds history. Preserve
those properties. `weather.py:95-130` fetches with an eight-second network
timeout off the UI thread and uses 20-minute success / one-minute failure
caching; this is not a frame-rate polling service. Networking, decoding and disk
access should remain off the native UI/render thread.

**Settings and Quick Settings.** `patches/bar_settings.py` and its mixins contain
schema validation, layout/widget editing, draft detection, backups and immediate
preference changes. `settings_immediate.py:25-28` debounces writes by 250 ms;
`settings_drafts.py` checks external state before committing drafts.
`quick_actions.py` and `system_controls.py` depend on YASB/Qt controls and
services. Reuse the JSON contracts, validations and behavioral cases, then
rebuild the UI and adapters in the later phases. Porting only the visible form
would omit conflict handling and safe action defaults.

**Wallpaper Engine and themes.** `launcher_wallpapers.py:23-59` bounds recursive
discovery, rejects symlink traversal and validates project preview paths.
`:61-84` indexes asynchronously with generation cancellation.
`wallpaper_data.py:51-71` reads public Steam favorites with cache and size/time
limits, without browser credentials. `patches/wallpaper_theme.py:28-43` decodes a
small image off-thread; `:82-104` copies an existing preset with rollback and a
snapshot. Preserve local metadata support, bounded workers and preset selection.
Its three-second discovery/signature polling (`patches/bar_theme.py:46-47`) is
a candidate for filesystem/system change notifications with a slow recovery
check, but any saving must be measured.

**Komorebi and Windows shell integration.** `patches/client.py:239` subscribes
to Komorebi; `komorebi_theme.py:34-61` already combines events, a configuration
watcher, a debounce and a single worker. Keep Komorebi external and optional.
The native bar should consume state and issue explicit commands without
replacing user configuration. `patches/bar_helper.py:535-647` handles AppBar
fullscreen notifications and Explorer restart; a native port must preserve
work-area negotiation, Explorer recovery and non-activating display behavior.
The old Island also polls its anchor at 400 ms and outside clicks at 12 ms
while open (`island.pyw:186-193,524-545`). A native host can use window/system
events and owned popup dismissal; avoid carrying that polling into its core.

## Rendering reuse and remaining risks

The existing shader's identity and material parameters should remain the optical
reference. Reusing its DLL initially is a reasonable reversible bridge, but it
adds a second device/context, worker and swap chain beside the native host.
It cannot be described as a unified render pipeline until those ownership and
pacing boundaries are actually consolidated and compared on Windows.

WGC frame pools still cover each captured source window, even when the visible
pill is small. Intersecting-layer selection reduces irrelevant sources; it does
not crop the underlying WGC frame pool. The renderer retains GPU copies and
locks around frame access, generates mipmaps and performs blur/composition.
Profile capture callback work, resource allocation on resize and GPU copy/blur
time before changing optical quality. Avoid duplicated capture backends:
`lgwin.cpp:475-481` already skips Desktop Duplication when WGC is selected.

`lgwin.cpp:751-963` is a process-global worker with mixed capture, window
management and rendering concerns. Error checks exist, but recovery is not a
complete per-device service boundary; audit device removal, adapter migration,
HDR/color space and resume separately. `lg_destroy` can wait up to about two
seconds (`:1014-1019`), and `lg_shutdown` joins the shared worker (`:1103`).
Do not put those potentially blocking operations on an interactive native UI
thread. Diagnostic texture readback and dumps are benchmark-only paths, not a
normal display-data path.

## Migration decision matrix

| Component | Decision | Rationale / retirement condition |
| --- | --- | --- |
| Existing Python/YASB installer and runtime | Retain unchanged | Regression reference until native parity and stability are demonstrated |
| Palette JSON, motion JSON, fonts and notices | Reuse | Preserve identity; validate and load independently of Qt |
| Contrast and preset-selection algorithms | Port with matching cases | Pure logic and existing curated assets; preserve token meanings |
| HLSL optics and MIT Liquid Glass implementation | Reuse behind an adapter, then evaluate integration | Existing working optical path; shared-device capture must be measured before consolidation |
| PyQt bar widgets and PySide painting | Rewrite per phase | Native text/layout/input/accessibility/composition replace these UI-specific layers |
| Qt timer animation implementation | Replace | Need shared display pacing, stateful velocity continuity and no idle animation timer |
| Launcher query/command behavior | Port | Preserve ranking, history, safe action defaults and keyboard behavior |
| Python/WinRT media and notification bridges | Replace adapters in Phase 3 | Native WinRT can retain event contracts and cleanup behavior |
| Python Core Audio bridge and mixer polling | Replace in Phase 3 | Native callbacks, bounded worker enumeration and explicit lifetimes |
| Wallpaper metadata, discovery limits and preset catalog | Reuse contracts/assets, port adapters | Preserve favorite/cache/path semantics without Python runtime dependency |
| Settings validation, backups and draft rules | Reuse contract, rebuild UI in Phase 4 | Required to avoid losing existing safe-edit behavior |
| Komorebi subscription and theme semantics | Port | Already event-driven; keep external process/configuration intact |
| Codex local-history adapter | Optional future port | External private schema; never required to launch the shell |
| Legacy patch manifest and Qt/Python bundles | Retire only from native distribution after parity | Keep legacy build available; never delete as part of Phase 1 |
| Existing Windows regression fixtures | Retain; translate applicable contracts | Supplement with native input, rendering and service tests |

## Existing validation and limits

`tools/check_install.py` exercises prepared runtime imports, Settings, themes,
config validation and drafts. `check_launcher_input.py` tests early typing,
composition strings and Escape using an isolated/offscreen Qt host; it does not
prove native Windows foreground/IME integration. `check_launcher_commands.py`
mocks session/wallpaper mutations and tests commands, confirmations, gallery and
asynchronous control. `check_activities.py` covers activities/notification cases.
`check_resources.py` exercises the icon LRU, media teardown/timeline behavior and
hidden-material timer suspension. `benchmark_glass.py` checks native redraw,
live updates, resize cycles, suspend/resume, resource cleanup and owned output.
These are substantive regression references, not a substitute for native tests.

The 2026-11-25 report in `docs/performance.md` describes one controlled native
fixture at 150% DPI on a 28-logical-CPU Windows machine. It reports closed
private commit 153.0 to 90.3 MiB, open 167.9 to 106.5 MiB, and after three resize
cycles 169.0 to 108.1 MiB. Resident working set did **not** decrease equivalently:
90.7 to 89.8, 94.4 to 102.2 and 103.9 to 105.6 MiB respectively.
Both variants produced zero new native frames in the static 1.4-second interval.
These numbers cover the fixture process, not YASB plus Island or this native
prototype. They do not establish a CPU, display-FPS, gaming or language-level
improvement. Raw inputs are in `docs/performance/`. Establish the new full-app
baseline using [performance-methodology.md](performance-methodology.md).
