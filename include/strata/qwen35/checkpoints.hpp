// include/strata/qwen35/checkpoints.hpp - the dense engine's conversation checkpoints (STRATA_Q35_CHECKPOINTS=N): the
// cells at which a prompt read takes a snapshot, the snapshot a request resumes from, and the one that leaves when more
// than N are held.
//
// A snapshot is the session's recurrent state at a cell - each GDN layer's conv and S, and the MTP seed (~150 MiB on
// the 27B models) - kept in host RAM.  The K / V cells need no copy: they are stored by position, and a read resumed at
// cell p writes only cells at p or after.  So the engine keeps only the snapshots whose cells still hold the session's
// tokens: a resume at p drops every snapshot past p, a reset drops them all, and the held snapshots lie on one branch
// of the conversation, each a prefix of the next (as with Flash-Next's conversation cache, program/conv_cache.hpp).
//
// Snapshots are taken only where a read's chunk ends, so taking one never changes the read, and a read resumed at a
// chunk end goes on in the chunks the read that never stopped there used.
#pragma once

#include <cstddef>
#include <cstdint>
#include <utility>
#include <vector>

namespace strata::qwen35::checkpoints {

/// The cells, ascending, at which a read of the cells [r, n) in chunks of t cells takes a snapshot:
///   * n, the prompt's end (that snapshot keeps the last logits, so the same prompt sent again decodes at once);
///   * the last chunk end at or before each cell of `marks` (the engine passes its last two <|im_start|> cells: an
///     edited last message, or the reply sent back in another form, resumes there);
///   * for a read of 4 chunks or more, the chunk ends nearest a quarter, a half and three quarters of it (an edit
///     further back resumes from one of them).
/// Never r itself, and never a cell strictly inside a picture (`pictures`: first cell, cell count).
inline std::vector<int64_t> snapshot_cells(int64_t r, int64_t n, int64_t t, const std::vector<int64_t>& marks,
                                           const std::vector<std::pair<int64_t, int64_t>>& pictures) {
    std::vector<int64_t> out;
    if (n <= r || t <= 0) return out;
    auto add = [&](int64_t c) {
        if (c <= r || c > n) return;
        for (const auto& p : pictures)
            if (c > p.first && c < p.first + p.second) return;
        for (int64_t o : out)
            if (o == c) return;
        out.push_back(c);
    };
    for (int64_t b : marks)
        if (b > r) {
            const int64_t c = r + (b - r) / t * t;
            if (c < n) add(c);
        }
    if (n - r >= 4 * t)
        for (int q = 1; q <= 3; ++q) {
            const int64_t target = r + (n - r) * q / 4;
            const int64_t c = r + (target - r + t / 2) / t * t;
            if (c < n) add(c);
        }
    add(n);
    for (size_t i = 1; i < out.size(); ++i)   // a handful of cells: insertion sort
        for (size_t j = i; j > 0 && out[j - 1] > out[j]; --j) std::swap(out[j - 1], out[j]);
    return out;
}

/// The index of the snapshot a request resumes from, -1 for none: the longest one at or below `m` - the cells its
/// prompt shares with the held tokens - and below `n`, its length; or at n, when that snapshot kept its logits.
/// `cells` ascending.
inline int pick(const std::vector<int64_t>& cells, const std::vector<bool>& has_logits, int64_t m, int64_t n) {
    for (size_t i = cells.size(); i-- > 0;) {
        const int64_t c = cells[i];
        if (c > m || c > n) continue;
        if (c < n || has_logits[i]) return (int) i;
    }
    return -1;
}

/// The index of the snapshot to drop when more than `cap` are held (`cells` ascending, `stamps` their last-use stamps:
/// a snapshot's stamp advances when it is taken and when a request resumes from it).  With a cap of 3 or more:
///   * the shortest (index 0) stays: it is the point every request so far has shared - in practice the end of a
///     client's system prompt - and a new chat of the same client resumes from it;
///   * the cap / 2 most recently used of the others stay: the next turn resumes from the last prompt end, an edit a
///     few turns back from one before it;
///   * of the rest, the one whose removal leaves the shortest gap between its neighbours leaves (the older on a
///     tie), so the snapshots stay spread over the conversation and an edit far back re-reads about one gap at most.
/// With nothing of the rest, or a cap below 3, the least recently used leaves (never the shortest with a cap of 3+).
inline size_t eviction_victim(const std::vector<int64_t>& cells, const std::vector<uint64_t>& stamps, size_t cap) {
    const size_t n = cells.size();
    auto lru = [&](size_t from) {
        size_t v = from;
        for (size_t i = from + 1; i < n; ++i)
            if (stamps[i] < stamps[v]) v = i;
        return v;
    };
    if (n < 2 || cap < 3) return lru(0);
    std::vector<bool> kept(n, false);
    kept[0] = true;
    for (size_t k = 0; k < cap / 2; ++k) {   // the most recently used of the others
        size_t best = n;
        for (size_t i = 1; i < n; ++i)
            if (!kept[i] && (best == n || stamps[i] > stamps[best])) best = i;
        if (best == n) break;
        kept[best] = true;
    }
    size_t v = n;
    int64_t v_gap = 0;
    for (size_t i = 1; i < n; ++i) {
        if (kept[i]) continue;
        const int64_t gap = (i + 1 < n ? cells[i + 1] : cells[i]) - cells[i - 1];
        if (v == n || gap < v_gap || (gap == v_gap && stamps[i] < stamps[v])) {
            v = i;
            v_gap = gap;
        }
    }
    return v < n ? v : lru(1);
}

}  // namespace strata::qwen35::checkpoints
