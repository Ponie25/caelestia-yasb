#include "render_device.hpp"
#include "glass_bridge.hpp"
#include "windows_services.hpp"
#include <shellapi.h>
#include <shlobj.h>
#include <shellscalingapi.h>
#include <windowsx.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <fstream>
#include <memory>
#include <sstream>
#include <thread>
#include <vector>

namespace caelestia {
namespace {
constexpr UINT FrameMessage=WM_APP+1, WorkspaceMessage=WM_APP+2, ForegroundMessage=WM_APP+3;
constexpr UINT LayoutMessage=WM_APP+4, ReloadMessage=WM_APP+5, AppbarMessage=WM_APP+6;
constexpr UINT ClockTimer=1, GlassTimer=2, RetryTimer=3;
constexpr UINT MenuReload=101, MenuMotion=102, MenuReconnect=103, MenuInfo=104, MenuExit=105;
std::atomic<HWND> foreground_target{nullptr};
std::atomic<bool> foreground_pending{false};
double seconds() {
    static const double frequency=[] { LARGE_INTEGER f{}; QueryPerformanceFrequency(&f); return static_cast<double>(f.QuadPart); }();
    LARGE_INTEGER now{}; QueryPerformanceCounter(&now); return static_cast<double>(now.QuadPart)/frequency;
}
std::wstring widen(const std::string& value) {
    if (value.empty()) return {};
    int n=MultiByteToWideChar(CP_UTF8,0,value.data(),static_cast<int>(value.size()),nullptr,0);
    std::wstring result(static_cast<std::size_t>(std::max(0,n)),L' ');
    if (n) MultiByteToWideChar(CP_UTF8,0,value.data(),static_cast<int>(value.size()),result.data(),n);
    return result;
}
void CALLBACK foreground_hook(HWINEVENTHOOK, DWORD event, HWND window, LONG object, LONG, DWORD, DWORD) {
    if (!window || object!=OBJID_WINDOW) return;
    if (event==EVENT_OBJECT_LOCATIONCHANGE && window!=GetForegroundWindow()) return;
    if (HWND target=foreground_target.load()) {
        if (!foreground_pending.exchange(true) && !PostMessageW(target,ForegroundMessage,0,0)) foreground_pending=false;
    }
}
struct Display { HMONITOR handle{}; MONITORINFOEXW info{}; int refresh=60; };
BOOL CALLBACK enum_monitor(HMONITOR monitor,HDC,LPRECT,LPARAM data) {
    auto& list=*reinterpret_cast<std::vector<Display>*>(data);
    Display display{}; display.handle=monitor; display.info.cbSize=sizeof(display.info);
    if (!GetMonitorInfoW(monitor,&display.info)) return TRUE;
    DEVMODEW mode{}; mode.dmSize=sizeof(mode);
    if (EnumDisplaySettingsExW(display.info.szDevice,ENUM_CURRENT_SETTINGS,&mode,0) && mode.dmDisplayFrequency>1)
        display.refresh=static_cast<int>(mode.dmDisplayFrequency);
    list.push_back(display); return TRUE;
}

// One owned clock for this host. It waits for DXGI readiness off the UI thread,
// coalesces work, and waits for an acknowledgement before posting another frame.
class FrameScheduler {
public:
    FrameScheduler(HWND window,HANDLE ready,ULONG_PTR generation):window_(window),ready_(ready),generation_(generation) {
        stop_=CreateEventW(nullptr,TRUE,FALSE,nullptr);
        request_=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        ack_=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        if (!stop_ || !request_ || !ack_) {
            if (stop_) CloseHandle(stop_);
            if (request_) CloseHandle(request_);
            if (ack_) CloseHandle(ack_);
            throw std::runtime_error("Frame scheduler events");
        }
        worker_=std::thread([this] {
            const HANDLE requests[]={stop_,request_};
            const HANDLE frames[]={stop_,ready_};
            const HANDLE acks[]={stop_,ack_};
            while (WaitForMultipleObjects(2,requests,FALSE,INFINITE)==WAIT_OBJECT_0+1) {
                const DWORD result=WaitForMultipleObjects(2,frames,FALSE,1000);
                if (result==WAIT_OBJECT_0) break;
                if (result==WAIT_FAILED) { PostMessageW(window_,FrameMessage,TRUE,static_cast<LPARAM>(generation_)); break; }
                // A timeout wakes the UI once so it can recover a stalled device.
                if (!PostMessageW(window_,FrameMessage,result==WAIT_TIMEOUT,static_cast<LPARAM>(generation_))) break;
                if (WaitForMultipleObjects(2,acks,FALSE,INFINITE)!=WAIT_OBJECT_0+1) break;
            }
        });
    }
    ~FrameScheduler() {
        if (stop_) SetEvent(stop_);
        if (worker_.joinable()) worker_.join();
        if (ack_) CloseHandle(ack_);
        if (request_) CloseHandle(request_);
        if (stop_) CloseHandle(stop_);
    }
    void request() { SetEvent(request_); }
    void acknowledge() { SetEvent(ack_); }
private:
    HWND window_{}; HANDLE ready_{},stop_{},request_{},ack_{}; ULONG_PTR generation_{}; std::thread worker_;
};
struct FrameSample { double time{}, cpu_ms{}; bool submitted{}; };
struct Options {
    std::filesystem::path config, trace;
    bool glass=false, validate=false;
    int monitor=-1, komorebi_monitor=0;
};
Options options(const std::filesystem::path& executable) {
    Options result; result.config=executable.parent_path()/L"config";
    int count=0; auto args=CommandLineToArgvW(GetCommandLineW(),&count);
    if (!args) throw std::runtime_error("Command-line arguments");
    try {
        for (int i=1;i<count;++i) {
            const std::wstring arg=args[i];
            if (arg==L"--glass") result.glass=true;
            else if (arg==L"--validate-config") result.validate=true;
            else if ((arg==L"--config" || arg==L"--trace" || arg==L"--monitor" || arg==L"--komorebi-monitor") && i+1<count) {
                const std::wstring value=args[++i];
                if (arg==L"--config") result.config=std::filesystem::absolute(value);
                else if (arg==L"--trace") result.trace=std::filesystem::absolute(value);
                else {
                    std::size_t end=0; const int index=std::stoi(value,&end);
                    if (end!=value.size() || index<0) throw std::runtime_error("Monitor index must be a nonnegative integer");
                    if (arg==L"--monitor") result.monitor=index; else result.komorebi_monitor=index;
                }
            } else throw std::runtime_error("Usage: caelestia-shell [--config DIR] [--glass] [--monitor N] [--komorebi-monitor N] [--trace CSV] [--validate-config]");
        }
    } catch (...) { LocalFree(args); throw; }
    LocalFree(args); return result;
}
}

class Application {
public:
    Application(HINSTANCE instance,Options options,std::filesystem::path executable)
        :instance_(instance),options_(std::move(options)),executable_(std::move(executable)),config_(load_config(options_.config)) {
        samples_.reserve(8192);
    }
    ~Application() {
        foreground_target=nullptr;
        if (foreground_event_) UnhookWinEvent(foreground_event_);
        if (location_event_) UnhookWinEvent(location_event_);
        scheduler_.reset(); services_.reset();
        if (reload_worker_.joinable()) reload_worker_.join();
        if (search_worker_.joinable()) search_worker_.join();
        if (window_ && IsWindow(window_)) { remove_appbar(); DestroyWindow(window_); }
        // The inherited DLL can wait during teardown. Do it after the window loop,
        // never during an animation/input callback.
        glass_.close(); renderer_.reset();
    }
    int run() {
        if (options_.validate) return config_.warnings.empty() ? 0 : 2;
        WNDCLASSEXW cls{}; cls.cbSize=sizeof(cls); cls.lpfnWndProc=procedure;
        cls.hInstance=instance_; cls.lpszClassName=L"Caelestia.NativeShell.Bar";
        cls.hCursor=LoadCursorW(nullptr,IDC_ARROW);
        if (!RegisterClassExW(&cls)) throw std::runtime_error("Register native bar class");
        window_=CreateWindowExW(WS_EX_TOOLWINDOW|WS_EX_NOACTIVATE|WS_EX_NOREDIRECTIONBITMAP,
            cls.lpszClassName,L"Caelestia Shell",WS_POPUP,0,0,600,34,nullptr,nullptr,instance_,this);
        if (!window_) throw std::runtime_error("Create native bar window");
        taskbar_created_=RegisterWindowMessageW(L"TaskbarCreated");
        BOOL animations=TRUE; SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION,0,&animations,0);
        system_motion_=animations!=FALSE;
        register_appbar(); layout(); create_renderer();
        services_=std::make_unique<WindowsServices>(window_,WorkspaceMessage,options_.komorebi_monitor);
        services_->start();
        foreground_target=window_;
        foreground_event_=SetWinEventHook(EVENT_SYSTEM_FOREGROUND,EVENT_SYSTEM_FOREGROUND,nullptr,
            foreground_hook,0,0,WINEVENT_OUTOFCONTEXT|WINEVENT_SKIPOWNPROCESS);
        location_event_=SetWinEventHook(EVENT_OBJECT_LOCATIONCHANGE,EVENT_OBJECT_LOCATIONCHANGE,nullptr,
            foreground_hook,0,0,WINEVENT_OUTOFCONTEXT|WINEVENT_SKIPOWNPROCESS);
        if (options_.glass && config_.glass.enabled) {
            glass_open_=glass_.open(window_,executable_.parent_path()/L"liquid_glass.dll");
            if (glass_open_) { configure_glass(); glass_deadline_=seconds()+5; SetTimer(window_,GlassTimer,100,nullptr); }
        }
        update_clock(); update_foreground();
        if (!hidden_) ShowWindow(window_,SW_SHOWNOACTIVATE);
        entrance_.snap(0,seconds());
        entrance_.retarget(1,seconds(),config_.motion.duration("popup"),config_.motion.effects,motion());
        invalidate();
        MSG message{}; int status=0;
        while ((status=static_cast<int>(GetMessageW(&message,nullptr,0,0)))>0) {
            TranslateMessage(&message); DispatchMessageW(&message);
        }
        if (status<0) throw std::runtime_error("Windows message loop");
        return last_error_.empty() ? 0 : 1;
    }
    void write_report(const std::filesystem::path& log) const {
        std::ofstream out(log);
        out<<"Caelestia Shell Phase 1\nWindows runtime report; not a benchmark.\nprofile="<<config_.profile
           <<"\nrefresh_hz="<<display_.refresh<<"\ndpi="<<dpi_<<"\nglass_requested="<<options_.glass
           <<"\nglass_ready="<<scene_.glass_ready<<"\nframe_samples="<<samples_.size()
           <<"\ndevice_recoveries="<<recoveries_<<"\nerror="<<last_error_<<'\n';
        for (const auto& warning:config_.warnings) out<<"config_warning="<<warning<<'\n';
        if (!options_.trace.empty()) {
            std::ofstream trace(options_.trace);
            trace<<"qpc_seconds,cpu_submission_ms,present_accepted\n";
            for (const auto& sample:samples_) trace<<sample.time<<','<<sample.cpu_ms<<','<<sample.submitted<<'\n';
        }
    }
private:
    bool motion() const { return system_motion_ && config_.motion.enabled; }
    void invalidate() { dirty_=true; if (scheduler_ && !hidden_) scheduler_->request(); }
    void register_appbar() {
        APPBARDATA data{}; data.cbSize=sizeof(data); data.hWnd=window_; data.uCallbackMessage=AppbarMessage;
        appbar_=SHAppBarMessage(ABM_NEW,&data)!=0;
    }
    void remove_appbar() {
        if (appbar_) { APPBARDATA data{}; data.cbSize=sizeof(data); data.hWnd=window_; SHAppBarMessage(ABM_REMOVE,&data); appbar_=false; }
    }
    void layout() {
        std::vector<Display> displays; EnumDisplayMonitors(nullptr,nullptr,enum_monitor,reinterpret_cast<LPARAM>(&displays));
        if (displays.empty()) return;
        auto chosen=displays.begin();
        if (options_.monitor>=0 && static_cast<std::size_t>(options_.monitor)<displays.size()) chosen+=options_.monitor;
        else {
            const auto primary=std::find_if(displays.begin(),displays.end(),[](const Display& d) { return (d.info.dwFlags&MONITORINFOF_PRIMARY)!=0; });
            if (primary!=displays.end()) chosen=primary;
        }
        display_=*chosen;
        if (MonitorFromWindow(window_,MONITOR_DEFAULTTONEAREST)!=display_.handle)
            SetWindowPos(window_,nullptr,display_.info.rcMonitor.left,display_.info.rcMonitor.top,
                0,0,SWP_NOSIZE|SWP_NOZORDER|SWP_NOACTIVATE);
        const UINT current_dpi=GetDpiForWindow(window_);
        dpi_=static_cast<float>(current_dpi ? current_dpi : 96);
        APPBARDATA data{}; data.cbSize=sizeof(data); data.hWnd=window_; data.uEdge=ABE_TOP; data.rc=display_.info.rcMonitor;
        const LONG height=static_cast<LONG>(std::lround(config_.theme.bar_height*dpi_/96.f));
        if (appbar_) SHAppBarMessage(ABM_QUERYPOS,&data);
        data.rc.bottom=data.rc.top+height;
        if (appbar_) SHAppBarMessage(ABM_SETPOS,&data);
        SetWindowPos(window_,HWND_TOP,data.rc.left,data.rc.top,data.rc.right-data.rc.left,height,SWP_NOACTIVATE);
        if (renderer_) {
            RECT rc{}; GetClientRect(window_,&rc);
            renderer_->resize(static_cast<UINT>(rc.right),static_cast<UINT>(rc.bottom),dpi_);
            configure_glass(); invalidate();
        }
    }
    void configure_glass() {
        if (!glass_open_) return;
        RECT rc{}; GetClientRect(window_,&rc);
        glass_.configure(static_cast<UINT>(rc.right),static_cast<UINT>(rc.bottom),dpi_,config_,display_.refresh);
        glass_.suspend(hidden_);
    }
    void create_renderer() {
        scheduler_.reset(); renderer_.reset();
        frame_deferred_=false;
        renderer_=std::make_unique<RenderDevice>();
        RECT rc{}; GetClientRect(window_,&rc);
        renderer_->initialize(window_,static_cast<UINT>(rc.right),static_cast<UINT>(rc.bottom),dpi_,config_.theme,options_.config);
        const float opacity=static_cast<float>(entrance_.sample(seconds()).position);
        renderer_->compose(opacity,-6.f*(1.f-opacity));
        scheduler_=std::make_unique<FrameScheduler>(window_,renderer_->frame_ready(),++frame_generation_);
    }
    void frame(bool stalled) {
        if (!scheduler_) return;
        // The worker has consumed readiness for one buffer. Hold this acquired
        // frame while hidden; on show, submit it before acknowledging. Otherwise
        // a fullscreen transition can consume the final signal without Present.
        if (hidden_) { frame_deferred_=true; return; }
        const double now=seconds();
        try {
            if (stalled) throw std::runtime_error("DXGI frame wait timed out");
            scene_.indicator=indicator_.sample(now).position;
            scene_.hover=static_cast<float>(hover_.sample(now).position);
            const bool scene_animation=indicator_.active(now)||hover_.active(now);
            const bool animation=scene_animation||entrance_.active(now);
            // A scheduled tick always submits a buffer, including entrance-only
            // animation and the final settled frame. DXGI readiness is a frame
            // queue signal, not an independent compositor animation clock.
            const double begin=seconds();
            const bool presented=renderer_->draw(scene_);
            if (samples_.size()<8192) samples_.push_back({now,(seconds()-begin)*1000,presented});
            dirty_=!presented;
            if (presented) consecutive_failures_=0;
            const float progress=static_cast<float>(entrance_.sample(now).position);
            renderer_->compose(progress,-6.f*(1.f-progress));
            scheduler_->acknowledge();
            if (dirty_||animation) scheduler_->request();
        } catch (const std::exception& error) {
            last_error_=error.what(); scheduler_.reset(); renderer_.reset();
            ++recoveries_;
            if (++consecutive_failures_<=3) SetTimer(window_,RetryTimer,500,nullptr);
            else PostMessageW(window_,WM_CLOSE,0,0);
        }
    }
    void update_clock() {
        SYSTEMTIME time{}; GetLocalTime(&time);
        wchar_t date[80]{},clock[80]{};
        GetDateFormatEx(LOCALE_NAME_USER_DEFAULT,0,&time,L"ddd, dd MMM",date,80,nullptr);
        GetTimeFormatEx(LOCALE_NAME_USER_DEFAULT,0,&time,L"HH:mm",clock,80);
        scene_.clock=std::wstring(date)+L"  "+clock;
        SetTimer(window_,ClockTimer,std::max<UINT>(1,60000-time.wSecond*1000-time.wMilliseconds),nullptr);
        invalidate();
    }
    void set_hidden(bool value) {
        if (hidden_==value) return;
        hidden_=value; glass_.suspend(value);
        ShowWindow(window_,value ? SW_HIDE : SW_SHOWNOACTIVATE);
        if (!value) {
            if (frame_deferred_ && scheduler_) {
                frame_deferred_=false; dirty_=true;
                PostMessageW(window_,FrameMessage,0,static_cast<LPARAM>(frame_generation_));
            } else invalidate();
        }
    }
    void update_foreground() {
        HWND foreground=GetForegroundWindow(); if (!foreground || foreground==window_) return;
        wchar_t title[512]{}; GetWindowTextW(foreground,title,512);
        const bool title_changed=scene_.title!=title;
        if (title_changed) scene_.title=title;
        RECT rc{}; GetWindowRect(foreground,&rc);
        const auto monitor=MonitorFromWindow(foreground,MONITOR_DEFAULTTONEAREST);
        wchar_t cls[128]{}; GetClassNameW(foreground,cls,128);
        const bool desktop=wcscmp(cls,L"Progman")==0 || wcscmp(cls,L"WorkerW")==0 || wcscmp(cls,L"Shell_TrayWnd")==0;
        const auto& m=display_.info.rcMonitor;
        const bool fullscreen=!desktop && monitor==display_.handle && !IsIconic(foreground) &&
            rc.left<=m.left && rc.top<=m.top && rc.right>=m.right && rc.bottom>=m.bottom;
        set_hidden(fullscreen); if (title_changed) invalidate();
    }
    void menu() {
        const HWND previous_foreground=GetForegroundWindow();
        HMENU popup=CreatePopupMenu();
        AppendMenuW(popup,MF_STRING,MenuReload,L"Tải lại theme");
        AppendMenuW(popup,MF_STRING,MenuMotion,L"Xem chuyển động");
        AppendMenuW(popup,MF_STRING,MenuReconnect,L"Kết nối lại Komorebi");
        AppendMenuW(popup,MF_STRING,MenuInfo,L"Thông tin bản thử");
        AppendMenuW(popup,MF_SEPARATOR,0,nullptr);
        AppendMenuW(popup,MF_STRING,MenuExit,L"Thoát Caelestia Shell");
        POINT point{}; GetCursorPos(&point);
        // A temporary foreground menu allows normal dismissal. The bar itself
        // remains non-activating and never registers launcher/global hotkeys.
        SetForegroundWindow(window_);
        const UINT command=TrackPopupMenu(popup,TPM_RETURNCMD|TPM_RIGHTBUTTON,point.x,point.y,0,window_,nullptr);
        DestroyMenu(popup); PostMessageW(window_,WM_NULL,0,0);
        if (GetForegroundWindow()==window_ && previous_foreground && IsWindow(previous_foreground))
            SetForegroundWindow(previous_foreground);
        if (command) PostMessageW(window_,WM_COMMAND,command,0);
    }
    void reload() {
        if (reload_running_) return;
        if (reload_worker_.joinable()) reload_worker_.join();
        reload_running_=true;
        reload_worker_=std::thread([this] {
            reloaded_=std::make_unique<Config>(load_config(options_.config));
            PostMessageW(window_,ReloadMessage,0,0);
        });
    }
    void search() {
        if (search_running_.exchange(true)) return;
        if (search_worker_.joinable()) search_worker_.join();
        search_worker_=std::thread([this] {
            const HRESULT com=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
            ShellExecuteW(nullptr,L"open",L"search-ms:",nullptr,nullptr,SW_SHOWNORMAL);
            if (SUCCEEDED(com)) CoUninitialize();
            search_running_=false;
        });
    }
    LRESULT message(UINT message,WPARAM w,LPARAM l) {
        if (taskbar_created_ && message==taskbar_created_) { appbar_=false; register_appbar(); PostMessageW(window_,LayoutMessage,0,0); return 0; }
        switch (message) {
        case FrameMessage:
            if (static_cast<ULONG_PTR>(l)==frame_generation_) frame(w!=0);
            return 0;
        case WorkspaceMessage:
            if (services_) if (auto state=services_->take_update()) {
                scene_.workspaces=std::move(*state);
                indicator_.retarget(scene_.workspaces.focused_workspace,seconds(),motion()); invalidate();
            }
            return 0;
        case ForegroundMessage: foreground_pending=false; update_foreground(); return 0;
        case LayoutMessage: layout(); update_foreground(); return 0;
        case ReloadMessage:
            if (reload_worker_.joinable()) reload_worker_.join();
            if (reloaded_) { config_=std::move(*reloaded_); reloaded_.reset(); if (renderer_) renderer_->set_theme(config_.theme); }
            reload_running_=false; layout(); return 0;
        case AppbarMessage:
            if (w==ABN_POSCHANGED) PostMessageW(window_,LayoutMessage,0,0);
            else if (w==ABN_FULLSCREENAPP) set_hidden(l!=0);
            return 0;
        case WM_DISPLAYCHANGE: PostMessageW(window_,LayoutMessage,0,0); return 0;
        case WM_DPICHANGED: dpi_=static_cast<float>(HIWORD(w)); PostMessageW(window_,LayoutMessage,0,0); return 0;
        case WM_SETTINGCHANGE: {
            BOOL enabled=TRUE; SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION,0,&enabled,0); system_motion_=enabled!=FALSE;
            if (!motion()) { indicator_.snap(scene_.workspaces.focused_workspace,seconds()); hover_.snap(0,seconds()); entrance_.snap(1,seconds()); }
            invalidate(); return 0;
        }
        case WM_POWERBROADCAST:
            if (w==PBT_APMSUSPEND) { set_hidden(true); scheduler_.reset(); }
            else if (w==PBT_APMRESUMEAUTOMATIC || w==PBT_APMRESUMESUSPEND) {
                create_renderer(); layout(); set_hidden(false); update_clock(); update_foreground();
            }
            return TRUE;
        case WM_TIMER:
            if (w==ClockTimer) update_clock();
            else if (w==GlassTimer) {
                const bool ready=glass_.ready();
                if (ready!=scene_.glass_ready) { scene_.glass_ready=ready; invalidate(); }
                if (ready || glass_.failed() || seconds()>glass_deadline_) {
                    KillTimer(window_,GlassTimer);
                    if (!ready) { glass_.suspend(true); glass_open_=false; }
                }
            } else if (w==RetryTimer) {
                KillTimer(window_,RetryTimer);
                try { create_renderer(); last_error_.clear(); invalidate(); }
                catch (const std::exception& error) { last_error_=error.what(); PostMessageW(window_,WM_CLOSE,0,0); }
            }
            return 0;
        case WM_WINDOWPOSCHANGED:
            if (appbar_) { APPBARDATA data{}; data.cbSize=sizeof(data); data.hWnd=window_; SHAppBarMessage(ABM_WINDOWPOSCHANGED,&data); }
            break;
        case WM_PAINT: { PAINTSTRUCT paint{}; BeginPaint(window_,&paint); EndPaint(window_,&paint); invalidate(); return 0; }
        case WM_ERASEBKGND: return 1;
        case WM_MOUSEACTIVATE: return MA_NOACTIVATE;
        case WM_MOUSEMOVE: {
            TRACKMOUSEEVENT track{sizeof(track),TME_LEAVE,window_,0}; TrackMouseEvent(&track);
            RECT rc{}; GetClientRect(window_,&rc); const float x=static_cast<float>(GET_X_LPARAM(l))*96/dpi_;
            const bool hover=x>static_cast<float>(rc.right)*96/dpi_-40;
            if (hover!=hover_target_) { hover_target_=hover; hover_.retarget(hover ? 1 : 0,seconds(),motion()); invalidate(); }
            return 0;
        }
        case WM_MOUSELEAVE: hover_target_=false; hover_.retarget(0,seconds(),motion()); invalidate(); return 0;
        case WM_RBUTTONUP: menu(); return 0;
        case WM_LBUTTONUP: {
            RECT rc{}; GetClientRect(window_,&rc);
            const float x=static_cast<float>(GET_X_LPARAM(l))*96/dpi_, width=static_cast<float>(rc.right)*96/dpi_;
            if (x>width-40) menu();
            else if (x>width-280 && x<width-248) search();
            else if (scene_.workspaces.connected && x>=152 && x<152+24*static_cast<float>(std::min<std::size_t>(scene_.workspaces.populated.size(),12)))
                services_->focus_workspace(static_cast<int>((x-152)/24));
            return 0;
        }
        case WM_COMMAND:
            if (LOWORD(w)==MenuExit) PostMessageW(window_,WM_CLOSE,0,0);
            else if (LOWORD(w)==MenuReload) reload();
            else if (LOWORD(w)==MenuReconnect && services_) services_->reconnect();
            else if (LOWORD(w)==MenuMotion) { entrance_.snap(0,seconds()); entrance_.retarget(1,seconds(),config_.motion.duration("popup"),config_.motion.spatial,motion()); invalidate(); }
            else if (LOWORD(w)==MenuInfo) {
                std::wostringstream text; text<<L"Caelestia Shell · Phase 1\n"<<display_.info.szDevice<<L" · "<<display_.refresh<<L" Hz · "<<static_cast<int>(dpi_)<<L" DPI\nTheme: "<<widen(config_.profile)
                    <<L"\nLiquid Glass: "<<(scene_.glass_ready ? L"đã có frame" : (options_.glass ? L"chưa sẵn sàng" : L"tắt (dùng --glass để thử)"))
                    <<L"\n\nDynamic Island, launcher và Quick Settings sẽ được chuyển ở các giai đoạn sau.";
                MessageBoxW(window_,text.str().c_str(),L"Caelestia Shell",MB_OK|MB_ICONINFORMATION);
            }
            return 0;
        case WM_CLOSE:
            foreground_target=nullptr;
            scheduler_.reset(); services_.reset();
            remove_appbar(); DestroyWindow(window_); return 0;
        case WM_DESTROY: PostQuitMessage(0); return 0;
        }
        return DefWindowProcW(window_,message,w,l);
    }
    static LRESULT CALLBACK procedure(HWND window,UINT message,WPARAM w,LPARAM l) {
        auto* self=reinterpret_cast<Application*>(GetWindowLongPtrW(window,GWLP_USERDATA));
        if (message==WM_NCCREATE) {
            self=static_cast<Application*>(reinterpret_cast<CREATESTRUCTW*>(l)->lpCreateParams);
            self->window_=window; SetWindowLongPtrW(window,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(self));
        }
        if (!self) return DefWindowProcW(window,message,w,l);
        try { return self->message(message,w,l); }
        catch (const std::exception& error) { self->last_error_=error.what(); PostMessageW(window,WM_CLOSE,0,0); return 0; }
    }
    HINSTANCE instance_{}; Options options_; std::filesystem::path executable_; Config config_;
    HWND window_{}; UINT taskbar_created_{}; Display display_{}; float dpi_=96;
    bool appbar_=false,hidden_=false,dirty_=true,system_motion_=true,hover_target_=false;
    bool glass_open_=false,reload_running_=false; double glass_deadline_=0;
    int recoveries_=0,consecutive_failures_=0; std::string last_error_;
    bool frame_deferred_=false; ULONG_PTR frame_generation_=0;
    HWINEVENTHOOK foreground_event_{},location_event_{};
    std::unique_ptr<RenderDevice> renderer_;
    std::unique_ptr<FrameScheduler> scheduler_;
    std::unique_ptr<WindowsServices> services_;
    GlassBridge glass_; BarScene scene_; Spring indicator_,hover_; BezierTransition entrance_;
    std::thread reload_worker_; std::unique_ptr<Config> reloaded_;
    std::thread search_worker_; std::atomic<bool> search_running_{false};
    std::vector<FrameSample> samples_;
};
}

int WINAPI wWinMain(HINSTANCE instance,HINSTANCE,LPWSTR,int) {
    using namespace caelestia;
    const HRESULT com=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);
    if (FAILED(com)) return 1;
    int result=1;
    try {
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        std::vector<wchar_t> path(32768); const DWORD size=GetModuleFileNameW(nullptr,path.data(),static_cast<DWORD>(path.size()));
        if (!size || size>=path.size()) throw std::runtime_error("Executable path");
        auto executable=std::filesystem::path(std::wstring(path.data(),size));
        // One instance per user session; never terminate or replace another shell.
        HANDLE mutex=CreateMutexW(nullptr,FALSE,L"Local\\Caelestia.NativeShell.Phase1");
        if (!mutex) throw std::runtime_error("Single-instance mutex");
        const bool existing=GetLastError()==ERROR_ALREADY_EXISTS;
        if (existing) { CloseHandle(mutex); CoUninitialize(); return 0; }
        try {
            Application app(instance,options(executable),executable);
            result=app.run();
            PWSTR local=nullptr;
            if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_LocalAppData,0,nullptr,&local))) {
                const auto directory=std::filesystem::path(local)/L"CaelestiaShell";
                CoTaskMemFree(local); std::filesystem::create_directories(directory);
                app.write_report(directory/L"native-shell-report.txt");
            }
        } catch (...) { CloseHandle(mutex); throw; }
        CloseHandle(mutex);
    } catch (const std::exception& error) {
        const auto text=widen(error.what()); MessageBoxW(nullptr,text.c_str(),L"Caelestia Shell",MB_OK|MB_ICONERROR);
    }
    CoUninitialize(); return result;
}
