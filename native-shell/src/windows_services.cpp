#include "windows_services.hpp"

#include <sddl.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace caelestia {
namespace {

constexpr std::size_t max_packet_bytes = 8 * 1024 * 1024;
constexpr DWORD command_timeout_ms = 2500;
constexpr DWORD connection_timeout_ms = 3000;

class Handle {
public:
    Handle() = default;
    explicit Handle(HANDLE value) : value_(value) {}
    ~Handle() { reset(); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    Handle(Handle&& other) noexcept : value_(std::exchange(other.value_, nullptr)) {}
    Handle& operator=(Handle&& other) noexcept {
        if (this != &other) reset(std::exchange(other.value_, nullptr));
        return *this;
    }
    void reset(HANDLE value = nullptr) noexcept {
        if (*this) CloseHandle(value_);
        value_ = value;
    }
    [[nodiscard]] HANDLE get() const noexcept { return value_; }
    explicit operator bool() const noexcept {
        return value_ && value_ != INVALID_HANDLE_VALUE;
    }
private:
    HANDLE value_{};
};

struct LocalAllocation {
    HLOCAL value{};
    ~LocalAllocation() { if (value) LocalFree(value); }
};

bool same_state(const WorkspaceState& first, const WorkspaceState& second) {
    return first.connected == second.connected &&
           first.monitor_index == second.monitor_index &&
           first.focused_workspace == second.focused_workspace &&
           first.populated == second.populated && first.layout == second.layout;
}

std::wstring executable_on_path() {
    const auto length = GetEnvironmentVariableW(L"PATH", nullptr, 0);
    if (!length || length > 32768) return {};
    std::wstring path(length, L'\0');
    const auto copied = GetEnvironmentVariableW(L"PATH", path.data(), length);
    if (!copied || copied >= length) return {};
    path.resize(copied);
    std::wstring result(32768, L'\0');
    const auto found = SearchPathW(path.c_str(), L"komorebic.exe", nullptr,
                                  static_cast<DWORD>(result.size()), result.data(), nullptr);
    if (!found || found >= result.size()) return {};
    result.resize(found);
    return result;
}

// All generated arguments are fixed command words, digits, or our own pipe name.
// Quote the explicit executable path using the CreateProcess argv convention.
std::wstring quote_argument(const std::wstring& argument) {
    std::wstring result = L"\"";
    std::size_t slashes = 0;
    for (const auto character : argument) {
        if (character == L'\\') { ++slashes; continue; }
        if (character == L'\"') {
            result.append(slashes * 2 + 1, L'\\');
            result += character;
        } else {
            result.append(slashes, L'\\');
            result += character;
        }
        slashes = 0;
    }
    result.append(slashes * 2, L'\\');
    result += L'\"';
    return result;
}

struct CommandResult {
    bool succeeded{};
    std::string output;
};

// This bounded worker-only operation drains stdout while the child runs. The
// short timed wait exists only for an active command; there is no idle polling.
// A kill-on-close job owns the child tree, including inherited stdout writers.
CommandResult run_command(const std::wstring& executable,
                          const std::vector<std::wstring>& arguments,
                          HANDLE stop_event, DWORD timeout = command_timeout_ms,
                          bool ignore_stop = false) {
    CommandResult result;
    if (executable.empty() || (!ignore_stop && WaitForSingleObject(stop_event, 0) == WAIT_OBJECT_0))
        return result;

    SECURITY_ATTRIBUTES inherited{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    HANDLE read_raw{}, write_raw{};
    if (!CreatePipe(&read_raw, &write_raw, &inherited, 0)) return result;
    Handle read_pipe(read_raw), write_pipe(write_raw);
    if (!SetHandleInformation(read_pipe.get(), HANDLE_FLAG_INHERIT, 0)) return result;
    Handle null_file(CreateFileW(L"NUL", GENERIC_READ | GENERIC_WRITE,
                                FILE_SHARE_READ | FILE_SHARE_WRITE, &inherited,
                                OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    Handle job(CreateJobObjectW(nullptr, nullptr));
    if (!null_file || !job) return result;
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!SetInformationJobObject(job.get(), JobObjectExtendedLimitInformation,
                                 &limits, sizeof(limits))) return result;

    SIZE_T attribute_bytes{};
    InitializeProcThreadAttributeList(nullptr, 1, 0, &attribute_bytes);
    if (!attribute_bytes) return result;
    std::vector<std::byte> attributes(attribute_bytes);
    auto* attribute_list = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attributes.data());
    if (!InitializeProcThreadAttributeList(attribute_list, 1, 0, &attribute_bytes)) return result;
    struct AttributeGuard {
        LPPROC_THREAD_ATTRIBUTE_LIST list;
        ~AttributeGuard() { DeleteProcThreadAttributeList(list); }
    } attribute_guard{attribute_list};
    std::array<HANDLE, 2> inherited_handles{write_pipe.get(), null_file.get()};
    if (!UpdateProcThreadAttribute(attribute_list, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                   inherited_handles.data(), sizeof(inherited_handles), nullptr, nullptr))
        return result;

    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = null_file.get();
    startup.StartupInfo.hStdOutput = write_pipe.get();
    startup.StartupInfo.hStdError = null_file.get();
    startup.lpAttributeList = attribute_list;
    std::wstring command_line = quote_argument(executable);
    for (const auto& argument : arguments) command_line += L" " + quote_argument(argument);
    PROCESS_INFORMATION child{};
    if (!CreateProcessW(executable.c_str(), command_line.data(), nullptr, nullptr,
                        TRUE, CREATE_NO_WINDOW | CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT,
                        nullptr, nullptr, &startup.StartupInfo, &child)) return result;
    Handle process(child.hProcess), thread(child.hThread);
    if (!AssignProcessToJobObject(job.get(), process.get())) {
        TerminateProcess(process.get(), ERROR_CANCELLED);
        WaitForSingleObject(process.get(), 1000);
        return result;
    }
    if (ResumeThread(thread.get()) == std::numeric_limits<DWORD>::max()) {
        TerminateJobObject(job.get(), ERROR_CANCELLED);
        WaitForSingleObject(process.get(), 1000);
        return result;
    }
    write_pipe.reset();
    const auto started = GetTickCount64();
    bool failed = false;
    auto drain = [&] {
        std::array<char, 16384> buffer{};
        for (;;) {
            if (!ignore_stop && WaitForSingleObject(stop_event, 0) == WAIT_OBJECT_0) return false;
            DWORD available{};
            if (!PeekNamedPipe(read_pipe.get(), nullptr, 0, nullptr, &available, nullptr))
                return GetLastError() == ERROR_BROKEN_PIPE;
            if (!available) return true;
            DWORD received{};
            if (!ReadFile(read_pipe.get(), buffer.data(),
                          std::min<DWORD>(available, static_cast<DWORD>(buffer.size())),
                          &received, nullptr)) return GetLastError() == ERROR_BROKEN_PIPE;
            if (!received) return true;
            if (result.output.size() + received > max_packet_bytes) return false;
            result.output.append(buffer.data(), received);
            if (GetTickCount64() - started >= timeout) return false;
        }
    };
    for (;;) {
        if (!drain() || GetTickCount64() - started >= timeout) { failed = true; break; }
        const HANDLE waits[]{stop_event, process.get()};
        const auto wait = ignore_stop ? WaitForSingleObject(process.get(), 15)
                                      : WaitForMultipleObjects(2, waits, FALSE, 15);
        if (wait == (ignore_stop ? WAIT_OBJECT_0 : WAIT_OBJECT_0 + 1)) break;
        if ((!ignore_stop && wait == WAIT_OBJECT_0) || wait == WAIT_FAILED) { failed = true; break; }
    }
    if (failed) {
        TerminateJobObject(job.get(), ERROR_CANCELLED);
        WaitForSingleObject(process.get(), 1000);
        result.output.clear();
        return result;
    }
    if (!drain()) return result;
    DWORD exit_code{};
    result.succeeded = GetExitCodeProcess(process.get(), &exit_code) && exit_code == 0;
    return result;
}

// An explicit DACL admits only the current user. Failure is closed: optional
// Komorebi integration stays offline instead of using a world-writable pipe.
Handle create_user_pipe(const std::wstring& name) {
    HANDLE token_raw{};
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token_raw)) return {};
    Handle token(token_raw);
    DWORD bytes{};
    GetTokenInformation(token.get(), TokenUser, nullptr, 0, &bytes);
    if (!bytes || bytes > 65536) return {};
    std::vector<std::byte> information(bytes);
    if (!GetTokenInformation(token.get(), TokenUser, information.data(), bytes, &bytes)) return {};
    const auto* user = reinterpret_cast<const TOKEN_USER*>(information.data());
    LPWSTR sid_text{};
    if (!ConvertSidToStringSidW(user->User.Sid, &sid_text)) return {};
    LocalAllocation sid_allocation{sid_text};
    const std::wstring sddl = L"D:P(A;;GA;;;" + std::wstring(sid_text) + L")";
    PSECURITY_DESCRIPTOR descriptor{};
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1,
                                                             &descriptor, nullptr)) return {};
    LocalAllocation security_allocation{descriptor};
    SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), descriptor, FALSE};
    return Handle(CreateNamedPipeW((L"\\\\.\\pipe\\" + name).c_str(),
                                  PIPE_ACCESS_INBOUND | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
                                  PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                                  1, 0, 65536, 0, &security));
}

} // namespace

struct WindowsServices::Impl {
    HWND target{};
    UINT update_message{};
    int monitor_index{};
    Handle stop_event{CreateEventW(nullptr, TRUE, FALSE, nullptr)};
    Handle work_event{CreateEventW(nullptr, FALSE, FALSE, nullptr)};
    std::thread worker;
    std::mutex mutex;
    bool started{}, reconnect_requested{}, notification_pending{};
    std::optional<int> focus_requested;
    std::optional<WorkspaceState> latest, previous;

    struct Session {
        Handle pipe;
        Handle cancel{CreateEventW(nullptr, TRUE, FALSE, nullptr)};
        Handle connected_event{CreateEventW(nullptr, TRUE, FALSE, nullptr)};
        std::atomic<bool> connected{false};
        std::thread reader;
        std::wstring pipe_name, unsubscribe_command;
        ~Session() {
            if (cancel) SetEvent(cancel.get());
            if (pipe) CancelIoEx(pipe.get(), nullptr);
            if (reader.joinable()) reader.join();
            if (pipe) DisconnectNamedPipe(pipe.get());
        }
    };

    Impl(HWND window, UINT message, int monitor)
        : target(window), update_message(message), monitor_index(std::max(0, monitor)) {
        if (!stop_event || !work_event) throw std::runtime_error("Cannot create Windows service events");
    }

    ~Impl() {
        SetEvent(stop_event.get());
        if (worker.joinable()) worker.join();
    }

    void publish(WorkspaceState state) {
        bool post = false;
        {
            std::lock_guard lock(mutex);
            if (previous && same_state(*previous, state)) return;
            previous = state;
            latest = std::move(state);
            if (!notification_pending) { notification_pending = true; post = true; }
        }
        if (post && !PostMessageW(target, update_message, 0, 0)) {
            std::lock_guard lock(mutex);
            notification_pending = false;
        }
    }

    void offline() {
        WorkspaceState state;
        state.monitor_index = monitor_index;
        publish(std::move(state));
    }

    bool wait_io(Session& session, OVERLAPPED& operation, DWORD timeout = INFINITE) {
        const HANDLE waits[]{stop_event.get(), session.cancel.get(), operation.hEvent};
        const auto result = WaitForMultipleObjects(3, waits, FALSE, timeout);
        if (result == WAIT_OBJECT_0 + 2) return true;
        CancelIoEx(session.pipe.get(), &operation);
        DWORD ignored{};
        GetOverlappedResult(session.pipe.get(), &operation, &ignored, TRUE);
        return false;
    }

    void read_notifications(Session& session) {
        Handle complete(CreateEventW(nullptr, TRUE, FALSE, nullptr));
        if (!complete) { SetEvent(session.connected_event.get()); offline(); return; }
        OVERLAPPED operation{};
        operation.hEvent = complete.get();
        bool connected = ConnectNamedPipe(session.pipe.get(), &operation) != FALSE;
        if (!connected) {
            const auto error = GetLastError();
            if (error == ERROR_PIPE_CONNECTED) connected = true;
            else if (error == ERROR_IO_PENDING && wait_io(session, operation, connection_timeout_ms)) {
                DWORD ignored{};
                connected = GetOverlappedResult(session.pipe.get(), &operation, &ignored, FALSE) != FALSE;
            }
        }
        session.connected = connected;
        SetEvent(session.connected_event.get());
        if (!connected) { offline(); return; }

        std::string pending;
        std::array<char, 16384> buffer{};
        while (WaitForSingleObject(stop_event.get(), 0) != WAIT_OBJECT_0 &&
               WaitForSingleObject(session.cancel.get(), 0) != WAIT_OBJECT_0) {
            ResetEvent(complete.get());
            operation = {};
            operation.hEvent = complete.get();
            DWORD received{};
            bool read = ReadFile(session.pipe.get(), buffer.data(), static_cast<DWORD>(buffer.size()),
                                 &received, &operation) != FALSE;
            if (!read) {
                if (GetLastError() != ERROR_IO_PENDING || !wait_io(session, operation)) break;
                read = GetOverlappedResult(session.pipe.get(), &operation, &received, FALSE) != FALSE;
            }
            if (!read || !received) break;
            pending.append(buffer.data(), received);
            if (pending.size() > max_packet_bytes) break;
            std::size_t consumed = 0;
            for (;;) {
                const auto newline = pending.find('\n', consumed);
                if (newline == std::string::npos) break;
                const std::string_view packet(pending.data() + consumed, newline - consumed);
                if (!packet.empty()) publish(parse_komorebi_state(packet, monitor_index));
                consumed = newline + 1;
            }
            if (consumed) pending.erase(0, consumed);
        }
        session.connected = false;
        offline();
    }

    std::unique_ptr<Session> connect(const std::wstring& executable) {
        // One initial query; subsequent changes arrive through the subscription.
        // Publish before opening the stream so newer notifications cannot be
        // overwritten by an initial snapshot delivered out of order.
        const auto initial = run_command(executable, {L"state"}, stop_event.get());
        if (!initial.succeeded) { offline(); return {}; }
        auto initial_state = parse_komorebi_state(initial.output, monitor_index);
        if (!initial_state.connected) { offline(); return {}; }
        publish(std::move(initial_state));

        static std::atomic<unsigned int> sequence{};
        auto session = std::make_unique<Session>();
        session->pipe_name = L"CaelestiaShell-" + std::to_wstring(GetCurrentProcessId()) + L"-" +
                             std::to_wstring(GetTickCount64()) + L"-" + std::to_wstring(++sequence);
        session->pipe = create_user_pipe(session->pipe_name);
        if (!session->pipe || !session->cancel || !session->connected_event) { offline(); return {}; }
        auto* stream = session.get();
        session->reader = std::thread([this, stream] {
            try { read_notifications(*stream); }
            catch (...) { stream->connected = false; SetEvent(stream->connected_event.get()); offline(); }
        });

        // Official current CLI: subscribe-pipe; `subscribe` remains its legacy
        // alias. See docs/cli/subscribe-pipe.md and komorebic/src/main.rs in
        // https://github.com/LGUG2Z/komorebi . The receiver exists first.
        auto subscription = run_command(executable, {L"subscribe-pipe", session->pipe_name}, stop_event.get());
        session->unsubscribe_command = L"unsubscribe-pipe";
        if (!subscription.succeeded && WaitForSingleObject(stop_event.get(), 0) != WAIT_OBJECT_0) {
            subscription = run_command(executable, {L"subscribe", session->pipe_name}, stop_event.get());
            session->unsubscribe_command = L"unsubscribe";
        }
        const HANDLE waits[]{stop_event.get(), session->connected_event.get()};
        if (!subscription.succeeded ||
            WaitForMultipleObjects(2, waits, FALSE, connection_timeout_ms) != WAIT_OBJECT_0 + 1 ||
            !session->connected) {
            close_session(session, executable);
            offline();
            return {};
        }
        return session;
    }

    void close_session(std::unique_ptr<Session>& session, const std::wstring& executable) {
        if (!session) return;
        SetEvent(session->cancel.get());
        CancelIoEx(session->pipe.get(), nullptr);
        if (session->reader.joinable()) session->reader.join();
        // Release a daemon write blocked on a full pipe before asking its
        // command loop to unsubscribe. No unread stream is held during cleanup.
        DisconnectNamedPipe(session->pipe.get());
        session->pipe.reset();
        // Removing our own ephemeral subscription does not touch user config.
        run_command(executable, {session->unsubscribe_command, session->pipe_name},
                    stop_event.get(), 300, true);
        session.reset();
    }

    void run() {
        auto executable = executable_on_path();
        auto session = connect(executable);
        const HANDLE waits[]{stop_event.get(), work_event.get()};
        while (WaitForMultipleObjects(2, waits, FALSE, INFINITE) == WAIT_OBJECT_0 + 1) {
            bool reconnect = false;
            std::optional<int> focus;
            {
                std::lock_guard lock(mutex);
                reconnect = std::exchange(reconnect_requested, false);
                focus = std::exchange(focus_requested, std::nullopt);
            }
            if (reconnect) {
                close_session(session, executable);
                executable = executable_on_path();
                session = connect(executable);
            }
            bool can_focus = false;
            if (focus && session && session->connected) {
                std::lock_guard lock(mutex);
                can_focus = previous && previous->connected && *focus >= 0 &&
                            static_cast<std::size_t>(*focus) < previous->populated.size();
            }
            if (can_focus && !run_command(executable,
                    {L"focus-monitor-workspace", std::to_wstring(monitor_index), std::to_wstring(*focus)},
                    stop_event.get()).succeeded) {
                close_session(session, executable);
                offline();
            }
        }
        close_session(session, executable);
    }
};

WindowsServices::WindowsServices(HWND target, UINT update_message, int monitor_index)
    : impl_(std::make_unique<Impl>(target, update_message, monitor_index)) {}

WindowsServices::~WindowsServices() = default;

void WindowsServices::start() {
    std::lock_guard lock(impl_->mutex);
    if (impl_->started) return;
    impl_->worker = std::thread([implementation = impl_.get()] {
        try { implementation->run(); }
        catch (...) { implementation->offline(); }
    });
    impl_->started = true;
}

void WindowsServices::focus_workspace(int index) {
    if (index < 0 || index > 255) return;
    {
        std::lock_guard lock(impl_->mutex);
        impl_->focus_requested = index;
    }
    SetEvent(impl_->work_event.get());
}

void WindowsServices::reconnect() {
    {
        std::lock_guard lock(impl_->mutex);
        impl_->reconnect_requested = true;
        impl_->focus_requested.reset();
    }
    SetEvent(impl_->work_event.get());
}

std::optional<WorkspaceState> WindowsServices::take_update() {
    std::lock_guard lock(impl_->mutex);
    impl_->notification_pending = false;
    return std::exchange(impl_->latest, std::nullopt);
}

} // namespace caelestia
