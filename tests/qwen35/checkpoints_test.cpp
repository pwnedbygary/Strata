// qwen35/checkpoints.hpp: where a dense prompt read takes snapshots, which one a request resumes from, which one leaves
// (synthetic: no model, no GPU).
#include "strata/qwen35/checkpoints.hpp"

#include <cstdio>
#include <vector>

using strata::qwen35::checkpoints::eviction_victim;
using strata::qwen35::checkpoints::pick;
using strata::qwen35::checkpoints::snapshot_cells;

using Cells = std::vector<int64_t>;
using Pictures = std::vector<std::pair<int64_t, int64_t>>;

static int fails = 0;
#define CHECK(c) do { if (!(c)) { std::printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); ++fails; } } while (0)

int main() {
    // a read shorter than a chunk: only the prompt's end (the mark's chunk end is the read's start)
    CHECK(snapshot_cells(0, 1000, 2048, {0, 995}, {}) == (Cells{1000}));
    // 6,000 cells in chunks of 2,048: the chunk end before the reply's <|im_start|>, and the end
    CHECK(snapshot_cells(0, 6000, 2048, {0, 5995}, {}) == (Cells{4096, 6000}));
    // the same chunk end from two marks is taken once
    CHECK(snapshot_cells(0, 6000, 2048, {5000, 5995}, {}) == (Cells{4096, 6000}));
    // 4 chunks or more: the chunk ends nearest a quarter (5,000 -> 4,096), a half (10,000 -> 10,240) and three
    // quarters (15,000 -> 14,336), ascending with the mark's (18,432) and the end
    CHECK(snapshot_cells(0, 20000, 2048, {100, 19990}, {}) == (Cells{4096, 10240, 14336, 18432, 20000}));
    // a resumed read: its chunks start at its first cell
    CHECK(snapshot_cells(3000, 3500, 2048, {3100, 3495}, {}) == (Cells{3500}));
    CHECK(snapshot_cells(1000, 9300, 2048, {}, {}) == (Cells{3048, 5096, 7144, 9300}));
    // never inside a picture; its first cell is outside it
    CHECK(snapshot_cells(0, 6000, 2048, {5995}, Pictures{{4000, 260}}) == (Cells{6000}));
    CHECK(snapshot_cells(0, 6000, 2048, {5995}, Pictures{{4096, 100}}) == (Cells{4096, 6000}));
    CHECK(snapshot_cells(0, 6000, 2048, {5995}, Pictures{{3996, 100}}) == (Cells{4096, 6000}));
    // nothing to read, or no chunk size
    CHECK(snapshot_cells(500, 500, 2048, {}, {}).empty());
    CHECK(snapshot_cells(0, 500, 0, {}, {}).empty());

    // the longest snapshot at or below the shared cells and below the prompt's length, or at it with its logits
    const Cells cells{4096, 6000};
    CHECK(pick(cells, {false, true}, 6000, 6000) == 1);
    CHECK(pick(cells, {false, false}, 6000, 6000) == 0);
    CHECK(pick(cells, {false, true}, 6000, 6500) == 1);
    CHECK(pick(cells, {false, true}, 5000, 7000) == 0);
    CHECK(pick(cells, {false, true}, 4000, 7000) == -1);
    CHECK(pick({4096}, {false}, 4096, 4096) == -1);
    CHECK(pick({}, {}, 4096, 9000) == -1);

    // cap 8, nine evenly spread: the shortest and the 4 most recent stay; of the rest (equal gaps) the oldest leaves
    CHECK(eviction_victim({2048, 4096, 6144, 8192, 10240, 12288, 14336, 16384, 18000}, {1, 2, 3, 4, 5, 6, 7, 8, 9},
                          8) == 1);
    // the one whose removal leaves the shorter gap leaves: 5,500 (5,000 -> 9,000) before 5,000 (1,000 -> 5,500)
    CHECK(eviction_victim({1000, 5000, 5500, 9000, 20000}, {1, 2, 3, 4, 5}, 4) == 2);
    // the shortest stays though it is the least recently used, and so do the 2 most recent; of 9,000 and 20,000 the
    // longest leaves (the gap it leaves is 11,000, 9,000's would be 14,500)
    CHECK(eviction_victim({1000, 5000, 5500, 9000, 20000}, {1, 5, 4, 3, 2}, 4) == 4);
    // the longest leaves when it is close to the one before it and not among the most recent
    CHECK(eviction_victim({100, 2000, 2100, 2200}, {1, 4, 2, 3}, 3) == 3);
    // below a cap of 3: the least recently used, the shortest included
    CHECK(eviction_victim({100, 200, 300}, {5, 1, 9}, 2) == 1);
    CHECK(eviction_victim({100, 200}, {1, 2}, 1) == 0);
    CHECK(eviction_victim({100, 200}, {2, 1}, 1) == 1);

    if (fails == 0) std::printf("qwen35_checkpoints_test: ok\n");
    return fails == 0 ? 0 : 1;
}
