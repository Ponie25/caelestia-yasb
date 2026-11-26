# Caelestia Shell — native Phase 1 prototype

An isolated C++20 Windows desktop bar. The legacy YASB/Python/Qt distribution is
unchanged. Explorer, DWM and Komorebi stay running. This prototype is not a
replacement for the complete legacy Island/launcher/Settings yet.

## Chạy thử trên Windows 11 x64

1. Giải nén **toàn bộ** gói Windows vào một thư mục riêng. Giữ `config/`, font,
   giấy phép và `liquid_glass.dll` bên cạnh `caelestia-shell.exe`.
2. Thoát YASB thủ công nếu muốn so sánh mà không có hai thanh bar chồng nhau.
3. Chạy `caelestia-shell.exe`. Không cần admin, Python hay Qt. Bar dùng nền
   transparent hiện tại, font/theme từ cấu hình và đồng hồ theo locale Windows.
4. Nhấp phải hoặc bấm biểu tượng bên phải để tải lại theme, xem chuyển động,
   kết nối lại Komorebi, xem thông tin hoặc **Thoát Caelestia Shell**.

Search opens Windows Search for this phase; the integrated Caelestia launcher is
Phase 2. Workspace stars appear only when a running Komorebi is available through
`komorebic.exe` on PATH. Clicking a star sends an asynchronous workspace command;
the selected star follows real subscription state. No fabricated workspaces.
If Komorebi starts later, use **Kết nối lại Komorebi**. It is never installed,
started, stopped, themed, or reconfigured by this prototype.

Optional arguments (PowerShell):

```powershell
# Existing repository configuration, with an optional Liquid Glass bar preview:
.\caelestia-shell.exe --config "C:\src\caelestia-yasb\config" --glass
# Choose a physical display and an independently mapped Komorebi monitor index:
.\caelestia-shell.exe --monitor 1 --komorebi-monitor 1
# Save bounded CPU submission diagnostics on a clean exit:
.\caelestia-shell.exe --trace "$PWD\frames.csv"
```

The display indices from Win32 enumeration and Komorebi need not be equal. The
default is the primary display and Komorebi monitor zero. Phase 1 has one bar;
simultaneous bars on every monitor remain Phase 3 work.

`--glass` explicitly previews the existing native optical material on the bar;
the ordinary transparent bar remains the default to preserve existing layout.
The compact/expanded Island is not ported in this phase. Glass may fall back to
the configured bar background when capture is unavailable. The x64 DLL in a
cross-built bundle is the existing tracked renderer binary; MSVC builds rebuild
it from its retained MIT source. There is no WacOS code or asset reuse.

Exit removes this process's AppBar reservation. Delete this standalone folder
to uninstall; no startup entry, service, Explorer replacement or global launcher
hotkey is installed. Runtime reports are written on exit to
`%LOCALAPPDATA%\CaelestiaShell\native-shell-report.txt`.

## Build

Windows: Visual Studio 2022 C++ desktop tools, Windows SDK with C++/WinRT, CMake
3.24+. No dependency download is performed by the CMake project.

```powershell
cmake -S native-shell -B native-shell/build -G "Visual Studio 17 2022" -A x64
cmake --build native-shell/build --config Release --parallel
ctest --test-dir native-shell/build -C Release --output-on-failure
cmake --install native-shell/build --config Release --prefix native-shell/out/windows-x64
```

On macOS/Linux, the same project builds the portable core and tests only:

```sh
cmake -S native-shell -B native-shell/build -DCMAKE_BUILD_TYPE=Release
cmake --build native-shell/build --parallel
ctest --test-dir native-shell/build --output-on-failure
```

For an optional macOS-to-Windows x64 cross-build, extract a verified LLVM-MinGW
release, set `LLVM_MINGW_ROOT`, and configure with
`-DCMAKE_TOOLCHAIN_FILE=cmake/llvm-mingw.cmake -DCAELESTIA_BUILD_GLASS=OFF`.
This produces Windows executables; it does not execute them on macOS. A CI
workflow builds with MSVC, rebuilds the glass DLL, runs portable tests on Windows
and macOS, validates config, and uploads a Windows bundle on the isolated branch.

## Evidence and remaining work

- [Legacy audit and reuse decisions](docs/legacy-audit.md)
- [WacOS source and licensing assessment](docs/wacos-reference.md)
- [Rendering, motion and service architecture](docs/architecture.md)
- [Reproducible Windows baseline methodology](docs/performance-methodology.md)
- [Actual build/test results and limitations](docs/validation.md)

The frame CSV records CPU submission duration and whether Present accepted a
buffer. It is **not** GPU frame time, screen presentation time, dropped frames,
input latency or a performance improvement. Use ETW/PresentMon and target Windows
hardware for those measurements, as described in the methodology.

The repository's GPL-3.0 and existing third-party notices remain in force. The
Liquid Glass source retains its MIT license. Source is supplied in the archive
and local Git branch together with this prototype; keep the notices with binaries.

For this delivered snapshot, GitHub write access was unavailable. The isolated
branch is local and supplied in the accompanying Git bundle/source archive;
Windows CI has not run. See the validation record for actual build evidence.
