#pragma once

#include <algorithm>
#include <string>

namespace native_api_error {
inline std::string grouped(long long value) {
    std::string digits = std::to_string(value);
    for (long long i = static_cast<long long>(digits.size()) - 3; i > 0; i -= 3)
        digits.insert(static_cast<size_t>(i), ",");
    return digits;
}

inline std::string context_window_message(long long prompt_tokens, long long context_tokens) {
    const auto prompt = grouped(prompt_tokens);
    const auto context = grouped(context_tokens);
    if (prompt_tokens > context_tokens)
        return "This request contains " + prompt + " input tokens, exceeding this model's " + context +
               "-token context window. Remove older conversation messages or start a new chat, or load a profile "
               "with a larger context window.";
    return "This request uses " + prompt + " of " + context +
           " context tokens and leaves too little room to start generation. Shorten the conversation or load a "
           "profile with a larger context window.";
}

inline std::string code_for(const std::string &message) {
    if (message.find("context window") != std::string::npos ||
        message.find("exceeds the available context size") != std::string::npos ||
        message.find("does not fit the context") != std::string::npos)
        return "context_length_exceeded";
    if (message.find("Output token limit") != std::string::npos)
        return "invalid_output_limit";
    if (message.find("Insufficient available system RAM") != std::string::npos)
        return "insufficient_system_ram";
    if (message.find("Insufficient physical VRAM") != std::string::npos)
        return "insufficient_vram";
    if (message.find("Insufficient process memory budget") != std::string::npos)
        return "insufficient_process_memory";
    if (message.find("engine is not running") != std::string::npos ||
        message.find("engine exited during the request") != std::string::npos)
        return "model_worker_unavailable";
    if (message.find("response formatter failed") != std::string::npos)
        return "response_format_error";
    if (message.find("request body is not valid JSON") != std::string::npos)
        return "invalid_json";
    if (message.find("messages array") != std::string::npos)
        return "messages_required";
    return "internal_error";
}

inline std::string client_message(const std::string &message, long long prompt_tokens,
                                 long long context_tokens) {
    if ((message.find("exceeds the available context size") != std::string::npos ||
         message.find("does not fit the context") != std::string::npos) && prompt_tokens > 0 && context_tokens > 0)
        return context_window_message(prompt_tokens, context_tokens);
    if (message == "the engine is not running" || message == "the engine exited during the request")
        return "The model worker stopped before completing this request. Reload the model; if it stops again, "
               "check the Strata server log for the worker's exit reason.";
    if (message.find("Insufficient available system RAM") != std::string::npos)
        return message + ". Close memory-heavy applications or reduce the model/context size, then retry.";
    if (message.find("Insufficient physical VRAM") != std::string::npos)
        return message + ". Close GPU-heavy applications or reduce GPU memory use, then retry.";
    if (message.find("Insufficient process memory budget") != std::string::npos)
        return message + ". Reduce the model memory budget or close memory-heavy applications, then retry.";
    if (message.find("response formatter failed") != std::string::npos)
        return "Strata could not format the model response: " + message.substr(std::string("response formatter failed: ").size());
    return message;
}

inline int status_for(const std::string &message, int fallback) {
    const std::string code = code_for(message);
    if (code == "context_length_exceeded" || code == "invalid_output_limit" || code == "invalid_json" ||
        code == "messages_required")
        return 400;
    if (code == "insufficient_system_ram" || code == "insufficient_vram" ||
        code == "insufficient_process_memory" || code == "model_worker_unavailable")
        return 503;
    return fallback;
}
} // namespace native_api_error
