#pragma once
#include "json.h"
namespace native_sampling {
// Profile defaults fill omissions; explicit request values, including zero, win.
inline common_json apply(const common_json &cfg, common_json body) {
    auto defaults = cfg.value("sampling", common_json::object());
    for (const char *key : {"temperature","top_p","top_k","min_p","presence_penalty","frequency_penalty","repeat_penalty"})
        if (!body.contains(key) && defaults.contains(key)) body[key] = defaults[key];
    return body;
}
}
