#pragma once

#include <windows.h>

#include <memory>
#include <optional>

#include "caelestia/core.hpp"

namespace caelestia {

// Optional Komorebi adapter. The caller owns the target HWND and must destroy
// this service before destroying that window. Notifications carry no pointers;
// take_update() consumes the latest coalesced snapshot on the UI thread.
class WindowsServices {
public:
    WindowsServices(HWND target, UINT update_message, int monitor_index);
    ~WindowsServices();
    WindowsServices(const WindowsServices&) = delete;
    WindowsServices& operator=(const WindowsServices&) = delete;

    void start();
    void focus_workspace(int index);
    void reconnect();
    [[nodiscard]] std::optional<WorkspaceState> take_update();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace caelestia
