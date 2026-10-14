# Local-profile smoke tests

October 14, 2026, RX 9070 XT 16 GiB / Ryzen 7800X3D / 32 GB RAM / ROCm 7.2.
[Profiles, settings, MTP on/off results and limitations](../../../docs/LOCAL_MODEL_PROFILES.md).

The `*-result.json` files record the initial adaptive Swift trials and the rejected
adaptive 0.8B trial. The 0.8B geometry cannot use the adaptive 27B path.
The `*-mtp-test.json` files record fixed 8K MTP trials and the initial 0.8B response
whose direct answer was classified as reasoning. The `*-8k-off.json` files record the
same-8K MTP-off comparison; the 0.8B entry uses its corrected 4K, reasoning-off profile.
Failed attempts are retained alongside the corrected results.

[Exact-message comparison and rates](mtp-comparison.json).
The MTP draft token counts are actual engine timings, not inferred from filenames.
No claims of full-context quality, long-output stability or numerical reference parity
are made from this short smoke prompt. Tiel/Cyber Tiel were rejected by preflight inspection;
no inference was attempted with their unsupported expert formats / memory requirement.
