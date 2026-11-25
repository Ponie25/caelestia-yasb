# Changelog

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
