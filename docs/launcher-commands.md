# Launcher commands

Press **Alt+Space**, type `>`, then select a command. The list scrolls beyond the
visible rows. Typing filters it; Up/Down, Tab/Shift+Tab or the mouse selects a
result. Enter accepts it, and Esc closes the launcher at any animation phase.
Left/Right remain ordinary text-editing keys, including in the wallpaper carousel.

## Commands

| Input | Result |
| --- | --- |
| `>calc sqrt(144)` | Calculate and press Enter to copy the result. Existing percentages and unit conversions remain available. |
| `>scheme` | Choose one of six existing presets with palette swatches and the current selection marked. Add a name, for example `>scheme cat`, to filter. |
| `>light`, `>dark` | Apply the Light or Dark preset. |
| `>wallpaper` | Browse thumbnails from your image folder and the local library of a running Wallpaper Engine. Add part of the title to filter. |
| `>wallpaper folder` | Choose another image directory. The directory is shared with Settings. |
| `>wallpaper refresh` | Rescan after adding files, starting Wallpaper Engine or replacing a preview. |
| `>random` | Apply a random library item, avoiding the last selection when alternatives exist. |
| `>lock` | Lock the Windows session. |
| `>sleep` | Show confirmation, then put Windows to sleep. |
| `>shutdown`, `>reboot`, `>logout` | Show confirmation for the corresponding Windows session action. Hidden until enabled in Settings. |
| `>bar` | Open the bar's Settings window. |
| `>settings` | Open Windows Settings; this existing shortcut is preserved. |
| `>web search text` | Search with the default browser. |
| `>documents`, `>downloads` | Open Windows' corresponding Known Folder, including redirected locations. |
| `>island`, `>timer` | Open the Island menu or its Live Activity timer. |

Aliases include `>theme`, `>themes`, `>schemes`, `>background`, `>wallpapers`,
`>restart`, `>signout`, `>logoff`, `>suspend` and `>poweroff`.

Selecting a theme uses the same full-preset path as Settings: custom appearance
and glass overrides reset to that preset's original values. Bar layout, enabled
widgets, wallpaper directory and activity options remain intact. Preset changes
also use the existing Komorebi border synchronization settings.

## Wallpaper library

Choose a directory in **Settings → Island và Launcher → Thư mục hình nền**,
or use `>wallpaper folder`. An empty setting means the installed
`config/wallpapers` directory. Supported static files are JPG/JPEG, PNG, BMP and
WebP; Windows must also be able to decode the chosen file as a desktop wallpaper.
Subfolders up to two levels deep are included. Individual Wallpaper Engine
project folders are recognized from `project.json`.

If Wallpaper Engine is running when indexing starts, its own local projects and
Steam Workshop library are included. The first available `wallpaper64.exe` or
`wallpaper32.exe` process identifies the installation; no Steam installation is
required for ordinary static pictures. Start Wallpaper Engine and use
`>wallpaper refresh` if it was not running during the first scan.

The launcher shows previews without changing your desktop. Enter or a click
applies the selected item. Static images use Windows' `IDesktopWallpaper` on all
monitors; a running Wallpaper Engine is stopped through its documented playback
control so it does not cover the image. Selecting an Engine project uses its
`openWallpaper` CLI command and the app's default monitor behavior. This version
does not provide separate monitor selection.

“Đã chọn” means the last choice made here, not a claim to track changes made in
other wallpaper apps. That state stays in local `wallpaper-state.json`. Personal
images and state are excluded from Git; absolute directories live in the user's
local `bar-settings.json` and should be removed before sharing a personal config.

Discovery and preview decoding run in background threads only when requested.
Scans stop at 2,000 items, 5,000 folders or 12,000 directory entries. Filtering
shows up to 24 matches; narrow the query to reach other items. Only nearby cards
request previews, decoded at up to 320×180 with a 32-image cache. There is no
continuous wallpaper scan or new idle polling timer.

## Session actions

Like Caelestia, Shutdown/Reboot/Logout are disabled by default. Enable **Lệnh
tắt máy, khởi động lại và đăng xuất** under **Island và Launcher** to expose them.
Typing an exact disabled command provides a shortcut to that Settings page.

Sleep and these three session actions first show **Hủy** selected; choose the
second row deliberately to continue. Editing the query invalidates that
confirmation. Lock runs directly after the launcher closes. The implementation
uses fixed Windows APIs or fixed executable arguments; query text is never run
as shell code. No force-close flag is supplied to Windows session commands.

## What comes from Caelestia

The command names and default power visibility follow the official
[launcher configuration](https://github.com/caelestia-dots/shell/blob/5cbf60e7c6dbdd2b94faa5444435b8d9cac7bd46/plugin/src/Caelestia/Config/launcherconfig.hpp),
with palette swatches from its Scheme items and a scaled thumbnail carousel
inspired by its
[WallpaperList](https://github.com/caelestia-dots/shell/blob/5cbf60e7c6dbdd2b94faa5444435b8d9cac7bd46/modules/launcher/WallpaperList.qml).
The search surface keeps this project's shared Island material and morph.

Windows adaptations are explicit: Scheme selects this setup's six presets,
rather than Caelestia's dynamic color generator; Sleep uses Windows sleep,
rather than Linux suspend-then-hibernate. Caelestia's Material 3 **Variant**
command is not exposed because this project does not implement that generator.
`>bar` opens shell Settings while the existing `>settings` keeps opening Windows
Settings. Hovering wallpaper cards does not alter the desktop or regenerate
theme colors.

Backend references: [Wallpaper Engine CLI](https://help.wallpaperengine.io/en/functionality/cli.html)
and [Windows SetWallpaper](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-idesktopwallpaper-setwallpaper).

## Validation

On a prepared install, use its Python runtime to run:

```powershell
& '<install>\python\python.exe' tools\check_launcher_commands.py '<install>'
& '<install>\python\python.exe' tools\check_launcher_input.py '<install>'
& '<install>\python\python.exe' tools\check_install.py '<install>'
& '<install>\python\python.exe' tools\check_resources.py '<install>'
```

Command tests use generated fixture images and an isolated offscreen Island.
They do not register a desktop shortcut or start graphics capture. Actual theme,
wallpaper, lock, sleep and shutdown mutations are replaced with test doubles.
Local IPC uses random test sockets; Settings tests use a disposable config and
check that outstanding advanced drafts are respected.
