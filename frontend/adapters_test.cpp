#include "adapters.hpp"
#include "sampling.hpp"
#include <cassert>
#include <cstdio>
int main() {
    common_json cfg={{"sampling",{{"temperature",1.0},{"top_p",0.95},{"presence_penalty",1.1}}}};
    auto defaults=native_sampling::apply(cfg,common_json::object());assert(defaults["temperature"]==1.0);
    auto explicit_zero=native_sampling::apply(cfg,{{"temperature",0},{"top_p",0.8}});assert(explicit_zero["temperature"]==0&&explicit_zero["top_p"]==0.8);
    auto adapted=native_api::chat_request({{"messages",common_json::array()},{"min_p",0.0},{"presence_penalty",1.1},{"repeat_penalty",1.0}},true);
    assert(adapted["presence_penalty"]==1.1&&adapted.contains("min_p")&&adapted["repeat_penalty"]==1.0);

    auto a = native_api::chat_request(
        common_json::parse(
            R"({"messages":[{"role":"user","content":[{"type":"text","text":"hello"}]}],"thinking":{"type":"disabled"},"max_tokens":32})"),
        true);
    assert(a.at("reasoning_effort") == "none");
    assert(a.at("messages").size() == 1);
    auto r = native_api::chat_request(
        common_json::parse(
            R"({"input":[{"type":"function_call","call_id":"a","name":"read","arguments":"{}"},{"type":"function_call_output","call_id":"a","output":"file"}],"max_output_tokens":128,"store":false})"),
        false);
    assert(r.at("max_tokens").get<int>() == 128);
    assert(r.at("messages").size() == 2);
    assert(r.at("messages").at(1).at("role") == "tool");
    for (const char *bad :
         {R"({"input":"x","previous_response_id":"remote"})", R"({"input":"x","store":true})",
          R"({"input":"x","tools":[{"type":"web_search"}]})"}) {
        bool rejected = false;
        try {
            native_api::chat_request(common_json::parse(bad), false);
        } catch (...) {
            rejected = true;
        }
        assert(rejected);
    }
    auto m = common_json::parse(
        R"({"content":"done","tool_calls":[{"id":"call_a","type":"function","function":{"name":"read","arguments":"{\"path\":\"x\"}"}}]})");
    auto am = native_api::anthropic_message("id", "local", m, 12, 8, "tool_calls");
    assert(am.at("stop_reason") == "tool_use");
    assert(am.at("content").at(1).at("input").at("path") == "x");
    auto rr = native_api::response_object("id", "local", m, 12, 8, "tool_calls");
    assert(rr.at("output").size() == 2);
    assert(rr.at("usage").at("total_tokens").get<int>() == 20);
    auto reasoning_message = common_json{{"content", "answer"}, {"reasoning_content", "Plan: café, then verify."}};
    auto replay_response = native_api::response_object("id", "local", reasoning_message, 12, 8, "stop");
    assert(native_api::replay(replay_response.at("output").at(0)) == "Plan: café, then verify.");
    auto replay_input = common_json{{"input", replay_response.at("output")}, {"store", false}};
    auto replay_chat = native_api::chat_request(replay_input, false);
    assert(replay_chat.at("messages").at(0).at("reasoning_content") == "Plan: café, then verify.");
    bool url_rejected = false;
    try {
        native_api::text_parts(
            common_json::parse(
                R"([{"type":"image","source":{"type":"url","url":"https://example.invalid/x.png"}}])"),
            true);
    } catch (...) {
        url_rejected = true;
    }
    assert(url_rejected);
    puts("PASS: stateless adapters, tool history, usage, thinking controls, no hosted tools/URL fetches");
}
