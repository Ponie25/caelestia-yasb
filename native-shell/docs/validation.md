# Validation record — 2026-11-27

Work is isolated on the local branch `codex/native-shell-phase1`. The starting legacy commit is
`8c4da7627bf56fa7723306876c25917c72f85d26`. Existing tracked files are unchanged;
only `native-shell/` and its dedicated `.github/workflows/native-shell.yml` are
added. No main commit, merge, release or legacy runtime removal is part of this
change.

## Observed locally on Apple Silicon macOS

- CMake 4.4.5 + Ninja 1.13.2, AppleClang 21.0.0, C++20 Release: portable core and
  tests configured, compiled and linked successfully. CTest: 1/1 test passed;
  the test executable reported **82 native core checks passed**.
- The core author also ran AddressSanitizer/UndefinedBehaviorSanitizer and strict
  warnings successfully on macOS. Tests cover source configuration/palette,
  malformed JSON, Unicode, path validation, real Komorebi schema, time-based
  spring invariance at 60/120/144/165/240 Hz, all damping regimes, long pauses,
  reduced motion, cubic-bezier inversion/overshoot and C1 interrupted retargets.
- LLVM-MinGW **20261117**, Clang 23.1.6, Windows x64 cross-build: native host and
  core-test executables compiled and linked. The downloaded toolchain archive
  matched its published SHA-256:
  `98d340bbb8d46b09ad6886ffba88bd9d5415e131c316de48e6bd7647377446aa`.
- `file` identified `caelestia-shell.exe` as a **PE32+ GUI x86-64 executable for
  Windows**. Import inspection found Windows graphics/system/UCRT libraries;
  no Python, Qt, browser runtime or external C++ runtime DLL import in this host.
- The optional renderer DLL packaged by a cross-build is the existing tracked
  x64 `config/dynamic-island/native/liquid_glass.dll`; it has **not** been rebuilt
  by the cross compiler. The MSVC CMake target rebuilds its original source.
- Independent code review found and corrected a DXGI scheduling error for
  entrance-only frames, initial opacity/fullscreen display issues, silent wait
  failure handling, a consumed-readiness edge case during fullscreen transitions,
  stale frame messages after device recreation and mixed-DPI API usage before packaging.
- The process collector parsed with official PowerShell 7.7.0 on macOS with
  **zero syntax errors**. Its Windows PowerShell 5.1 execution remains unverified.

These observations prove compilation and portable logic checks. They do not
prove Windows UI execution, screenshot fidelity, real refresh-rate pacing,
capture behavior, gaming compatibility or measured resource improvement.

## Windows CI

The branch-specific workflow builds with Visual Studio 2022 x64, rebuilds the
existing renderer source, runs the core tests on Windows and macOS, checks config
without creating a window, exercises the process collector on Windows PowerShell
5.1 and uploads an install-tree artifact. Consult the exact workflow run for its
result; a configured workflow is not itself a successful Windows test.

In this session, creating the remote branch through the GitHub integration
returned HTTP 403 (`Resource not accessible by integration`). A normal Git push
dry-run also found no configured HTTPS login. Therefore the branch has not been
pushed, **the workflow has not run**, and no MSVC/Windows runtime result is
claimed. Local source archives and a Git bundle preserve the isolated branch so
it can be transferred to the user's Windows machine or pushed after login.

## Outstanding target-Windows validation

- Run the packaged host, visually compare typography/alignment/colors against
  the supplied screenshots and check transparent/default and `--glass` modes.
- Verify real Komorebi subscriptions, workspace clicks, daemon disconnect/manual
  reconnect and independent monitor-index mapping.
- Verify AppBar work-area registration/removal, menu focus and fullscreen hide,
  Explorer restart, display changes/mixed DPI and sleep/resume.
- Exercise hardware/WARP initialization, graphics device loss and WGC failure;
  late failures of the inherited glass path remain an explicit limitation.
- Measure the complete legacy/native process trees on the same Windows hardware
  with the [baseline protocol](performance-methodology.md). No new CPU/GPU,
  commit/working-set, latency, P95/P99, dropped-frame, startup or gaming figures
  are claimed here. The older repository measurements are not this prototype's
  results.
- Accessibility is incomplete: reduced motion is implemented, but the custom
  drawn bar has no full UI Automation provider/high-contrast parity yet. The
  interactive Island, launcher, IME/focus tests, media/audio/notifications,
  Quick Settings, Settings and wallpaper controls remain later phases.

The immediate usable deliverable is a separately packaged bar prototype plus
source, audit, architecture and measurement tooling. Full native feature parity
and final rendering architecture are still open work.
