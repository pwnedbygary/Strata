// frontend/main.cpp - UnbiasedStrata's front end: tokenizer, chat template and an OpenAI-style HTTP endpoint
// in front of the unmodified Strata engine.
//
// One binary, two roles.  Started normally it is the front end: it starts a copy of itself with `--engine`,
// which runs the engine's own program (frontend/engine_entry.cpp) in serve mode, and talks to it over a pipe
// in the engine's line protocol (token ids in, token ids out).  That is the process model upstream's Python
// server uses, so the engine runs exactly as upstream tested it.
//
// The tokenizer and the chat template come from llama.cpp (the pinned submodule): the GGUF's own vocabulary
// and its own Jinja template.  Nothing here opens an outgoing connection.
#include "adapters.hpp"
#include "chat.h"
#include "common.h"
#include "engine.hpp"
#include "llama.h"
#include "profiles.hpp"
#include "router.hpp"
#include "backend_worker.hpp"
#include "vision.hpp"
#include <filesystem>
#include <fstream>

#include <cpp-httplib/httplib.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <vector>

#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

int strata_engine_main(int argc, char **argv);

namespace {

// the model id reported on /v1/models and in every completion: the GGUF's base name
// (`Qwen3.6-35B-A3B-UD-IQ3_XXS`, `Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS` for shard 1 without its
// `-00001-of-00002`), set once the options are parsed
std::string g_model_name = "strata-native";
std::string model_name_of(const std::string &path) {
    std::string b = path.substr(path.find_last_of('/') == std::string::npos ? 0 : path.find_last_of('/') + 1);
    if (b.size() > 5 && b.compare(b.size() - 5, 5, ".gguf") == 0)
        b.resize(b.size() - 5);
    const size_t at = b.rfind("-00001-of-");
    if (at != std::string::npos)
        b.resize(at);
    return b.empty() ? std::string("strata-native") : b;
}

struct Options {
    bool open_browser = false;
    std::string api_key;
    std::string model_id;
    std::string config;
    std::string registry;
    std::string model; // shard 1 of the GGUF
    std::string pack;  // the prepared pack directory
    std::string mtp;   // the prepared draft-head directory
    std::string mmproj;
    int vision_tokens = 1024;
    std::string host = "127.0.0.1";
    int port = 8080;
    long long ctx = 32768;
    int threads = 0;                // CPU expert workers; 0 = the engine's default (every physical core)
    long long vram_cap_mib = 0;     // --vram-cap: the engine limits itself to a smaller card's VRAM
    double ram_cap_gib = 0.0;       // --ram-cap: bounds the engine's RAM expert tier and pinned arena
    std::vector<std::string> extra; // after `--`: passed to the engine as they are
};

void usage() {
    std::fprintf(
        stderr,
        "usage: strata-native --config PROFILE.json | --registry REGISTRY.json | --model MODEL.gguf "
        "[options] [-- engine options]\n\n"
        "  --model PATH    the model's first GGUF shard (...-00001-of-00002.gguf); the second must be beside "
        "it\n"
        "  --pack DIR      the prepared pack for that model\n"
        "  --mtp DIR       the prepared draft head\n"
        "  --mmproj PATH   enable image input using this vision encoder (CPU)\n"
        "  --vision-tokens N  maximum tokens per image (default 1024)\n"
        "  --ctx N         context length in tokens (default 32768)\n"
        "  --threads N     CPU threads for the experts the GPU does not hold (default: every physical core,\n"
        "                  or half the CPU quota inside a container that has one)\n"
        "  --host ADDR     address to listen on (default 127.0.0.1)\n"
        "  --port N        port to listen on (default 8080)\n"
        "  --vram-cap MIB  emulate a smaller card: the engine uses at most MIB of VRAM (a 1080 Ti as 6 GB: "
        "5722)\n"
        "  --ram-cap GIB   bound the engine's RAM expert tier and pinned arena to GIB\n\n"
        "Serves POST /v1/chat/completions (OpenAI style, with streaming), GET /v1/models and GET /health "
        "(with the\n"
        "engine's expert tiers and per-token counters: VRAM slots, RAM copies, mapped experts, hits, warm "
        "hints,\n"
        "major page faults).\n");
}

bool file_exists(const std::string &p) {
    struct stat st;
    return ::stat(p.c_str(), &st) == 0;
}

// ---------------------------------------------------------------------------------------------------- the
// engine

using strata_frontend::Engine;
using strata_frontend::GenResult;

// ------------------------------------------------------------------------------------------------ text
// handling

/// The length of the longest prefix of `s` that does not end inside a UTF-8 character.
size_t utf8_complete_prefix(const std::string &s) {
    size_t i = s.size();
    int back = 0;
    while (i > 0 && back < 4) {
        const unsigned char c = (unsigned char)s[i - 1];
        ++back;
        if ((c & 0xC0) == 0x80) {
            --i;
            continue;
        } // a continuation byte: keep looking for its lead
        const int need = c >= 0xF0 ? 4 : c >= 0xE0 ? 3 : c >= 0xC0 ? 2 : 1;
        return need > back ? i - 1 : s.size();
    }
    return s.size();
}

std::string make_id() {
    static std::mt19937_64 rng{std::random_device{}()};
    static std::mutex mu;
    std::lock_guard<std::mutex> lk(mu);
    char b[40];
    std::snprintf(b, sizeof b, "chatcmpl-%016llx", (unsigned long long)rng());
    return b;
}

long long now_s() {
    return (long long)std::chrono::duration_cast<std::chrono::seconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

void json_error(httplib::Response &res, int status, const std::string &message, const char *type) {
    common_json e = common_json::object();
    e["error"] = common_json::object();
    e["error"]["message"] = message;
    e["error"]["type"] = type;
    res.status = status;
    res.set_content(e.dump_safe(), "application/json");
}

// ------------------------------------------------------------------------------------------------- the
// request

struct Prepared {
    std::shared_ptr<strata_frontend::ImageFile> images;
    std::vector<llama_token> ids;
    std::string header; // "GEN <max_new> key=value ... " - the ids follow
    std::string request_id;
    common_chat_parser_params parser; // how to split the output into reasoning, answer and tool calls
    bool stream = false;
    long long max_new = 0;
};

/// The parse of one response as its text grows: what has been published, and what to publish next.
///
/// Reasoning and answer text are published as they arrive.  Tool calls are published once, from the parse of
/// the complete message: while a call is being written its arguments are partial JSON that the parser closes
/// and normalizes on every token, so text already parsed can change (an escape, a number still being
/// written), and an OpenAI stream cannot take back what it sent.  The same rule keeps the answer text sound:
/// a partial parse whose content does not extend what was published (the parser reread the tail as the start
/// of a tool call) publishes nothing for the content until it does.  This changes delivery, never generated
/// tokens.
struct StreamParse {
    common_chat_msg msg; // what has been published
    std::vector<std::string> call_ids;

    std::vector<common_chat_msg_diff> step(const std::string &text, bool partial,
                                           const common_chat_parser_params &parser) {
        common_chat_msg now;
        try {
            now = common_chat_parse(text, partial, parser);
        } catch (const std::exception &) {
            if (partial)
                return {}; // not parseable yet: wait for more text
            now = common_chat_msg();
            now.role = "assistant";
            now.content = text;
        }
        now.content_parts.clear();
        if (partial) {
            now.tool_calls.clear();
            if (now.content.compare(0, msg.content.size(), msg.content) != 0)
                now.content = msg.content;
            if (now.reasoning_content.compare(0, msg.reasoning_content.size(), msg.reasoning_content) != 0)
                now.reasoning_content = msg.reasoning_content;
        } else {
            // the complete parse decides; text it no longer holds was already sent and stays sent (the parser
            // trims the white space before a tool call, which the partial parses still carried)
            for (auto field : {&common_chat_msg::content, &common_chat_msg::reasoning_content}) {
                const std::string &sent = msg.*field;
                std::string &whole = now.*field;
                if (whole.compare(0, sent.size(), sent) == 0)
                    continue;
                if (sent.compare(0, whole.size(), whole) != 0)
                    std::fprintf(stderr,
                                 "strata-native: the complete message's %s differs from the %zu bytes "
                                 "already streamed; the stream keeps what it sent\n",
                                 field == &common_chat_msg::content ? "content" : "reasoning", sent.size());
                whole = sent;
            }
        }
        if (now.empty())
            return {};
        now.set_tool_call_ids(call_ids, [] { return "call_" + make_id().substr(9); });
        std::vector<common_chat_msg_diff> diffs = common_chat_msg_diff::compute_diffs(msg, now);
        msg = now;
        return diffs;
    }
};

struct Server {
    Options opt;
    Engine engine;
    strata_frontend::Vision vision;
    llama_model *model = nullptr;
    const llama_vocab *vocab = nullptr;
    common_chat_templates_ptr tmpls;

    /// Parses an OpenAI chat request, renders the model's chat template and tokenizes the result.
    bool prepare(const common_json &body, Prepared &p, std::string &err, bool count_only = false) {
        if (!body.is_object() || !body.contains("messages") || !body.at("messages").is_array()) {
            err = "the request needs a \"messages\" array";
            return false;
        }
        common_chat_templates_inputs in;
        common_json messages = body.at("messages");
        std::vector<std::string> markers;
        std::vector<std::shared_ptr<strata_frontend::EncodedImage>> images;
        {
            std::lock_guard<std::mutex> lock(engine.mu);
            for (auto &message : messages) {
                if (!message.contains("content") || !message.at("content").is_array())
                    continue;
                for (auto &part : message["content"]) {
                    if (part.value("type", "") != "image_url")
                        continue;
                    if (images.size() >= 32)
                        throw std::invalid_argument("at most 32 images per request");
                    const std::string url = part.at("image_url").at("url").get<std::string>();
                    images.push_back(vision.encode(url));
                    markers.push_back("UNBIASED_IMAGE_" + make_id() + "_" + std::to_string(markers.size()));
                    part = common_json::object();
                    part["type"] = "media_marker";
                    part["text"] = markers.back();
                }
            }
        }
        in.messages = common_chat_msgs_parse_oaicompat(messages);
        if (body.contains("tools") && body.at("tools").is_array() && body.at("tools").size() > 0) {
            auto tools = body.at("tools");
            if (body.contains("tool_choice") && body.at("tool_choice").is_object()) {
                auto choice = body.at("tool_choice");
                auto name = choice.at("function").at("name").get<std::string>();
                auto selected = common_json::array();
                for (const auto &t : tools)
                    if (t.at("function").at("name") == name)
                        selected.push_back(t);
                if (selected.empty()) {
                    err = "Named tool choice does not name an available tool";
                    return false;
                }
                tools = selected;
                in.tool_choice = COMMON_CHAT_TOOL_CHOICE_REQUIRED;
            }
            in.tools = common_chat_tools_parse_oaicompat(tools);
            if (body.contains("tool_choice") && body.at("tool_choice").is_string())
                in.tool_choice =
                    common_chat_tool_choice_parse_oaicompat(body.at("tool_choice").get<std::string>());
            const auto caps = common_chat_templates_get_caps(tmpls.get());
            in.parallel_tool_calls =
                body.value("parallel_tool_calls", caps.at("supports_parallel_tool_calls"));
        }
        in.add_generation_prompt = true;
        in.use_jinja = true;
        in.reasoning_format = COMMON_REASONING_FORMAT_DEEPSEEK; // reasoning goes to "reasoning_content"
        in.enable_thinking = true;
        // thinking: OpenAI's reasoning_effort, or the llama.cpp / vLLM convention
        // chat_template_kwargs.enable_thinking
        if (body.contains("reasoning_effort") && body.at("reasoning_effort").is_string()) {
            const std::string effort = body.at("reasoning_effort").get<std::string>();
            if (effort == "none")
                in.enable_thinking = false;
            else
                in.chat_template_kwargs["reasoning_effort"] = common_json(effort).dump();
        }
        if (body.contains("chat_template_kwargs") && body.at("chat_template_kwargs").is_object()) {
            const common_json &kw = body.at("chat_template_kwargs");
            if (kw.contains("enable_thinking") && kw.at("enable_thinking").is_boolean())
                in.enable_thinking = kw.at("enable_thinking").get<bool>();
            if (kw.contains("reasoning_effort") && kw.at("reasoning_effort").is_string())
                in.chat_template_kwargs["reasoning_effort"] = kw.at("reasoning_effort").dump();
            // Qwen3.6's template drops the reasoning of every reply before the last user message unless this
            // is set; with it (and the client sending reasoning_content back) the history renders as it was
            // generated, so the next turn reuses the checkpoint at the end of the reply, not only the one at
            // its header
            if (kw.contains("preserve_thinking") && kw.at("preserve_thinking").is_boolean())
                in.chat_template_kwargs["preserve_thinking"] = kw.at("preserve_thinking").dump();
        }
        const common_chat_params cp = common_chat_templates_apply(tmpls.get(), in);
        std::string rendered = cp.prompt;
        if (images.empty()) {
            p.ids = common_tokenize(vocab, rendered, false, true);
        } else {
            const auto pad = common_tokenize(vocab, "<|image_pad|>", false, true);
            const auto literal_pad = common_tokenize(vocab, "<|image_pad|>", false, false);
            const auto start = common_tokenize(vocab, "<|vision_start|>", false, true);
            const auto end = common_tokenize(vocab, "<|vision_end|>", false, true);
            if (pad.size() != 1 || start.size() != 1 || end.size() != 1)
                throw std::runtime_error("model does not have the expected image special tokens");
            auto text_ids = [&](const std::string &text) {
                for (auto id : common_tokenize(vocab, text, false, true)) {
                    if (id == pad[0])
                        p.ids.insert(p.ids.end(), literal_pad.begin(), literal_pad.end());
                    else
                        p.ids.push_back(id);
                }
            };
            size_t offset = 0;
            rendered.clear();
            for (size_t i = 0; i < images.size(); ++i) {
                auto at = cp.prompt.find(markers[i], offset);
                if (at == std::string::npos ||
                    cp.prompt.find(markers[i], at + markers[i].size()) != std::string::npos)
                    throw std::invalid_argument("chat template did not preserve each image exactly once");
                auto text = cp.prompt.substr(offset, at - offset);
                text_ids(text);
                rendered += text + "<|vision_start|>";
                p.ids.push_back(start[0]);
                p.ids.insert(p.ids.end(), images[i]->tokens, pad[0]);
                for (int j = 0; j < images[i]->tokens; ++j)
                    rendered += "<|image_pad|>";
                p.ids.push_back(end[0]);
                rendered += "<|vision_end|>";
                offset = at + markers[i].size();
            }
            auto tail = cp.prompt.substr(offset);
            text_ids(tail);
            rendered += tail;
            p.images = std::make_shared<strata_frontend::ImageFile>();
            strata_frontend::write_images(*p.images, images);
        }
        if (p.ids.empty()) {
            err = "the prompt is empty";
            return false;
        }

        if (count_only)
            return true;
        p.parser = common_chat_parser_params(cp);
        p.parser.reasoning_format = COMMON_REASONING_FORMAT_DEEPSEEK;
        p.parser.parse_tool_calls = true;
        if (!cp.parser.empty())
            p.parser.parser.load(cp.parser);

        // The engine refuses a request unless prompt + max_new + 8 <= context (generate.cpp, the GEN
        // handler), so the slots it keeps back are not ours to promise.  Without this a client that asks for
        // "as much as fits" (pi sends max_tokens 32768 on a 64K card) was refused on every prompt longer than
        // ctx - max_tokens.
        constexpr long long kEngineReserve = 8;
        const long long n = (long long)p.ids.size();
        if (n + 1 + kEngineReserve > opt.ctx) {
            err = "the prompt is " + std::to_string(n) + " tokens, which does not fit the context of " +
                  std::to_string(opt.ctx);
            return false;
        }
        long long max_new = opt.ctx - n - kEngineReserve;
        for (const char *key : {"max_completion_tokens", "max_tokens"})
            if (body.contains(key) && body.at(key).is_number()) {
                const long long want = body.at(key).get<long long>();
                if (want >= 1)
                    max_new = std::min(max_new, want);
                break;
            }
        for (const char *k : {"max_tokens", "max_completion_tokens"})
            if (body.contains(k) && (!body.at(k).is_number_integer() || body.at(k).get<long long>() < 1)) {
                err = "Output token limit must be a positive integer";
                return false;
            }
        p.max_new = max_new;
        p.stream = body.value("stream", false);

        // sampling: greedy unless the request sets a temperature above zero
        std::string keys;
        const double temperature = body.contains("temperature") && body.at("temperature").is_number()
                                       ? body.at("temperature").get<double>()
                                       : 0.0;
        if (temperature > 0.0) {
            const double top_p = body.contains("top_p") && body.at("top_p").is_number()
                                     ? body.at("top_p").get<double>()
                                     : 0.95;
            long long top_k = body.contains("top_k") && body.at("top_k").is_number()
                                  ? body.at("top_k").get<long long>()
                                  : 20;
            top_k = std::max(1LL, std::min(64LL, top_k)); // the engine's sampler takes 1..64
            unsigned long long seed;
            if (body.contains("seed") && body.at("seed").is_number())
                seed = (unsigned long long)body.at("seed").get<long long>();
            else
                seed = std::random_device{}();
            char b[160];
            std::snprintf(b, sizeof b, " temperature=%g top_p=%g top_k=%lld seed=%llu", temperature, top_p,
                          top_k, seed);
            keys += b;
            if (body.contains("min_p") && body.at("min_p").is_number()) {
                std::snprintf(b, sizeof b, " min_p=%g", body.at("min_p").get<double>());
                keys += b;
            }
        }
        for (const auto &kv : {std::pair<const char *, const char *>{"presence_penalty", "penalty_present"},
                               std::pair<const char *, const char *>{"frequency_penalty", "penalty_freq"},
                               std::pair<const char *, const char *>{"repeat_penalty", "penalty_repeat"}})
            if (body.contains(kv.first) && body.at(kv.first).is_number()) {
                char b[64];
                std::snprintf(b, sizeof b, " %s=%g", kv.second, body.at(kv.first).get<double>());
                keys += b;
                if (keys.find("penalty_last_n") == std::string::npos)
                    keys += " penalty_last_n=64";
            }
        p.header = (p.images ? "GENI " : "GEN ") + std::to_string(max_new) + keys + " " +
                   (p.images ? p.images->path + " " : "");
        return true;
    }

    common_json usage_json(const GenResult &r) const {
        common_json u = common_json::object();
        u["prompt_tokens"] = r.prompt_n;
        u["prompt_tokens_details"] = {{"cached_tokens", r.cache_n}};
        u["completion_tokens"] = r.produced;
        u["total_tokens"] = r.prompt_n + r.produced;
        return u;
    }

    common_json timings_json(const GenResult &r) const {
        common_json t = common_json::object();
        t["prompt_n"] = r.prompt_n - r.cache_n;
        t["cache_n"] = r.cache_n;
        t["prompt_ms"] = r.prompt_ms;
        t["prompt_per_second"] =
            r.prompt_ms > 0 ? 1000.0 * (double)(r.prompt_n - r.cache_n) / r.prompt_ms : 0.0;
        t["predicted_n"] = r.produced;
        t["predicted_ms"] = r.decode_ms;
        t["predicted_per_second"] = r.decode_ms > 0 ? 1000.0 * (double)r.produced / r.decode_ms : 0.0;
        t["draft_n"] = r.draft_offered;
        t["draft_n_accepted"] = r.draft_accepted;
        return t;
    }

    /// Runs one request.  The text produced so far is parsed by llama.cpp's chat parser after every token,
    /// and `emit` gets what changed (reasoning and answer text as they grow, tool calls once the message is
    /// complete: see StreamParse); it returns false when the client has gone.  `final_msg` is the whole
    /// parsed message. `keepalive`, when given, is called whenever 2 s pass without an emit (a long tool
    /// call is silent while its arguments are written): the stream writes an SSE comment, which keeps clients
    /// with an idle timeout (pi: 5 minutes) attached and notices a client that has gone, so the generation is
    /// cancelled instead of running to the end for nobody.
    GenResult run(const Prepared &p, common_chat_msg &final_msg,
                  const std::function<bool(const std::vector<common_chat_msg_diff> &)> &emit,
                  const std::function<bool()> &keepalive = {}) {
        std::lock_guard<std::mutex> lk(engine.mu);
        std::fprintf(stderr, "strata-native: request %s start: prompt=%zu header=%s\n", p.request_id.c_str(),
                     p.ids.size(), p.header.c_str());
        std::string memory_error;
        auto memory_ok = [&] {
            memory_error = native_memory::refusal(native_memory::snapshot(),
                static_cast<uint64_t>((native_router::requested_ram_floor + 1) * native_memory::GiB),
                static_cast<uint64_t>(native_router::requested_vram_floor + 256) * native_memory::MiB);
            return memory_error.empty();
        };
        if (!memory_ok()) {
            GenResult rejected; rejected.error = memory_error; return rejected;
        }
        auto last_memory_check = std::chrono::steady_clock::now();
        auto memory_safe = [&] {
            if (std::chrono::steady_clock::now() - last_memory_check < std::chrono::milliseconds(500))
                return memory_error.empty();
            last_memory_check = std::chrono::steady_clock::now();
            return memory_ok();
        };
        std::string text, pending;
        StreamParse parse;
        common_chat_msg &msg = parse.msg;
        bool client_ok = true;
        auto last_write = std::chrono::steady_clock::now();
        auto update = [&](bool partial) {
            const std::vector<common_chat_msg_diff> diffs = parse.step(text, partial, p.parser);
            if (client_ok && !diffs.empty()) {
                client_ok = emit(diffs);
                last_write = std::chrono::steady_clock::now();
            }
        };
        GenResult r = engine.generate(
            p.header, p.ids,
            [&](llama_token id) {
                if (!memory_safe()) return false;
                if (llama_vocab_is_eog(vocab, id))
                    return client_ok;
                pending += common_token_to_piece(vocab, id, /*special=*/true);
                const size_t n = utf8_complete_prefix(pending);
                if (n > 0) {
                    text.append(pending, 0, n);
                    pending.erase(0, n);
                    if (p.stream)
                        update(true); // a whole response is parsed once, at the end
                }
                if (client_ok && keepalive) {
                    const auto now = std::chrono::steady_clock::now();
                    if (now - last_write >= std::chrono::seconds(2)) {
                        client_ok = keepalive();
                        last_write = now;
                    }
                }
                return client_ok;
            },
            [&]() {
                if (!memory_safe()) return false;
                if (client_ok && keepalive &&
                    std::chrono::steady_clock::now() - last_write >= std::chrono::seconds(2)) {
                    client_ok = keepalive();
                    last_write = std::chrono::steady_clock::now();
                }
                return client_ok;
            });
        if (!memory_error.empty()) {
            r.ok = false; r.error = memory_error;
            std::fprintf(stderr, "strata-native: request cancelled by memory admission: %s\n", memory_error.c_str());
        }
        text += pending;
        try {
            update(false);
        } catch (const std::exception &ex) {
            r.ok = false;
            r.error = std::string("response formatter failed: ") + ex.what();
            std::fprintf(stderr, "strata-native: final response formatter failed: %s\n", ex.what());
        }
        final_msg = msg;
        if (final_msg.role.empty())
            final_msg.role = "assistant";
        if (final_msg.tool_calls.empty() && text.find("<tool_call>") != std::string::npos) {
            // The parser accepts a message with no tool call even when the text holds one it could not
            // match (see third_party/llama.cpp/common/parsers/qwen3-coder.cpp); say so, with the text.
            std::fprintf(stderr,
                         "strata-native: request %s: the output contains <tool_call> but no tool call was "
                         "parsed; the client sees finish=stop. raw-output-begin\n%s\n"
                         "strata-native: request %s raw-output-end\n",
                         p.request_id.c_str(), text.c_str(), p.request_id.c_str());
        }
        if (r.error.find("response formatter failed") == 0) {
            std::fprintf(stderr,
                         "strata-native: request %s formatter-input-begin\n%s\n"
                         "strata-native: request %s formatter-input-end\n",
                         p.request_id.c_str(), text.c_str(), p.request_id.c_str());
        }
        std::fprintf(
            stderr, "strata-native: request %s end: ok=%d prompt=%lld generated=%lld finish=%s error=%s\n",
            p.request_id.c_str(), r.ok ? 1 : 0, r.prompt_n, r.produced, r.finish.c_str(), r.error.c_str());
        return r;
    }

    static const char *finish_reason(const GenResult &r, const common_chat_msg &msg) {
        if (!msg.tool_calls.empty())
            return "tool_calls";
        return r.finish == "stop" ? "stop" : "length";
    }

#include "compat_methods.inc"

    void handle_chat(const httplib::Request &req, httplib::Response &res) {
        if (!engine.alive())
            return json_error(res, 503, "the engine is not running", "server_error");
        const common_json body = common_json::parse_no_throw(req.body);
        if (body.is_discarded())
            return json_error(res, 400, "the request body is not valid JSON", "invalid_request_error");
        auto prep = std::make_shared<Prepared>();
        std::string err;
        try {
            if (!prepare(body, *prep, err))
                return json_error(res, 400, err, "invalid_request_error");
        } catch (const std::exception &ex) {
            return json_error(res, 400, ex.what(), "invalid_request_error");
        }
        const std::string id = make_id();
        prep->request_id = id;
        const long long created = now_s();

        if (!prep->stream) {
            common_chat_msg msg;
            const GenResult r =
                run(*prep, msg, [](const std::vector<common_chat_msg_diff> &) { return true; });
            if (!r.ok)
                return json_error(res, r.error.rfind("Insufficient", 0) == 0 ? 503 : 500, r.error,
                                  r.error.rfind("Insufficient", 0) == 0 ? "resource_exhausted" : "server_error");
            common_json choice = common_json::object();
            choice["index"] = 0;
            choice["message"] = msg.to_json_oaicompat();
            choice["finish_reason"] = finish_reason(r, msg);
            common_json out = common_json::object();
            out["id"] = id;
            out["object"] = "chat.completion";
            out["created"] = created;
            out["model"] = g_model_name;
            out["choices"] = common_json::array();
            out["choices"].push_back(choice);
            out["usage"] = usage_json(r);
            out["timings"] = timings_json(r);
            res.set_content(out.dump_safe(), "application/json");
            return;
        }

        res.set_header("Cache-Control", "no-cache");
        res.set_header("X-Accel-Buffering", "no");
        res.set_chunked_content_provider(
            "text/event-stream", [this, prep, id, created](size_t, httplib::DataSink &sink) {
                auto chunk = [&](const common_json &delta, const char *finish, const GenResult *done) {
                    common_json choice = common_json::object();
                    choice["index"] = 0;
                    choice["delta"] = delta;
                    if (finish)
                        choice["finish_reason"] = finish;
                    else
                        choice["finish_reason"] = nullptr;
                    common_json out = common_json::object();
                    out["id"] = id;
                    out["object"] = "chat.completion.chunk";
                    out["created"] = created;
                    out["model"] = g_model_name;
                    out["choices"] = common_json::array();
                    out["choices"].push_back(choice);
                    if (done) {
                        out["usage"] = usage_json(*done);
                        out["timings"] = timings_json(*done);
                    }
                    const std::string s = "data: " + out.dump_safe() + "\n\n";
                    return sink.write(s.data(), s.size());
                };
                common_json first = common_json::object();
                first["role"] = "assistant";
                first["content"] = "";
                bool ok = chunk(first, nullptr, nullptr);
                common_chat_msg msg;
                const GenResult r = run(
                    *prep, msg,
                    [&](const std::vector<common_chat_msg_diff> &diffs) {
                        for (const common_chat_msg_diff &df : diffs) {
                            common_json d = common_json::object();
                            if (!df.reasoning_content_delta.empty())
                                d["reasoning_content"] = df.reasoning_content_delta;
                            if (!df.content_delta.empty())
                                d["content"] = df.content_delta;
                            if (df.tool_call_index != std::string::npos) {
                                common_json fn = common_json::object();
                                if (!df.tool_call_delta.name.empty())
                                    fn["name"] = df.tool_call_delta.name;
                                fn["arguments"] = df.tool_call_delta.arguments;
                                common_json tc = common_json::object();
                                tc["index"] = (long long)df.tool_call_index;
                                if (!df.tool_call_delta.id.empty()) {
                                    tc["id"] = df.tool_call_delta.id;
                                    tc["type"] = "function";
                                }
                                tc["function"] = fn;
                                d["tool_calls"] = common_json::array();
                                d["tool_calls"].push_back(tc);
                            }
                            if (d.size() == 0)
                                continue;
                            ok = ok && chunk(d, nullptr, nullptr);
                        }
                        return ok;
                    },
                    [&]() {
                        static const std::string ka =
                            ": keepalive\n\n"; // an SSE comment: every client ignores it
                        ok = ok && sink.is_writable() && sink.write(ka.data(), ka.size());
                        return ok;
                    });
                if (ok) {
                    if (r.ok) {
                        chunk(common_json::object(), finish_reason(r, msg), &r);
                    } else {
                        common_json e = common_json::object();
                        e["error"] = common_json::object();
                        e["error"]["message"] = r.error;
                        e["error"]["type"] = "server_error";
                        const std::string s = "data: " + e.dump_safe() + "\n\n";
                        sink.write(s.data(), s.size());
                    }
                    static const std::string end = "data: [DONE]\n\n";
                    sink.write(end.data(), end.size());
                }
                sink.done();
                return true;
            });
    }
};

volatile std::sig_atomic_t g_shutdown_requested = 0;
void on_signal(int) { g_shutdown_requested = 1; }

void quiet_log(ggml_log_level level, const char *text, void *) {
    if (level == GGML_LOG_LEVEL_ERROR || level == GGML_LOG_LEVEL_WARN)
        std::fputs(text, stderr);
}

bool parse_args(int argc, char **argv, Options &o) {
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        auto next = [&](const char *name) -> std::string {
            if (i + 1 >= argc) {
                std::fprintf(stderr, "strata-native: %s needs a value\n", name);
                std::exit(2);
            }
            return argv[++i];
        };
        if (a == "--open")
            o.open_browser = true;
        else if (a == "--api-key")
            o.api_key = next("--api-key");
        else if (a == "--memory-floor-gib")
            native_router::requested_ram_floor = std::stod(next("--memory-floor-gib"));
        else if (a == "--vram-floor-mib")
            native_router::requested_vram_floor = std::stoll(next("--vram-floor-mib"));
        else if (a == "--model-id")
            o.model_id = next("--model-id");
        else if (a == "--config")
            o.config = next("--config");
        else if (a == "--registry")
            o.registry = next("--registry");
        else if (a == "--model")
            o.model = next("--model");
        else if (a == "--mmproj")
            o.mmproj = next("--mmproj");
        else if (a == "--vision-tokens")
            o.vision_tokens = std::atoi(next("--vision-tokens").c_str());
        else if (a == "--pack")
            o.pack = next("--pack");
        else if (a == "--mtp")
            o.mtp = next("--mtp");
        else if (a == "--host")
            o.host = next("--host");
        else if (a == "--port")
            o.port = std::atoi(next("--port").c_str());
        else if (a == "--ctx")
            o.ctx = std::atoll(next("--ctx").c_str());
        else if (a == "--threads")
            o.threads = std::atoi(next("--threads").c_str());
        else if (a == "--vram-cap")
            o.vram_cap_mib = std::atoll(next("--vram-cap").c_str());
        else if (a == "--ram-cap")
            o.ram_cap_gib = std::atof(next("--ram-cap").c_str());
        else if (a == "--") {
            for (++i; i < argc; ++i) {
                const std::string e = argv[i];
                // one GPU only: the engine's multi-GPU and remote-expert modes are not part of this fork
                for (const char *no : {"--gpus", "--layer-split", "--split-device", "--peer-device",
                                       "--peer-slots", "--remote-expert", "--vision", "--batch"})
                    if (e.rfind(no, 0) == 0) {
                        std::fprintf(
                            stderr,
                            "strata-native: %s is not supported here (use --mmproj for image input)\n",
                            e.c_str());
                        std::exit(2);
                    }
                o.extra.push_back(e);
            }
        } else if (a == "-h" || a == "--help")
            return false;
        else {
            std::fprintf(stderr, "strata-native: unknown option %s\n\n", a.c_str());
            return false;
        }
    }
    if (o.config.empty() && o.registry.empty() && o.model.empty()) {
        const char *x = getenv("XDG_CONFIG_HOME");
        const char *h = getenv("HOME");
        o.registry = std::string(x ? x : (std::string(h ? h : ".") + "/.config")) + "/strata/router.json";
        if (o.port == 8080)
            o.port = 8096;
    }
    if (!std::isfinite(native_router::requested_ram_floor) || native_router::requested_ram_floor < 1 ||
        native_router::requested_ram_floor > 1024 || native_router::requested_vram_floor < 256 ||
        native_router::requested_vram_floor > 1048576) {
        std::fprintf(stderr, "strata-native: memory floors must be finite and positive (RAM >= 1 GiB, VRAM >= 256 MiB)\n");
        return false;
    }
    return true;
}

} // namespace

int main(int argc, char **argv) {
    if(argc>1&&std::strcmp(argv[1],"--llama-worker")==0)return native_backend::worker(argc,argv);
    if (argc > 1 && std::strcmp(argv[1], "--engine") == 0) {
#ifdef __linux__
        ::prctl(PR_SET_NAME, "strata-engine", 0, 0, 0);
#endif
        return strata_engine_main(argc - 1, argv + 1);
    }

    Server srv;
    Options &o = srv.opt;
    if (!parse_args(argc, argv, o)) {
        usage();
        return 2;
    }
    if (!o.api_key.empty())
        setenv("STRATA_API_KEY", o.api_key.c_str(), 1);
    if (o.open_browser) {
        try {
            native_router::spawn({"xdg-open", "http://127.0.0.1:" + std::to_string(o.port) + "/"});
        } catch (...) {
        }
    }
    if (!o.registry.empty()) {
        try {
            return native_router::run(o.registry, o.port, o.host);
        } catch (const std::exception &ex) {
            std::fprintf(stderr, "strata-native: %s\n", ex.what());
            return 2;
        }
    }
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    std::string lockpath = (runtime ? std::string(runtime) : "/tmp") + "/strata-native-model-" +
                           std::to_string(getuid()) + ".lock";
    int model_lock = open(lockpath.c_str(), O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (model_lock < 0 || flock(model_lock, LOCK_EX | LOCK_NB)) {
        std::fprintf(stderr, "strata-native: another native model worker is active; release it first\n");
        return 2;
    }
    if (o.host != "127.0.0.1" && o.host != "::1" && o.host != "localhost") {
        const char *key=getenv("STRATA_API_KEY");
        if(!key || !*key) {
            std::fprintf(stderr, "strata-native: non-loopback listening requires --api-key or STRATA_API_KEY\n");
            return 2;
        }
    }
    // Direct worker invocation must have the same hard host-memory boundary as router workers.
    const auto worker_memory = native_memory::snapshot();
    if (!worker_memory.cgroup_limit) {
        std::fprintf(stderr, "strata-native: refusing an unbounded model worker; use router mode, or run inside\n"
                             "  systemd-run --user --scope -p MemoryMax=20G -p MemorySwapMax=0 <command>\n");
        return 2;
    }
    const auto worker_admission = native_memory::refusal(worker_memory,
        static_cast<uint64_t>((native_router::requested_ram_floor + 1) * native_memory::GiB),
        static_cast<uint64_t>(native_router::requested_vram_floor + 256) * native_memory::MiB);
    if (!worker_admission.empty()) {
        std::fprintf(stderr, "strata-native: %s\n", worker_admission.c_str());
        return 2;
    }
    std::vector<std::string> eargs;
    try {
        if (!o.config.empty()) {
            auto cfg = native_profiles::load(std::filesystem::absolute(o.config));
            auto args = cfg.at("args").get<std::vector<std::string>>();
            o.model = native_profiles::option(args, "--native");
            if (o.model.empty())
                throw std::runtime_error("Profile must name a local --native GGUF");
            o.ctx = std::stoll(native_profiles::option(args, "--max-context", "32768"));
            g_model_name = cfg.value("model_name", model_name_of(o.model));
            if (cfg.contains("env"))
                for (auto it = cfg["env"].begin(); it != cfg["env"].end(); ++it)
                    setenv(it.key().c_str(), it.value().get<std::string>().c_str(), 1);
            if (cfg.contains("vision")) {
                auto v = cfg.at("vision");
                o.mmproj = v.at("mmproj").get<std::string>();
                o.vision_tokens = v.value("max_tokens", 2048);
                o.threads = v.value("threads", 4);
            }
            if (chdir(cfg.at("cwd").get<std::string>().c_str()))
                throw std::runtime_error("Profile cwd unavailable");
            eargs = {"strata-native", "--engine", "--serve"};
            eargs.insert(eargs.end(), args.begin(), args.end());
        } else {
            g_model_name = model_name_of(o.model);
            if (!std::filesystem::is_regular_file(o.model))
                throw std::runtime_error("Model GGUF is missing");
            eargs = {"strata-native", "--engine",           "--serve", "--native", o.model,
                     "--max-context", std::to_string(o.ctx)};
            if (!o.pack.empty()) {
                for (const auto &f : {o.pack + "/index.txt", o.pack + "/expert-profile.bin"})
                    if (!file_exists(f))
                        throw std::runtime_error("Missing prepared pack file: " + f);
                eargs.insert(eargs.end(),
                             {"--pack", o.pack, "--expert-profile", o.pack + "/expert-profile.bin",
                              "--expert-cache", "auto", "--prefill", "auto"});
            }
            if (!o.mtp.empty())
                eargs.insert(eargs.end(), {"--spec", "4", "--spec-min-p", "0.5", "--mtp", o.mtp});
            std::string shard2 = o.model;
            auto at = shard2.rfind("-00001-of-00002");
            if (at != std::string::npos) {
                shard2.replace(at, 15, "-00002-of-00002");
                if (!file_exists(shard2))
                    throw std::runtime_error("Second GGUF shard is missing");
                eargs.insert(eargs.end(), {"--ple-gguf", shard2, "--ple-io", "direct"});
            }
            if (o.ctx > 8192)
                eargs.insert(eargs.end(), {"--kv", "int8"});
            if (o.threads > 0)
                eargs.insert(eargs.end(), {"--pool-workers", std::to_string(o.threads)});
            if (!o.mmproj.empty())
                eargs.push_back("--vision");
            eargs.insert(eargs.end(), o.extra.begin(), o.extra.end());
        }
        if (o.ctx < 1024)
            throw std::runtime_error("Context must be at least 1024 tokens");
    } catch (const std::exception &ex) {
        std::fprintf(stderr, "strata-native: %s\n", ex.what());
        return 2;
    }
    if (!o.model_id.empty())
        g_model_name = o.model_id;
    std::signal(SIGPIPE, SIG_IGN);
    std::string err;
    setenv("STRATA_NATIVE_MONITOR", "1", 1);
    if (!srv.engine.start(eargs, err)) {
        std::fprintf(stderr, "strata-native: %s\n", err.c_str());
        return 1;
    }

    // the tokenizer and the chat template, from the GGUF itself
    llama_log_set(quiet_log, nullptr);
    llama_backend_init();
    llama_model_params mp = llama_model_default_params();
    mp.vocab_only = true;
    srv.model = llama_model_load_from_file(o.model.c_str(), mp);
    if (srv.model == nullptr) {
        std::fprintf(stderr, "strata-native: could not read the tokenizer from %s\n", o.model.c_str());
        srv.engine.quit();
        return 1;
    }
    srv.vocab = llama_model_get_vocab(srv.model);
    srv.tmpls = common_chat_templates_init(srv.model, "");
    if (!o.mmproj.empty()) {
        try {
            srv.vision.init(o.mmproj, srv.model, o.threads, o.vision_tokens);
        } catch (const std::exception &ex) {
            std::fprintf(stderr, "strata-native: %s\n", ex.what());
            srv.engine.quit();
            return 1;
        }
    }

    std::fprintf(stderr, "strata-native: loading the model (this takes a few minutes)...\n");
    long long engine_ctx = 0;
    if (!srv.engine.wait_ready(err, &engine_ctx)) {
        std::fprintf(stderr, "strata-native: %s\n", err.c_str());
        srv.engine.quit();
        return 1;
    }
    if (engine_ctx > 0 && engine_ctx != o.ctx) { // the engine's VRAM plan lowered the context: serve that one
        std::fprintf(stderr,
                     "strata-native: the engine allocated a context of %lld tokens, not the %lld requested; "
                     "requests are bounded by %lld\n",
                     engine_ctx, o.ctx, engine_ctx);
        o.ctx = engine_ctx;
    }

    httplib::Server http;
    native_router::install_security(http, o.host != "127.0.0.1" && o.host != "::1" && o.host != "localhost");
    // /health: ok or error, plus the engine's expert tiers and counters when it is between requests (STATS:
    // VRAM slots and how many hold an expert, RAM copies, mapped experts, tokens served, VRAM hits of
    // lookups, RAM-copy and file reads, warm hints, major page faults).  During a request the last reading is
    // served, marked stale. httplib serves /health from several threads: the last reading has its own lock
    // (engine.mu is the engine's, taken only to ask), and every read of it is a copy under that lock.
    static std::mutex stats_mu;
    static std::string last_stats;
    http.Get("/health", [&](const httplib::Request &, httplib::Response &res) {
        res.status = srv.engine.alive() ? 200 : 503;
        std::string body = srv.engine.alive() ? "{\"status\":\"ok\"" : "{\"status\":\"error\"";
        if (srv.engine.alive()) {
            std::unique_lock<std::mutex> lk(srv.engine.mu, std::try_to_lock);
            if (lk.owns_lock()) {
                std::string reply, err;
                const bool got = srv.engine.command("STATS", "STATS ", reply, err);
                lk.unlock();
                std::string stats;
                {
                    std::lock_guard<std::mutex> sl(stats_mu);
                    if (got)
                        last_stats = reply.substr(6);
                    stats = last_stats;
                }
                if (!got && stats.empty())
                    body += ",\"tiers_error\":\"" + err + "\"";
                if (!stats.empty())
                    body += ",\"tiers\":" + stats;
            } else {
                std::string stats;
                {
                    std::lock_guard<std::mutex> sl(stats_mu);
                    stats = last_stats;
                }
                if (!stats.empty())
                    body += ",\"tiers\":" + stats + ",\"tiers_stale\":true";
                else
                    body += ",\"busy\":true";
            }
        }
        body += ",\"model\":\"" + g_model_name + "\",\"max_context\":" + std::to_string(o.ctx) +
                ",\"images\":" + (srv.vision.enabled() ? "true" : "false") + ",\"engine\":\"" +
                STRATA_VERSION + "\",\"runtime\":\"native-c++\"}";
        auto response = common_json::parse_no_throw(body);
        response["live"] = {
            {"state", srv.engine.busy ? (srv.engine.generated > 0 ? "generating" : "reading") : "idle"},
            {"prompt_total", srv.engine.prompt_total.load()},
            {"prompt_read", srv.engine.prompt_read.load()},
            {"generated", srv.engine.generated.load()}, {"prefill_total", srv.engine.prefill_total.load()},
            {"prefill_tok_s_mean", srv.engine.prefill_tps.load()},
            {"decode_tok_s_mean", srv.engine.decode_tps.load()},
            {"cached_tokens", srv.engine.cached_tokens.load()},
            {"cancelled", srv.engine.cancelled.load()},
            {"draft_accepted", srv.engine.draft_accepted.load()}, {"draft_offered", srv.engine.draft_offered.load()},
            {"position", srv.engine.position.load()}, {"kv_capacity", srv.engine.kv_capacity.load()},
            {"kv_bytes", srv.engine.kv_bytes.load()},
            {"weights_resident_bytes", srv.engine.weights_resident.load()},
            {"weights_file_backed_bytes", srv.engine.weights_backed.load()}};
        res.set_content(response.dump_safe(), "application/json");
    });
    http.Get("/v1/models", [&](const httplib::Request &, httplib::Response &res) {
        if (!srv.engine.alive())
            return json_error(res, 503, "the engine is not running", "server_error");
        common_json m = common_json::object();
        m["id"] = g_model_name;
        m["object"] = "model";
        m["owned_by"] = "local";
        m["context_length"] = srv.opt.ctx;
        m["input_modalities"] = common_json::array();
        m["input_modalities"].push_back("text");
        if (srv.vision.enabled())
            m["input_modalities"].push_back("image");
        common_json out = common_json::object();
        out["object"] = "list";
        out["data"] = common_json::array();
        out["data"].push_back(m);
        res.set_content(out.dump_safe(), "application/json");
    });
    http.Post("/cancel", [&](const auto &, auto &res) {
        const bool cancelled = srv.engine.request_cancel();
        res.set_content(common_json{{"cancel_requested", cancelled}}.dump_safe(), "application/json");
    });
    http.Post("/v1/chat/completions",
              [&](const httplib::Request &req, httplib::Response &res) { srv.handle_chat(req, res); });
    http.Post("/v1/messages", [&](auto &req, auto &res) { srv.handle_compat(req, res, true); });
    http.Post("/v1/messages/count_tokens",
              [&](auto &req, auto &res) { srv.handle_compat(req, res, true, true); });
    http.Post("/v1/responses", [&](auto &req, auto &res) { srv.handle_compat(req, res, false); });
    http.new_task_queue = [] { return new httplib::ThreadPool(4, 4, 8); };
    http.set_payload_max_length(32 * 1024 * 1024);
    http.set_read_timeout(600, 0);
    http.set_write_timeout(600, 0);
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    if (!http.bind_to_port(o.host, o.port)) {
        std::fprintf(stderr, "strata-native: could not listen on %s:%d\n", o.host.c_str(), o.port);
        srv.engine.quit();
        return 1;
    }
    std::fprintf(stderr, "strata-native: ready on http://%s:%d (context %lld tokens)\n", o.host.c_str(),
                 o.port, o.ctx);
    // The engine watchdog intentionally aborts a stuck child. Exit the HTTP
    // parent too so systemd's Restart=on-failure reloads the complete service.
    // Do not fork a replacement from this multithreaded HTTP process.
    std::atomic<bool> shutting_down{false};
    std::thread supervisor([&] {
        while (!shutting_down.load()) {
            if (g_shutdown_requested) {
                srv.engine.terminate();
                http.stop();
                return;
            }
            std::string why;
            if (srv.engine.reap_exit(why)) {
                std::fprintf(stderr, "strata-native: %s; exiting frontend for service restart\n",
                             why.c_str());
                std::fflush(stderr);
                std::_Exit(1);
            }
            if (!srv.engine.alive()) {
                std::fprintf(stderr,
                             "strata-native: engine protocol failed; exiting frontend for service restart\n");
                std::fflush(stderr);
                std::_Exit(1);
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    });
    http.listen_after_bind();
    shutting_down.store(true);
    supervisor.join();

    std::fprintf(stderr, "strata-native: stopping\n");
    srv.engine.quit();
    llama_model_free(srv.model);
    return 0;
}
