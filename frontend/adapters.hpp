#pragma once
#include "json.h"
#include <stdexcept>
namespace native_api {
inline std::string base64(const std::string &text, bool decode = false) {
    static const std::string alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    unsigned bits = 0;
    int count = 0;
    for (unsigned char c : text) {
        if (decode) {
            if (c == '=')
                break;
            auto at = alphabet.find(c);
            if (at == std::string::npos)
                throw std::runtime_error("Invalid reasoning replay encoding");
            bits = (bits << 6) | unsigned(at);
            count += 6;
            if (count >= 8) {
                count -= 8;
                out.push_back(char((bits >> count) & 255));
            }
        } else {
            bits = (bits << 8) | c;
            count += 8;
            while (count >= 6) {
                count -= 6;
                out.push_back(alphabet[(bits >> count) & 63]);
            }
        }
    }
    if (!decode) {
        if (count)
            out.push_back(alphabet[(bits << (6 - count)) & 63]);
        while (out.size() % 4)
            out.push_back('=');
    }
    return out;
}
inline std::string replay(const common_json &item) {
    auto text = item.value("encrypted_content", "");
    if (text.rfind("strata.r1:", 0) == 0)
        return common_json::parse(base64(text.substr(10), true)).at("text").get<std::string>();
    std::string result;
    if (item.contains("content"))
        for (const auto &p : item.at("content"))
            if (p.value("type", "") == "reasoning_text")
                result += p.value("text", "");
    if (result.empty() && item.contains("summary"))
        for (const auto &p : item.at("summary"))
            result += p.value("text", "");
    return result;
}
inline common_json text_parts(const common_json &content, bool anthropic = false) {
    if (content.is_string())
        return content;
    common_json out = common_json::array();
    for (const auto &p : content) {
        auto type = p.value("type", "");
        if (type == "text" || type == "input_text" || type == "output_text")
            out.push_back({{"type", "text"}, {"text", p.at("text")}});
        else if (type == "input_image")
            out.push_back({{"type", "image_url"}, {"image_url", {{"url", p.at("image_url")}}}});
        else if (type == "image" && anthropic) {
            auto s = p.at("source");
            if (s.value("type", "") != "base64")
                throw std::runtime_error("Only inline base64 screenshots are supported; no URL downloads");
            out.push_back({{"type", "image_url"},
                           {"image_url",
                            {{"url", "data:" + s.at("media_type").get<std::string>() + ";base64," +
                                         s.at("data").get<std::string>()}}}});
        } else
            throw std::runtime_error("Unsupported message content block: " + type);
    }
    return out;
}
inline common_json chat_request(const common_json &in, bool anthropic) {
    common_json out = common_json::object();
    for (const char *k : {"model", "stream", "temperature", "top_p", "top_k", "max_tokens",
                          "max_output_tokens", "reasoning_effort", "seed"})
        if (in.contains(k))
            out[k == std::string("max_output_tokens") ? "max_tokens" : k] = in.at(k);
    common_json messages = common_json::array();
    if (anthropic) {
        if (in.contains("thinking") && in.at("thinking").value("type", "") == "disabled")
            out["reasoning_effort"] = "none";
        if (in.contains("system"))
            messages.push_back({{"role", "system"}, {"content", text_parts(in.at("system"))}});
        for (const auto &m : in.at("messages")) {
            auto content = m.at("content");
            if (content.is_string()) {
                messages.push_back(m);
                continue;
            }
            common_json parts = common_json::array(), calls = common_json::array();
            std::string thought;
            for (const auto &p : content) {
                auto type = p.value("type", "");
                if (type == "tool_result")
                    messages.push_back({{"role", "tool"},
                                        {"tool_call_id", p.at("tool_use_id")},
                                        {"content", text_parts(p.at("content"))}});
                else if (type == "tool_use")
                    calls.push_back(
                        {{"id", p.at("id")},
                         {"type", "function"},
                         {"function", {{"name", p.at("name")}, {"arguments", p.at("input").dump_safe()}}}});
                else if (type == "thinking")
                    thought += p.value("thinking", "");
                else {
                    auto a = common_json::array();
                    a.push_back(p);
                    for (auto &q : text_parts(a, true))
                        parts.push_back(q);
                }
            }
            if (!parts.empty() || !calls.empty() || !thought.empty()) {
                common_json msg = {{"role", m.at("role")}, {"content", parts}};
                if (!calls.empty())
                    msg["tool_calls"] = calls;
                if (!thought.empty())
                    msg["reasoning_content"] = thought;
                messages.push_back(msg);
            }
        }
    } else {
        if (in.contains("previous_response_id"))
            throw std::runtime_error(
                "Native Responses is stateless; send input history instead of previous_response_id");
        if (in.value("store", false))
            throw std::runtime_error("Native Responses supports store:false only");
        if (in.contains("instructions"))
            messages.push_back({{"role", "system"}, {"content", in.at("instructions")}});
        auto input = in.at("input");
        std::string thought;
        if (input.is_string())
            messages.push_back({{"role", "user"}, {"content", input}});
        else
            for (const auto &m : input) {
                auto type = m.value("type", "message");
                if (type == "reasoning") {
                    thought += replay(m);
                    continue;
                }
                if (type == "function_call") {
                    common_json call = {
                        {"id", m.at("call_id")},
                        {"type", "function"},
                        {"function", {{"name", m.at("name")}, {"arguments", m.at("arguments")}}}};
                    if (!messages.empty() && messages.back().value("role", "") == "assistant" &&
                        messages.back().contains("tool_calls"))
                        messages.back()["tool_calls"].push_back(call);
                    else {
                        common_json msg = {{"role", "assistant"},
                                           {"content", ""},
                                           {"tool_calls", common_json::array({call})}};
                        if (!thought.empty()) {
                            msg["reasoning_content"] = thought;
                            thought.clear();
                        }
                        messages.push_back(msg);
                    }
                } else if (type == "function_call_output")
                    messages.push_back(
                        {{"role", "tool"}, {"tool_call_id", m.at("call_id")}, {"content", m.at("output")}});
                else if (type == "message") {
                    common_json msg = {{"role", m.value("role", "user")},
                                       {"content", text_parts(m.at("content"))}};
                    if (msg.at("role") == "assistant" && !thought.empty()) {
                        msg["reasoning_content"] = thought;
                        thought.clear();
                    }
                    messages.push_back(msg);
                } else
                    throw std::runtime_error("Unsupported Responses item: " + type);
            }
        if (in.contains("reasoning"))
            out["reasoning_effort"] = in.at("reasoning").value("effort", "medium");
    }
    if (in.contains("tools")) {
        common_json tools = common_json::array();
        for (const auto &t : in.at("tools")) {
            if (!anthropic && t.value("type", "") != "function")
                throw std::runtime_error("Native runtime supports client-side function tools only");
            tools.push_back({{"type", "function"},
                             {"function",
                              {{"name", t.at("name")},
                               {"description", t.value("description", "")},
                               {"parameters", t.value(anthropic ? "input_schema" : "parameters",
                                                      common_json::object())}}}});
        }
        out["tools"] = tools;
    }
    if (in.contains("tool_choice")) {
        auto c = in.at("tool_choice");
        if (c.is_string())
            out["tool_choice"] = c;
        else if (c.value("type", "") == "any")
            out["tool_choice"] = "required";
        else if (c.value("type", "") == "auto")
            out["tool_choice"] = "auto";
        else if (c.value("type", "") == "none")
            out["tool_choice"] = "none";
        else if (c.value("type", "") == "tool" || c.value("type", "") == "function")
            out["tool_choice"] = {{"type", "function"}, {"function", {{"name", c.at("name")}}}};
        else
            throw std::runtime_error("Unsupported tool choice");
    }
    out["messages"] = messages;
    return out;
}
inline common_json anthropic_message(const std::string &id, const std::string &model, const common_json &msg,
                                     long long input, long long output, const std::string &finish) {
    common_json content = common_json::array();
    auto thought = msg.value("reasoning_content", "");
    if (!thought.empty())
        content.push_back({{"type", "thinking"}, {"thinking", thought}});
    auto text = msg.value("content", "");
    if (!text.empty())
        content.push_back({{"type", "text"}, {"text", text}});
    if (msg.contains("tool_calls"))
        for (const auto &t : msg.at("tool_calls")) {
            auto f = t.at("function");
            auto args = common_json::parse_no_throw(f.at("arguments").get<std::string>());
            if (!args.is_object())
                throw std::runtime_error("Model produced invalid function arguments");
            content.push_back(
                {{"type", "tool_use"}, {"id", t.at("id")}, {"name", f.at("name")}, {"input", args}});
        }
    return {{"id", id},
            {"type", "message"},
            {"role", "assistant"},
            {"model", model},
            {"content", content},
            {"stop_reason", finish == "tool_calls" ? "tool_use"
                            : finish == "length"   ? "max_tokens"
                                                   : "end_turn"},
            {"stop_sequence", nullptr},
            {"usage", {{"input_tokens", input}, {"output_tokens", output}}}};
}
inline common_json response_object(const std::string &id, const std::string &model, const common_json &msg,
                                   long long input, long long output, const std::string &finish) {
    common_json items = common_json::array();
    auto thought = msg.value("reasoning_content", "");
    if (!thought.empty())
        items.push_back(
            {{"id", id + "_reason"},
             {"type", "reasoning"},
             {"summary", common_json::array({common_json{{"type", "summary_text"}, {"text", thought}}})},
             {"encrypted_content", "strata.r1:" + base64(common_json{{"text", thought}}.dump_safe())}});
    auto text = msg.value("content", "");
    if (!text.empty())
        items.push_back(
            {{"id", id + "_msg"},
             {"type", "message"},
             {"status", "completed"},
             {"role", "assistant"},
             {"content",
              common_json::array({common_json{
                  {"type", "output_text"}, {"text", text}, {"annotations", common_json::array()}}})}});
    if (msg.contains("tool_calls"))
        for (const auto &t : msg.at("tool_calls")) {
            auto f = t.at("function");
            items.push_back({{"id", id + "_" + t.at("id").get<std::string>()},
                             {"type", "function_call"},
                             {"call_id", t.at("id")},
                             {"name", f.at("name")},
                             {"arguments", f.at("arguments")},
                             {"status", "completed"}});
        }
    return {{"id", id},
            {"object", "response"},
            {"model", model},
            {"status", finish == "length" ? "incomplete" : "completed"},
            {"output", items},
            {"usage", {{"input_tokens", input}, {"output_tokens", output}, {"total_tokens", input + output}}},
            {"error", nullptr},
            {"incomplete_details",
             finish == "length" ? common_json{{"reason", "max_output_tokens"}} : common_json(nullptr)}};
}
} // namespace native_api
