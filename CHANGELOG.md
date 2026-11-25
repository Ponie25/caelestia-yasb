# Changelog

## 2026-11-26 — Caelestia launcher commands

- Expand `>` with Scheme, Wallpaper, Random, Light/Dark and Windows session
  actions, following Caelestia's command groups.
- Add six-preset swatches and a wallpaper thumbnail carousel, including local
  projects from a running Wallpaper Engine. Keep wallpaper previews inside the
  launcher until the user applies one.
- Add a shared wallpaper-folder setting and optional Shutdown/Reboot/Logout,
  hidden by default. Require a fresh confirmation with Cancel selected first
  for sleep and destructive session commands.
- Use asynchronous, bounded local control for launcher-to-bar Settings/theme
  changes; respect outstanding Settings drafts.
- Grow the native launcher window when query results need more height, avoiding
  clipped rows after an initially short result list.
- Keep new indexing/preview work on demand with bounded traversal and a 32-image
  cache. Preserve early typing, IME, Esc and the collapsed Island menu action.
- Add command, gallery, IPC and confirmation regressions; extend install checks
  to cover launcher Settings and draft protection.

## 2026-11-25 — Resource optimization

- Remove unused Desktop Duplication allocations from the native WGC glass backend.
- Reduce capture queue buffering, narrow closed-pill layer discovery and stop
  hidden material health polling.
- Bound launcher icon retention to 64 recently used entries.
- Handle missing Windows media timelines/controls without reconnecting the listener.
- Add reproducible native resource/lifecycle checks and a transparent performance
  report. Keep Python/Qt and C++ for this update; a Rust rewrite is deferred.
- Preserve the bar layout, themes, glass settings, launcher focus/Esc behavior,
  and the collapsed Island's menu click action.

## 2026-11-25 — Settings and shared motion

- Add searchable native Settings, persistent save feedback and compact navigation.
- Share launcher-style motion across Island surfaces, menus and Settings.
- Publish the integrated Alt+Space launcher, Liquid Glass, six themes, current
  configuration and source-based portable installer.
