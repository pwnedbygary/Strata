void handle_compat(const httplib::Request &req, httplib::Response &res, bool anthropic, bool count = false) {
    auto input = common_json::parse_no_throw(req.body);
    auto p = std::make_shared<Prepared>();
    try {
        auto body = native_api::chat_request(input, anthropic);
        std::string error;
        if (count)
            body["max_tokens"] = 1;
        if (!prepare(body, *p, error, count))
            return json_error(res, 400, error, "invalid_request_error");
        if (count) {
            res.set_content(common_json{{"input_tokens", (long long)p->ids.size()}}.dump_safe(),
                            "application/json");
            return;
        }
    } catch (const std::exception &e) {
        return json_error(res, 400, e.what(), "invalid_request_error");
    }
    std::string id = make_id();
    p->request_id = id;
    if (!p->stream) {
        common_chat_msg msg;
        auto r = run(*p, msg, [](auto &) { return true; });
        if (!r.ok)
            return json_error(res, r.error.rfind("Insufficient", 0) == 0 ? 503 : 500, r.error,
                              r.error.rfind("Insufficient", 0) == 0 ? "resource_exhausted" : "server_error");
        try {
            auto out = anthropic
                           ? native_api::anthropic_message(id, g_model_name, msg.to_json_oaicompat(),
                                                           r.prompt_n, r.produced, finish_reason(r, msg))
                           : native_api::response_object(id, g_model_name, msg.to_json_oaicompat(),
                                                         r.prompt_n, r.produced, finish_reason(r, msg));
            res.set_content(out.dump_safe(), "application/json");
        } catch (const std::exception &e) {
            return json_error(res, 500, e.what(), "server_error");
        }
        return;
    }
    res.set_header("Cache-Control", "no-cache");
    res.set_header("X-Accel-Buffering", "no");
    res.set_chunked_content_provider("text/event-stream", [this, p, id, anthropic](size_t,
                                                                                   httplib::DataSink &sink) {
        long long sequence = 0;
        bool ok = true;
        auto event = [&](const std::string &type, common_json value) {
            value["type"] = type;
            if (!anthropic)
                value["sequence_number"] = sequence++;
            auto s = "event: " + type + "\ndata: " + value.dump_safe() + "\n\n";
            ok = ok && sink.write(s.data(), s.size());
            return ok;
        };
        auto empty = common_json{{"content", ""}};
        if (anthropic) {
            auto m = native_api::anthropic_message(id, g_model_name, empty, p->ids.size(), 0, "stop");
            m["stop_reason"] = nullptr;
            event("message_start", {{"message", m}});
        } else {
            auto r = native_api::response_object(id, g_model_name, empty, p->ids.size(), 0, "stop");
            r["status"] = "in_progress";
            event("response.created", {{"response", r}});
            event("response.in_progress", {{"response", r}});
        }
        std::map<std::string, int> indices;
        common_json items = common_json::array();
        auto block = [&](const std::string &key, const common_json &item) {
            auto it = indices.find(key);
            if (it != indices.end())
                return it->second;
            int index = (int)indices.size();
            indices[key] = index;
            items.push_back(item);
            if (anthropic)
                event("content_block_start", {{"index", index}, {"content_block", item}});
            else {
                event("response.output_item.added", {{"output_index", index}, {"item", item}});
                if (key == "text")
                    event("response.content_part.added",
                          {{"output_index", index},
                           {"item_id", id + "_msg"},
                           {"content_index", 0},
                           {"part",
                            {{"type", "output_text"}, {"text", ""}, {"annotations", common_json::array()}}}});
                if (key == "reason")
                    event("response.reasoning_summary_part.added",
                          {{"output_index", index},
                           {"item_id", id + "_reason"},
                           {"summary_index", 0},
                           {"part", {{"type", "summary_text"}, {"text", ""}}}});
            }
            return index;
        };
        common_chat_msg final;
        auto r = run(
            *p, final,
            [&](const std::vector<common_chat_msg_diff> &diffs) {
                for (const auto &d : diffs) {
                    if (!d.content_delta.empty()) {
                        int i = block("text", anthropic ? common_json{{"type", "text"}, {"text", ""}}
                                                        : common_json{{"id", id + "_msg"},
                                                                      {"type", "message"},
                                                                      {"role", "assistant"},
                                                                      {"status", "in_progress"},
                                                                      {"content", common_json::array()}});
                        if (anthropic)
                            event("content_block_delta",
                                  {{"index", i},
                                   {"delta", {{"type", "text_delta"}, {"text", d.content_delta}}}});
                        else
                            event("response.output_text.delta", {{"item_id", id + "_msg"},
                                                                 {"output_index", i},
                                                                 {"content_index", 0},
                                                                 {"delta", d.content_delta}});
                    }
                    if (!d.reasoning_content_delta.empty()) {
                        int i =
                            block("reason", anthropic ? common_json{{"type", "thinking"}, {"thinking", ""}}
                                                      : common_json{{"id", id + "_reason"},
                                                                    {"type", "reasoning"},
                                                                    {"summary", common_json::array()}});
                        if (anthropic)
                            event("content_block_delta",
                                  {{"index", i},
                                   {"delta",
                                    {{"type", "thinking_delta"}, {"thinking", d.reasoning_content_delta}}}});
                        else
                            event("response.reasoning_summary_text.delta",
                                  {{"item_id", id + "_reason"},
                                   {"output_index", i},
                                   {"summary_index", 0},
                                   {"delta", d.reasoning_content_delta}});
                    }
                    if (d.tool_call_index != std::string::npos) {
                        auto &t = d.tool_call_delta;
                        std::string key = "tool" + std::to_string(d.tool_call_index);
                        int i = block(key, anthropic ? common_json{{"type", "tool_use"},
                                                                   {"id", t.id},
                                                                   {"name", t.name},
                                                                   {"input", common_json::object()}}
                                                     : common_json{{"id", id + "_" + t.id},
                                                                   {"type", "function_call"},
                                                                   {"call_id", t.id},
                                                                   {"name", t.name},
                                                                   {"arguments", ""},
                                                                   {"status", "in_progress"}});
                        if (anthropic)
                            event("content_block_delta",
                                  {{"index", i},
                                   {"delta", {{"type", "input_json_delta"}, {"partial_json", t.arguments}}}});
                        else
                            event("response.function_call_arguments.delta",
                                  {{"item_id", items.at(i).at("id")},
                                   {"output_index", i},
                                   {"delta", t.arguments}});
                    }
                }
                return ok;
            },
            [&] {
                static std::string keep = ": keepalive\n\n";
                ok = ok && sink.is_writable() && sink.write(keep.data(), keep.size());
                return ok;
            });
        if (ok && r.ok) {
            auto msg = final.to_json_oaicompat();
            if (anthropic) {
                for (size_t i = 0; i < items.size(); i++)
                    event("content_block_stop", {{"index", (int)i}});
                auto out = native_api::anthropic_message(id, g_model_name, msg, r.prompt_n, r.produced,
                                                         finish_reason(r, final));
                event("message_delta",
                      {{"delta", {{"stop_reason", out.at("stop_reason")}, {"stop_sequence", nullptr}}},
                       {"usage", {{"output_tokens", r.produced}}}});
                event("message_stop", common_json::object());
            } else {
                auto out = native_api::response_object(id, g_model_name, msg, r.prompt_n, r.produced,
                                                       finish_reason(r, final));
                // Reorder final output to the indices announced while streaming.
                common_json ordered = common_json::array();
                for (size_t i = 0; i < items.size(); i++)
                    for (const auto &item : out.at("output"))
                        if (item.at("id") == items.at(i).at("id")) {
                            if (item.value("type", "") == "message") {
                                auto part = item.at("content").at(0);
                                event("response.output_text.done", {{"item_id", item.at("id")},
                                                                    {"output_index", (int)i},
                                                                    {"content_index", 0},
                                                                    {"text", part.at("text")}});
                                event("response.content_part.done", {{"item_id", item.at("id")},
                                                                     {"output_index", (int)i},
                                                                     {"content_index", 0},
                                                                     {"part", part}});
                            }
                            if (item.value("type", "") == "function_call")
                                event("response.function_call_arguments.done",
                                      {{"item_id", item.at("id")},
                                       {"output_index", (int)i},
                                       {"arguments", item.at("arguments")}});
                            if (item.value("type", "") == "reasoning") {
                                auto part = item.at("summary").at(0);
                                event("response.reasoning_summary_text.done", {{"item_id", item.at("id")},
                                                                               {"output_index", (int)i},
                                                                               {"summary_index", 0},
                                                                               {"text", part.at("text")}});
                                event("response.reasoning_summary_part.done", {{"item_id", item.at("id")},
                                                                               {"output_index", (int)i},
                                                                               {"summary_index", 0},
                                                                               {"part", part}});
                            }
                            event("response.output_item.done", {{"output_index", (int)i}, {"item", item}});
                            ordered.push_back(item);
                        }
                out["output"] = ordered;
                event(out.at("status") == "incomplete" ? "response.incomplete" : "response.completed",
                      {{"response", out}});
            }
        } else if (ok) {
            event("error", {{"error", {{"type", "server_error"}, {"message", r.error}}}});
        }
        sink.done();
        return true;
    });
}
