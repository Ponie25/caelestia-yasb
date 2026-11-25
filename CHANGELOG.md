# Changelog

## 2026-11-26 — Designed wallpaper presets

- Replace wallpaper-derived palette generation with deterministic selection from
  18 checked-in presets: nine color families, each with light and dark variants.
- Copy full preset palette/CSS files exactly; wallpaper pixels only choose the
  hue family and never create interface colors.
- Rename automatic mode to “Tự chọn preset” and show the selected preset's name
  in Settings. Preserve opacity, glass, layout, motion and Komorebi integration.
- Add an offline preset builder, reference board and checks for all palette
  contrasts, tone matching and byte-identical preset application.

## 2026-11-26 — Wallpaper interaction and automatic colors

- Animate gallery scrolling and scaling together; keep Up/Down selection until
  the pointer really moves instead of allowing hover to steal it during scroll.
- Default to installed favorites from the current Wallpaper Engine/Steam account.
  Cache the public list locally and provide All/Favorites and explicit refresh.
  No separate launcher favorites list or credential access is introduced.
- Generate a shared, contrast-normalized palette from the current static picture
  or Wallpaper Engine preview, preserving opacity, glass, layout and motion.
  Synchronize Komorebi borders and transparent-bar ink with that source.
- Add the automatic wallpaper scheme, light/dark tone controls and Settings draft
  protection. Fixed preset selection disables automatic colors.
- Prioritize nearby previews, protect visible entries in the bounded image cache,
  and prepare wallpaper metadata in the background after launcher activation.
- Validate keyboard/scroll intermediate states, favorite filtering, offline cache,
  multiple color seeds, shared theme application and unsaved Settings drafts.

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
