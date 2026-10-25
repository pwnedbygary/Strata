#include "api_errors.hpp"
#include <cassert>
#include <string>

int main() {
    using namespace native_api_error;
    const auto oversized = context_window_message(309367, 131072);
    assert(oversized ==
           "This request contains 309,367 input tokens, exceeding this model's 131,072-token context window. "
           "Remove older conversation messages or start a new chat, or load a profile with a larger context "
           "window.");
    assert(code_for(oversized) == "context_length_exceeded");
    assert(status_for(oversized, 500) == 400);
    assert(status_for("Insufficient physical VRAM headroom; request refused before inference", 500) == 503);
    assert(code_for("Insufficient physical VRAM headroom; request refused before inference") == "insufficient_vram");
    assert(client_message("the engine exited during the request", 0, 0).find("Reload the model") !=
           std::string::npos);
    const auto near_limit = context_window_message(131066, 131072);
    assert(near_limit.find("leaves too little room") != std::string::npos);
}
