#pragma once
#include "sampling.hpp"
#include "request_queue.hpp"
#include "profiles.hpp"
#include "tuning.hpp"
#include "config_store.hpp"
#include "memory_policy.hpp"
#include "ui.hpp"
#include "file_browser.hpp"
#include <algorithm>
#include <atomic>
#include <csignal>
#include <chrono>
#include <cpp-httplib/httplib.h>
#include <mutex>
#include <netinet/in.h>
#include <signal.h>
#include <spawn.h>
#include <sys/socket.h>
#include <sys/file.h>
#include <fcntl.h>
#include <sys/wait.h>
#include <thread>
extern char **environ;
namespace native_router {
namespace fs = std::filesystem;
inline bool model_lock_busy() {
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    const auto path = (runtime ? std::string(runtime) : "/tmp") +
        "/strata-native-model-" + std::to_string(getuid()) + ".lock";
    const int fd = open(path.c_str(), O_RDWR | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return false;
    const bool locked = flock(fd, LOCK_EX | LOCK_NB) != 0 &&
        (errno == EWOULDBLOCK || errno == EAGAIN);
    close(fd);
    return locked;
}
inline constexpr const char *external_busy_message =
    "Another model runner holds the GPU model lock. Native inference is unavailable until it releases the model; system memory counters include that runner.";
inline pid_t spawn(const std::vector<std::string> &args) {
    std::vector<char *> av;
    for (const auto &s : args)
        av.push_back(const_cast<char *>(s.c_str()));
    av.push_back(nullptr);
    posix_spawnattr_t attr;
    posix_spawnattr_init(&attr);
    posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETPGROUP);
    posix_spawnattr_setpgroup(&attr, 0);
    pid_t pid = -1;
    int e = posix_spawnp(&pid, av[0], nullptr, &attr, av.data(), environ);
    posix_spawnattr_destroy(&attr);
    if (e)
        throw std::runtime_error("Cannot start process: " + std::string(strerror(e)));
    return pid;
}
inline void command(const std::vector<std::string> &args) {
    pid_t p = spawn(args);
    int s;
    while (waitpid(p, &s, 0) < 0 && errno == EINTR) {
    }
}
inline int free_port() {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0)
        throw std::runtime_error("socket failed");
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(fd, reinterpret_cast<sockaddr *>(&a), sizeof a)) {
        close(fd);
        throw std::runtime_error("No worker port");
    }
    socklen_t n = sizeof a;
    getsockname(fd, reinterpret_cast<sockaddr *>(&a), &n);
    int port = ntohs(a.sin_port);
    close(fd);
    return port;
}
inline long long integer(const fs::path &p) {
    std::ifstream f(p);
    long long n = 0;
    f >> n;
    return n;
}
inline std::pair<double, long long> memory() {
    std::ifstream f("/proc/meminfo");
    std::string key, line;
    long long n = 0, available = 0;
    while (f >> key >> n) {
        std::getline(f, line);
        if (key == "MemAvailable:") {
            available = n * 1024;
            break;
        }
    }
    long long vram = -1;
    for (const auto &p : fs::directory_iterator("/sys/class/drm")) {
        auto d = p.path() / "device";
        auto total = integer(d / "mem_info_vram_total");
        if (total > (1LL << 30))
            vram = (total - integer(d / "mem_info_vram_used")) >> 20;
    }
    return {available / double(1LL << 30), vram};
}
inline double requested_ram_floor = 3;
inline long long requested_vram_floor = 512;
class Router {
  public:
    std::map<std::string, common_json> profiles, base_profiles;
    std::map<std::string, std::string> profile_errors;
    common_json overrides = common_json::object();
    fs::path tuning_file, worker_config, registry_path;
    std::mutex config_mutex;
    bool tuning_dirty = false;
    common_json active_metadata = common_json::object();
    std::map<std::string, fs::path> paths;
    std::string default_model, active, loading, error, unit;
    pid_t pid = -1;
    std::atomic<int> port{0};
    std::atomic<uint64_t> worker_budget_mib{0};
    std::mutex turn, state, lifecycle, clients_mutex, metrics_mutex;
    native_requests::Queue request_queue;
    bool queue_enabled=false;
    std::vector<std::weak_ptr<httplib::Client>> clients;
    std::atomic<bool> request_cancelled{false};
    common_json last_timings=common_json::object(),last_progress=common_json::object();
    std::chrono::steady_clock::time_point request_started{}, first_output{};
    long long observed_generated=0;
    void track(const std::shared_ptr<httplib::Client> &c) {
        std::lock_guard<std::mutex> lock(clients_mutex);clients.erase(std::remove_if(clients.begin(),clients.end(),[](auto &w){return w.expired();}),clients.end());clients.push_back(c);
        std::lock_guard<std::mutex> metrics(metrics_mutex);request_cancelled=false;last_timings=common_json::object();last_progress=common_json::object();request_started=std::chrono::steady_clock::now();first_output={};observed_generated=0;
    }
    std::string connection_failure(const char *fallback) {
        // The socket can close just before the supervisor exits. Give the guard
        // one sampling interval to publish its exit reason; never retry inference.
        for(int attempt=0;attempt<13;++attempt) {
            if(request_cancelled.load())return "Request cancelled";
            {std::lock_guard<std::mutex> lock(state);if(!error.empty())return error;}
            {std::lock_guard<std::mutex> lock(lifecycle);if(pid<=0)break;}
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
        {std::lock_guard<std::mutex> lock(state);if(!error.empty())return error;}
        return fallback;
    }
    void observe(const common_json &answer) {
        std::lock_guard<std::mutex> lock(metrics_mutex);
        if(answer.contains("prompt_progress")&&answer["prompt_progress"].is_object())last_progress=answer["prompt_progress"];
        if(answer.contains("timings")&&answer["timings"].is_object())last_timings=answer["timings"];
        if(first_output==std::chrono::steady_clock::time_point{}&&answer.contains("choices"))
            for(const auto &choice:answer["choices"])if(choice.contains("delta"))for(const char *field:{"content","reasoning_content"})if(choice["delta"].contains(field)&&choice["delta"][field].is_string()&&!choice["delta"][field].template get<std::string>().empty())first_output=std::chrono::steady_clock::now();
    }
    void cancel_clients() {request_cancelled=true;std::lock_guard<std::mutex> lock(clients_mutex);for(auto &weak:clients)if(auto c=weak.lock())c->stop();}
    bool llama_active() {std::lock_guard<std::mutex> lock(state);return !active.empty()&&active_metadata.value("inference",common_json::object()).value("engine","")=="llama";}

    std::atomic<bool> closed{false};
    std::thread guard;
    double ram_floor = requested_ram_floor;
    long long vram_floor = requested_vram_floor;
    explicit Router(const fs::path &registry) {
        registry_path = fs::absolute(registry);
        auto r = native_profiles::read(registry);
        queue_enabled=r.value("queue_requests",false);
        auto base = fs::absolute(registry).parent_path();
        for (auto it = r.at("profiles").begin(); it != r["profiles"].end(); ++it) {
            fs::path p = native_profiles::path(it.value().get<std::string>(), base);
            paths[it.key()] = p;
            profiles[it.key()] = native_profiles::load(p);
            auto &cfg = profiles[it.key()];
            const auto args = cfg.at("args").get<std::vector<std::string>>();
            const auto gpu = native_memory::snapshot().gpu_total;
            if (cfg.value("backend", "") == "hip" && gpu >= 12 * native_memory::GiB &&
                gpu <= 20 * native_memory::GiB && !native_profiles::option(args, "--pack").empty()) {
                const auto reserve = native_profiles::option(args, "--vram-reserve-mib", "0");
                if (std::stoll(reserve) < 4096) native_tuning::argument(cfg, "--vram-reserve-mib", "4096");
            }
            native_profiles::metadata(it.key(), cfg);
        }
        base_profiles = profiles;
        tuning_file = base / ("native-tuning-" + registry.stem().string() + ".json");
        if (fs::exists(tuning_file)) {
            try {
                auto saved = native_profiles::read(tuning_file);
                overrides = saved.at("profiles");
                if (!overrides.is_object()) throw std::runtime_error("Profiles must be an object");
                for (auto it=overrides.begin();it!=overrides.end();++it) {
                    if (!profiles.count(it.key())) continue;
                    try { profiles[it.key()] = native_tuning::apply(base_profiles.at(it.key()), it.value()); }
                    catch(const std::exception &e) {
                        profile_errors[it.key()] = std::string("Saved tuning cannot be applied: ") + e.what();
                        std::fprintf(stderr,"native tuning: %s: %s\n",it.key().c_str(),e.what());
                    }
                }
            } catch(const std::exception &e) {
                overrides = common_json::object();
                std::fprintf(stderr,"native tuning: cannot read saved overrides: %s\n",e.what());
            }
        }
        if (profiles.empty())
            throw std::runtime_error("No model profiles configured");
        default_model = r.value("default", profiles.begin()->first);
        if (!profiles.count(default_model))
            throw std::runtime_error("Unknown default model");
        unit = "strata-native-worker-" + std::to_string(getpid());
        guard = std::thread([this] {
            while (!closed.load()) {
                try {
                    auto m = memory();
                    bool running;
                    {
                        std::lock_guard<std::mutex> l(lifecycle);
                        running = pid > 0;
                        if (running) {
                            int st=0;
                            auto result = waitpid(pid, &st, WNOHANG);
                            if (result == pid || (result < 0 && errno == ECHILD)) {
                                pid = -1;
                                worker_budget_mib = 0;
                                running = false;
                                std::lock_guard<std::mutex> s(state);
                                active.clear();
                                if (error.empty())
                                    error = WIFEXITED(st)&&WEXITSTATUS(st)==75?"Backend stopped to preserve system memory headroom; release other applications or lower memory settings":"Model worker exited; load again to restart";
                            }
                        }
                    }
                    if (running && (m.first < ram_floor || (m.second >= 0 && m.second < vram_floor))) {
                        {
                            std::lock_guard<std::mutex> l(state);
                            error = "Worker stopped by physical RAM/VRAM floor: RAM " +
                                    std::to_string(m.first) + " GiB, VRAM " + std::to_string(m.second) + " MiB";
                            std::fprintf(stderr, "native memory monitor: %s (floors %.1f GiB / %lld MiB)\n",
                                         error.c_str(), ram_floor, vram_floor);
                        }
                        stop();
                    }
                } catch (const std::exception &e) {
                    std::fprintf(stderr, "native memory monitor: %s\n", e.what());
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(500));
            }
        });
    }
    ~Router() {
        closed = true;
        stop();
        if (guard.joinable())
            guard.join();
    }
    common_json status() {
        std::lock_guard<std::mutex> l(state);
        const bool external_busy = active.empty() && loading.empty() && model_lock_busy();
        if (!external_busy && error == external_busy_message) error.clear();
        common_json names = common_json::array();
        for (auto &p : profiles)
            names.push_back(p.first);
        common_json result={{"active", active.empty() ? common_json(nullptr) : common_json(active)},
                {"loading", loading.empty() ? common_json(nullptr) : common_json(loading)},
                {"error", error.empty() ? common_json(nullptr) : common_json(error)},
                {"default", default_model},
                {"profiles", names},
                {"loaded", !active.empty()}, {"reload_required", tuning_dirty},
                {"external_model_busy", external_busy},
                {"profile", active.empty() ? common_json(nullptr) : active_metadata},
                {"runtime", "native-c++"},
                {"memory_policy", {{"worker_limit_mib", worker_budget_mib.load()},
                    {"available_ram_floor_gib", ram_floor}, {"physical_vram_floor_mib", vram_floor},
                    {"admission_ram_floor_gib", ram_floor + 1},
                    {"admission_vram_floor_mib", vram_floor + 256}, {"scope_swap_mib", 0}}}};
        if(queue_enabled){auto q=request_queue.state();result["request_queue"]={{"waiting",q.waiting},{"estimated_bytes",q.bytes},{"max_requests",native_requests::Queue::max_requests}};}
        return result;
    }
    void stop() {
        std::lock_guard<std::mutex> l(lifecycle);
        if (pid > 0) {
            command({"systemctl", "--user", "stop", unit + ".scope"});
            kill(-pid, SIGTERM);
            int status;
            bool done = false;
            for (int i = 0; i < 100; i++) {
                auto r = waitpid(pid, &status, WNOHANG);
                if (r == pid || r < 0) {
                    done = true;
                    break;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
            }
            if (!done) {
                kill(-pid, SIGKILL);
                waitpid(pid, &status, 0);
            }
            pid = -1;
        }
        if (!worker_config.empty()) { std::error_code ec; fs::remove(worker_config, ec); worker_config.clear(); }
        std::lock_guard<std::mutex> s(state);
        active.clear();
        {std::lock_guard<std::mutex> metrics(metrics_mutex);last_timings=common_json::object();last_progress=common_json::object();request_started=std::chrono::steady_clock::now();first_output={};observed_generated=0;request_cancelled=false;}
        tuning_dirty = false;
        worker_budget_mib = 0;
    }
    std::shared_ptr<httplib::Client> client() {
        auto c = std::make_shared<httplib::Client>("127.0.0.1", port);
        if (const char *key = getenv("STRATA_API_KEY"))
            c->set_default_headers({{"Authorization", std::string("Bearer ") + key}});
        c->set_connection_timeout(1);
        c->set_read_timeout(3600);
        c->set_write_timeout(600);
        return c;
    }
    void load(const std::string &name, bool apply_pending = false) {
        if (closed)
            throw std::runtime_error("Router shutting down");
        common_json cfg;
        {
            std::lock_guard<std::mutex> lock(config_mutex);
            if (!profiles.count(name)) throw std::runtime_error("Unknown model: " + name);
            if (profile_errors.count(name)) throw std::runtime_error(profile_errors.at(name));
            cfg = profiles.at(name);
        }
        auto r = cfg.value("router", common_json::object());
        if (!r.value("enabled", true))
            throw std::runtime_error("Model profile disabled");
        {
            std::lock_guard<std::mutex> s(state);
            if (active == name && (!tuning_dirty || !apply_pending))
                return;
            loading = name;
            error.clear();
        }
        try {
            if (model_lock_busy()) {
                std::lock_guard<std::mutex> s(state);
                if (active.empty()) throw std::runtime_error(external_busy_message);
            }
            const auto admission = native_memory::refusal(native_memory::snapshot(),
                static_cast<uint64_t>((ram_floor + 1) * native_memory::GiB),
                static_cast<uint64_t>(vram_floor + 256) * native_memory::MiB);
            if (!admission.empty()) throw std::runtime_error(admission);
            stop();
            int limit = r.value("memory_max_gib", 20);
            if (limit < 2 || limit > 512)
                throw std::runtime_error("Invalid memory limit");
            const auto free_memory = native_memory::snapshot();
            const uint64_t keep = static_cast<uint64_t>((ram_floor + 1) * native_memory::GiB);
            if (free_memory.available <= keep + 2 * native_memory::GiB)
                throw std::runtime_error("Insufficient available RAM for a bounded model worker");
            const uint64_t budget_mib = std::min<uint64_t>(static_cast<uint64_t>(limit) * 1024,
                (free_memory.available - keep) / native_memory::MiB);
            const auto engine_args = cfg.at("args").get<std::vector<std::string>>();
            const auto resident_arg = native_profiles::option(engine_args, "--resident-budget-gib");
            if (!native_tuning::dense(cfg) && !resident_arg.empty() && resident_arg != "auto") {
                const double resident_gib = std::stod(resident_arg);
                if (resident_gib > 0 && (resident_gib + 2) * 1024 > budget_mib)
                    throw std::runtime_error("Resident expert cache plus engine reserve exceeds the worker RAM budget; reduce the RAM cache setting");
            }
            worker_budget_mib = budget_mib;
            port = free_port();
            {
                std::lock_guard<std::mutex> l(lifecycle);
                worker_config = native_config::temporary(cfg, fs::temp_directory_path());
                std::vector<std::string> cmd={"systemd-run", "--user", "--scope", "--collect", "--quiet", "--unit=" + unit};
                const auto memory_args = native_memory::worker_scope_memory_args(budget_mib);
                cmd.insert(cmd.end(), memory_args.begin(), memory_args.end());
                if(native_backend::resolve(cfg)["engine"]=="llama") {
                    cmd.insert(cmd.end(),{(native_profiles::executable_dir()/"strata-native").string(),"--llama-worker",std::to_string(getpid()),std::to_string((uint64_t)((ram_floor+1)*1024)),std::to_string(vram_floor+256)});
                    auto backend=native_backend::command(cfg,name,port,native_profiles::executable_dir());cmd.insert(cmd.end(),backend.begin(),backend.end());
                } else cmd.insert(cmd.end(),{(native_profiles::executable_dir()/"strata-native").string(),"--config",worker_config.string(),"--model-id",name,"--port",std::to_string(port),"--memory-floor-gib",std::to_string(ram_floor),"--vram-floor-mib",std::to_string(vram_floor)});
                pid=spawn(cmd);
            }
            auto c = client();
            c->set_read_timeout(1);
            for (int i = 0; i < 3600 && !closed; i++) {
                {
                    std::lock_guard<std::mutex> l(lifecycle);
                    int st=0;
                    if (pid < 0 || waitpid(pid, &st, WNOHANG) != 0)
                        throw std::runtime_error("Model worker exited while loading; see terminal log");
                }
                auto h = c->Get("/health");
                if (h && h->status == 200) {
                    std::lock_guard<std::mutex> l(lifecycle);
                    if (pid < 0)
                        throw std::runtime_error("Model worker stopped during startup");
                    std::lock_guard<std::mutex> s(state);
                    active = name;
                    active_metadata = native_profiles::metadata(name, cfg);
                    const auto ready = common_json::parse_no_throw(h->body);
                    const auto actual_ctx = ready.value("max_context", active_metadata.at("context_length").template get<long long>());
                    active_metadata["context_length"] = actual_ctx;
                    active_metadata["max_output_tokens"] = actual_ctx - 8;
                    active_metadata["meta"]["n_ctx"] = actual_ctx;
                    active_metadata["meta"]["max_output_tokens"] = actual_ctx - 8;
                    tuning_dirty = false;
                    loading.clear();
                    return;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(200));
            }
            throw std::runtime_error("Model worker startup timed out");
        } catch (const std::exception &e) {
            stop();
            std::lock_guard<std::mutex> s(state);
            loading.clear();
            if (error.empty())
                error = e.what();
            throw std::runtime_error(error);
        }
    }
    common_json tuning(const std::string &name) {
        std::lock_guard<std::mutex> lock(config_mutex);
        if (!profiles.count(name)) throw std::runtime_error("Unknown model: " + name);
        return {{"model", name}, {"inference",native_backend::resolve(profiles.at(name))}, {"dense", native_tuning::dense(profiles.at(name))},
                {"values", native_tuning::values(profiles.at(name))},
                {"files", native_tuning::files(profiles.at(name))}, {"registry", registry_path.string()},
                {"saved", overrides.value(name, common_json::object())},
                {"override_file", tuning_file.string()}, {"vision", profiles.at(name).contains("vision")},
                {"warning", profile_errors.count(name) ? profile_errors.at(name) : ""}};
    }
    void save_tuning(const std::string &name, const common_json &settings, bool reset) {
        {
            std::lock_guard<std::mutex> lock(config_mutex);
            if (!profiles.count(name)) throw std::runtime_error("Unknown model: " + name);
            if (!settings.is_object()) throw std::runtime_error("Tuning settings must be an object");
            auto merged = overrides.value(name, common_json::object());
            if (reset) merged = common_json::object();
            else for(auto it=settings.begin();it!=settings.end();++it) merged[it.key()] = it.value();
            auto candidate = native_tuning::apply(base_profiles.at(name), merged);
            auto next = overrides;
            next[name] = merged;
            native_config::save({{"version", 1}, {"profiles", next}}, tuning_file);
            overrides = next; profiles[name] = candidate; profile_errors.erase(name);
        }
        std::lock_guard<std::mutex> lock(state);
        if (active == name) tuning_dirty = true;
    }

};
inline void json(httplib::Response &res, int code, const common_json &body) {
    res.status = code;
    res.set_content(body.dump_safe(), "application/json");
}
inline std::string pick(Router &r, const common_json &body) {
    if (body.contains("model") && body["model"].is_string() && body["model"] != "strata")
        return body["model"].get<std::string>();
    std::lock_guard<std::mutex> s(r.state);
    return r.active.empty() ? r.default_model : r.active;
}
inline volatile std::sig_atomic_t shutdown_requested = 0;
inline void install_security(httplib::Server &http, bool remote = false) {
    http.set_pre_routing_handler([remote](const httplib::Request &req, httplib::Response &res) {
        const auto host = req.get_header_value("Host");
        bool local = false;
        for (const std::string allowed : {"127.0.0.1", "localhost", "[::1]"}) {
            if (host == allowed) local = true;
            if (host.rfind(allowed + ":", 0) == 0) {
                auto port = host.substr(allowed.size() + 1);
                local = !port.empty() && std::all_of(port.begin(), port.end(), [](unsigned char c) { return c >= '0' && c <= '9'; });
            }
        }
        if (!local && !remote) {
            json(res, 403, {{"error", {{"message", "Loopback Host header required"}}}});
            return httplib::Server::HandlerResponse::Handled;
        }
        if (req.has_header("Origin") &&
            req.get_header_value("Origin") != "http://" + req.get_header_value("Host")) {
            json(res, 403, {{"error", {{"message", "Foreign browser origin rejected"}}}});
            return httplib::Server::HandlerResponse::Handled;
        }
        if (const char *key = getenv("STRATA_API_KEY"))
            if (!(req.method == "GET" && req.path == "/") && *key && req.get_header_value("Authorization") != std::string("Bearer ") + key) {
                json(res, 401, {{"error", {{"message", "API key required"}}}});
                return httplib::Server::HandlerResponse::Handled;
            }
        return httplib::Server::HandlerResponse::Unhandled;
    });
}
inline void proxy_request(Router &router,const httplib::Request &req,httplib::Response &res) {
        const auto admission = native_memory::refusal(native_memory::snapshot(),
            static_cast<uint64_t>((router.ram_floor + 1) * native_memory::GiB),
            static_cast<uint64_t>(router.vram_floor + 256) * native_memory::MiB,
            static_cast<uint64_t>(req.body.size()) * 8);
        if (!admission.empty()) {
            json(res, 503, {{"error", {{"message", admission}, {"type", "resource_exhausted"}}}});
            return;
        }
        std::shared_ptr<native_requests::Queue::Ticket> ticket;
        std::shared_ptr<std::unique_lock<std::mutex>> turn_lock;
        if(!router.queue_enabled) {
            turn_lock=std::make_shared<std::unique_lock<std::mutex>>(router.turn,std::try_to_lock);
            if(!turn_lock->owns_lock()){res.set_header("Retry-After","1");json(res,429,{{"error",{{"message","Model is busy; retry after the current request"},{"type","server_busy"}}}});return;}
        }
        auto body = common_json::parse_no_throw(req.body);
        if (!body.is_object()) {
            json(res, 400, {{"error", {{"message", "JSON object required"}}}});
            return;
        }
        std::function<bool(const common_json &)> remote_image=[&](const common_json &value) {
            if(value.is_object()) {
                const auto type=value.contains("type")&&value["type"].is_string()?value["type"].template get<std::string>():std::string();
                if(type=="image"&&value.contains("source")&&value["source"].is_object()&&value["source"].value("type",std::string())=="url")return true;
                if((type=="image_url"||type=="input_image")&&value.contains("image_url")) {auto u=value["image_url"];auto url=u.is_string()?u.template get<std::string>():u.is_object()?u.value("url",std::string()):"";if(url.rfind("data:image/",0)!=0)return true;}
                for(auto it=value.begin();it!=value.end();++it)if(remote_image(it.value()))return true;
            }else if(value.is_array())for(const auto &item:value)if(remote_image(item))return true;
            return false;
        };
        if(remote_image(body)){json(res,400,{{"error",{{"message","Use inline base64 screenshots; remote image fetching is disabled"}}}});return;}
        auto name = pick(router, body);
        try {
            std::lock_guard<std::mutex> lock(router.config_mutex);
            body = native_sampling::apply(router.profiles.at(name), body);
        } catch (const std::exception &e) {
            json(res,400,{{"error",{{"message",e.what()}}}});return;
        }
        const auto body_text = body.dump_safe();
        if(router.queue_enabled) {
            ticket=router.request_queue.admit(static_cast<uint64_t>(req.body.size())*8);
            if(!ticket){res.set_header("Retry-After","3");json(res,429,{{"error",{{"message","Request queue is full; retry shortly"},{"type","server_busy"}}}});return;}
            turn_lock=std::make_shared<std::unique_lock<std::mutex>>(router.turn,std::defer_lock);
        }
        bool stream = body.value("stream", false);
        if (!stream) {
            try {
                if(ticket&&!router.request_queue.acquire(*ticket,*turn_lock,[&]{return !shutdown_requested&&!req.is_connection_closed();})) {
                    res.set_header("Retry-After","3");json(res,429,{{"error",{{"message","Request queue wait expired"},{"type","server_busy"}}}});return;
                }
                const auto check=native_memory::refusal(native_memory::snapshot(),static_cast<uint64_t>((router.ram_floor+1)*native_memory::GiB),static_cast<uint64_t>(router.vram_floor+256)*native_memory::MiB);
                if(ticket&&!check.empty())throw std::runtime_error(check);
                router.load(name);
                auto c = router.client();router.track(c);
                auto answer = c->Post(req.path, body_text, "application/json");
                if (!answer)
                    throw std::runtime_error(router.connection_failure("Worker connection failed"));
                router.observe(common_json::parse_no_throw(answer->body));
                res.status = answer->status;
                res.set_content(answer->body, answer->get_header_value("Content-Type"));
            } catch (const std::exception &e) {
                json(res, 503, {{"error", {{"message", e.what()}}}});
            }
            return;
        }
        res.set_header("Cache-Control", "no-cache");
        res.set_chunked_content_provider("text/event-stream", [&, turn_lock, ticket, name, path = req.path, body = body_text](
                                                                  size_t, httplib::DataSink &sink) {
            try {
                auto heartbeat=std::chrono::steady_clock::time_point{};
                if(ticket&&!router.request_queue.acquire(*ticket,*turn_lock,[&]{
                    if(shutdown_requested||!sink.is_writable())return false;
                    auto now=std::chrono::steady_clock::now();
                    if(now-heartbeat>=std::chrono::seconds(2)){heartbeat=now;return sink.write(": waiting for model\n\n",21);}
                    return true;
                }))throw std::runtime_error("Request queue wait expired or client disconnected");
                const auto check=native_memory::refusal(native_memory::snapshot(),static_cast<uint64_t>((router.ram_floor+1)*native_memory::GiB),static_cast<uint64_t>(router.vram_floor+256)*native_memory::MiB);
                if(ticket&&!check.empty())throw std::runtime_error(check);
                router.load(name);
                auto c = router.client();router.track(c);std::string event_buffer;
                auto answer = c->Post(path, httplib::Headers{}, body, "application/json",
                                      [&](const char *data, size_t n) {
                    event_buffer.append(data,n);size_t end;
                    while((end=event_buffer.find('\n'))!=std::string::npos){auto line=event_buffer.substr(0,end);event_buffer.erase(0,end+1);if(line.rfind("data: ",0)==0)router.observe(common_json::parse_no_throw(line.substr(6)));}
                    if(event_buffer.size()>1024*1024)event_buffer.clear();
                    return sink.is_writable()&&sink.write(data,n);
                });
                if (!answer)
                    throw std::runtime_error(router.connection_failure("Worker stream disconnected"));
            } catch (const std::exception &e) {
                auto s = "data: " + common_json({{"error", {{"message", e.what()}}}}).dump_safe() + "\n\n";
                sink.write(s.data(), s.size());
            }
            sink.done();
            return true;
        });
}
inline int run(const std::string &registry, int port, const std::string &host) {
    if (host != "127.0.0.1" && host != "::1" && host != "localhost")
        { const char *key=getenv("STRATA_API_KEY");
          if(!key || !*key)throw std::runtime_error("Non-loopback listening requires --api-key or STRATA_API_KEY"); }
    Router router(registry);
    httplib::Server http;
    shutdown_requested = 0;
    http.new_task_queue = [&] { return new httplib::ThreadPool(4, router.queue_enabled?8:4, 8); };
    http.set_payload_max_length(32 * 1024 * 1024);
    http.set_read_timeout(600);
    http.set_write_timeout(3600);
    install_security(http, host != "127.0.0.1" && host != "::1" && host != "localhost");
    http.Get("/", [](auto &, auto &res) { res.set_content(native_ui, "text/html; charset=utf-8"); });
    http.Get("/router/status", [&](auto &, auto &res) { json(res, 200, router.status()); });
    http.Get("/health", [&](auto &, auto &res) {
        auto s = router.status();
        s["status"] = "ok";
        json(res, 200, s);
    });
    http.Get("/v1/models", [&](auto &, auto &res) {
        common_json data = common_json::array();
        auto status = router.status();
        std::lock_guard<std::mutex> lock(router.config_mutex);
        for (auto &p : router.profiles) {
            auto m = native_profiles::metadata(p.first, p.second);
            const bool loaded = status["active"] == p.first;
            if (loaded) {
                auto configured = m; m = status.at("profile");
                if (status.value("reload_required", false)) m["pending_configuration"] = configured;
            }
            m["status"] = {{"loaded", loaded}, {"reload_required", loaded && status.value("reload_required", false)}};
            m["local_files"]["profile_config"] = router.paths.at(p.first).string();
            data.push_back(m);
        }
        json(res, 200, {{"object", "list"}, {"data", data}});
    });
    http.Get("/router/files", [](const auto &req, auto &res) {
        try {
            const auto kind = req.get_param_value("kind");
            if (kind != "gguf" && kind != "directory") throw std::runtime_error("Unknown file picker type");
            json(res, 200, native_files::list(req.get_param_value("path"), kind == "directory"));
        } catch (const std::exception &e) { json(res, 400, {{"error", {{"message", e.what()}}}}); }
    });
    http.Get("/router/tuning", [&](const auto &req, auto &res) {
        try { json(res, 200, router.tuning(req.get_param_value("model"))); }
        catch(const std::exception &e) { json(res, 400, {{"error", {{"message", e.what()}}}}); }
    });
    http.Post("/router/tuning", [&](const auto &req, auto &res) {
        std::unique_lock<std::mutex> lock(router.turn, std::try_to_lock);
        if (!lock.owns_lock()) { json(res, 409, {{"error", {{"message", "Finish or cancel inference before tuning"}}}}); return; }
        try {
            auto body = common_json::parse_no_throw(req.body);
            auto name = body.at("model").template get<std::string>();
            router.save_tuning(name, body.value("settings", common_json::object()), body.value("reset", false));
            if (body.value("reload", false)) router.load(name, true);
            auto result = router.tuning(name); result["status"] = router.status();
            json(res, 200, result);
        } catch(const std::exception &e) { json(res, 400, {{"error", {{"message", e.what()}}}}); }
    });
    http.Post("/router/load", [&](const auto &req, auto &res) {
        try {
            auto b = common_json::parse_no_throw(req.body);
            std::lock_guard<std::mutex> l(router.turn);
            auto name=b.at("model").template get<std::string>();common_json settings=common_json::object();
            for(const char *key:{"engine_policy","compute_backend"})if(b.contains(key))settings[key]=b[key];
            if(!settings.empty())router.save_tuning(name,settings,false);
            router.load(name, true);
            json(res, 200, router.status());
        } catch (const std::exception &e) {
            json(res, 503, {{"error", {{"message", e.what()}}}});
        }
    });
    http.Post("/router/cancel", [&](auto &, auto &res) {
        auto status = router.status();
        if (!status.at("loaded").template get<bool>()) {
            json(res, 200, {{"cancel_requested", false}}); return;
        }
        if(router.llama_active()){router.cancel_clients();json(res,200,{{"cancel_requested",true}});return;}
        auto c = router.client(); c->set_read_timeout(2);
        auto answer = c->Post("/cancel", "{}", "application/json");
        if (!answer) { json(res, 503, {{"error", {{"message", "Worker cancellation failed"}}}}); return; }
        res.status = answer->status; res.set_content(answer->body, "application/json");
    });
    http.Post("/router/unload", [&](auto &, auto &res) {
        std::lock_guard<std::mutex> l(router.turn);
        router.stop();
        json(res, 200, router.status());
    });
    auto proxy = [&](const auto &req,auto &res){proxy_request(router,req,res);};
    for (const char *path :
         {"/v1/chat/completions", "/v1/messages", "/v1/messages/count_tokens", "/v1/responses"})
        http.Post(path, proxy);
    auto worker_status = [&](const auto &, auto &res) {
        auto s = router.status();
        if (s.at("loaded").template get<bool>()) {
            try {
                auto c = router.client();
                c->set_read_timeout(2);
                auto h = c->Get("/health");
                if (h && h->status == 200) {
                    auto m = common_json::parse_no_throw(h->body);
                    for (auto it = m.begin(); it != m.end(); ++it)
                        s[it.key()] = it.value();
                }
            } catch (...) {
            }
        }
        auto m = native_memory::snapshot();
        s["resources"] = {{"ram_total_bytes", m.total}, {"ram_available_bytes", m.available},
            {"swap_total_bytes", m.swap_total}, {"swap_used_bytes", m.swap_total - m.swap_free},
            {"vram_total_bytes", m.gpu_total}, {"vram_used_bytes", m.gpu_used},
            {"vram_free_bytes", m.vram_free}, {"gpu_busy_percent", m.gpu_busy},
            {"gpu_temperature_c", m.gpu_temperature_millic / 1000.0},
            {"gtt_total_bytes",m.gtt_total},{"gtt_used_bytes",m.gtt_used},{"gtt_free_bytes",m.gtt_free},
            {"cpu_total_ticks", m.cpu_total}, {"cpu_idle_ticks", m.cpu_idle}};
        {
            std::lock_guard<std::mutex> lock(router.lifecycle);
            if (router.pid > 0) {
                auto worker = native_memory::snapshot(std::to_string(router.pid));
                s["resources"]["worker_cgroup_bytes"] = worker.cgroup_used;
            }
        }
        if(router.llama_active()) {
            s["engine"]="llama.cpp";s["max_context"]=s["profile"]["context_length"];
            try {
                auto c=router.client();c->set_read_timeout(1);auto answer=c->Get("/slots");
                if(answer&&answer->status==200) {
                    auto slots=common_json::parse_no_throw(answer->body);
                    if(slots.is_array()&&!slots.empty()) {
                        auto slot=slots[0];const bool processing=slot.value("is_processing",false);
                        long long generated=0;if(slot.contains("next_token")&&slot["next_token"].is_array()&&!slot["next_token"].empty())generated=slot["next_token"][0].value("n_decoded",0LL);
                        std::lock_guard<std::mutex> lock(router.metrics_mutex);auto now=std::chrono::steady_clock::now();
                        if(generated>0&&router.first_output==std::chrono::steady_clock::time_point{}){router.first_output=now;router.observed_generated=generated;}
                        const double elapsed=std::max(.001,std::chrono::duration<double>(now-router.request_started).count());
                        const double pp=router.first_output==std::chrono::steady_clock::time_point{}?elapsed:std::max(.001,std::chrono::duration<double>(router.first_output-router.request_started).count());
                        const auto read=slot.value("n_prompt_tokens_processed",0LL);const auto cached=slot.value("n_prompt_tokens_cache",0LL);const auto total=slot.value("n_prompt_tokens",0LL);
                        s["live"]={{"state",processing?(generated>0?"generating":"reading"):"idle"},{"prompt_total",total},{"prefill_total",std::max(0LL,total-cached)},{"prompt_read",read},{"cached_tokens",cached},{"generated",generated},{"position",total},{"prompt_total_known",!processing},{"prefill_tok_s_mean",read/pp},{"decode_tok_s_mean",std::max(0LL,generated-router.observed_generated)/std::max(.001,elapsed-pp)},{"rates_estimated",processing||router.last_timings.empty()},{"allocated_context",slot.value("n_ctx",0LL)},{"cancelled",router.request_cancelled.load()}};
                        if(processing&&!router.last_progress.empty()) {
                            auto &l=s["live"];auto &p=router.last_progress;
                            l["prompt_total"]=p.value("total",total);l["cached_tokens"]=p.value("cache",cached);
                            l["prefill_total"]=p.value("total",total)-p.value("cache",cached);
                            l["prompt_read"]=p.value("processed",read);l["prompt_total_known"]=true;
                            if(p.value("time_ms",0.0)>0)l["prefill_tok_s_mean"]=p.value("processed",read)*1000.0/p.value("time_ms",1.0);
                        }
                        if(!processing&&!router.last_timings.empty()) {
                            auto &l=s["live"];auto &t=router.last_timings;
                            l["prefill_tok_s_mean"]=t.value("prompt_per_second",0.0);l["decode_tok_s_mean"]=t.value("predicted_per_second",0.0);
                            l["generated"]=t.value("predicted_n",generated);l["prompt_read"]=t.value("prompt_n",read);l["prefill_total"]=t.value("prompt_n",read);l["prompt_total"]=t.value("prompt_n",read)+cached;l["rates_estimated"]=false;
                        }
                        s["tiers_error"]="llama.cpp owns layer placement; native expert-cache counters do not apply";
                    }
                }
            }catch(const std::exception &e){s["monitor_error"]=e.what();}
        }
        if (s["active"].is_string()) {
            auto name = s["active"].template get<std::string>();
            std::lock_guard<std::mutex> lock(router.config_mutex);
            s["configured_profile"] = native_profiles::metadata(name, router.profiles.at(name));
        }
        json(res, 200, s);
    };
    http.Get("/v1/status", worker_status);
    http.Get("/metrics", worker_status);
    http.Get("/props", worker_status);
    auto previous_int = std::signal(SIGINT, [](int) { shutdown_requested = 1; });
    auto previous_term = std::signal(SIGTERM, [](int) { shutdown_requested = 1; });
    std::atomic<bool> finished{false};
    std::thread shutdown_monitor([&] {
        while (!finished) {
            if (shutdown_requested) {
                router.closed = true;
                router.stop();
                http.stop();
                return;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    });
    std::fprintf(stderr, "Strata native router: http://%s:%d/ — %zu profiles, local-only runtime\n",
                 host.c_str(), port, router.profiles.size());
    bool ok = http.listen(host, port);
    finished = true;
    shutdown_monitor.join();
    std::signal(SIGINT, previous_int);
    std::signal(SIGTERM, previous_term);
    return ok ? 0 : 1;
}
} // namespace native_router
