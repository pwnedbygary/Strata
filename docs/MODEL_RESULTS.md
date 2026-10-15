# Current local model results

October 14, 2026. RX 9070 XT 16 GiB, Ryzen 7800X3D, 32 GB RAM. Later tuning
runs use JEDEC 4800 MT/s; older short tests are historical. These are individual
measurements with different prompts and output lengths, not a model quality ranking.
Profile settings have changed since some runs. A configured limit is not a filled test.

| Current profile | Measured output tokens/s | Measurement and limits |
| --- | ---: | --- |
| flash-iq3 | 10.9 fresh / 13.8 cached | Latest pre-port 8,186-token coding test, MTP off and 9 GiB RAM tier; 354.6 prefill. Live preset instead has MTP and 11 GiB RAM. |
| swift27-iq3-xxs | 34.0 | Historical short text smoke; not a filled 256K test. |
| swift27-iq3-xxs-vision | 33.5 | Two short screenshot responses. |
| swift27-iq3-s | 13.6 | Historical short text smoke; the newly tuned separate non-MTP GGUF has not been measured separately. |
| swift27-iq3-s-vision | 14.5–14.7 | Historical short screenshot responses; new tuning has no separate result for this GGUF. |
| swift27-iq3-s-mtp | 33.9 / 31.4 cached at 8K; 17.4 / 16.2 at 32K | One draft, aggressive 1536 MiB reserve, 4K KV growth. Current reserve is 2048 MiB, so these are not measurements of the exact live preset. |
| swift27-iq3-s-mtp-vision | 35.7–37.7 | Two changed-image requests at about 4K, one draft, aggressive reserve. |
| swift27-iq3-s-mtp2-vision | 31.3 / 27.9 cached | 8K coding, two drafts, 2048 MiB reserve, 847.2 prefill. Screenshot responses 32.3–32.4; worker subsequently stopped at the physical VRAM guard. More headroom needs validation. |
| saluki27-abliterated-vision | 35.9–36.0 | Two short screenshot responses, drafting off. |
| saluki27-abliterated-mtp-vision | 49.0–49.5 short; 32.7 / 31.3 cached at 32K; 16.6 / 15.7 at 64K | Short screenshot test and separate text coding-context tests. Tuned prefill 456.9 at 32K and 245.0 at 64K. |

Swift's embedded-MTP file with drafting **disabled** reached 31.2 / 30.4 output tokens/s
at about 8K with aggressive memory fit. That result belongs to the MTP-containing GGUF,
not the separate non-MTP Swift IQ3_S file. The aggressive two-draft trial peaked at 43.0
fresh / 29.7 cached with only 104 MiB physical VRAM free; it is not a desktop-safe preset.

The removed fixed-8K Swift MTP profiles peaked at 50.8 (IQ3_XXS, 55 output tokens) and
52.2 (IQ3_S, 79 output tokens). Those short replies do not establish sustained speed
for long coding conversations. Removed Tiel, Cyber Tiel, original Saluki and Qwen 0.8B
profiles are excluded here. Original GGUF files were not deleted by profile removal.

The opt-in Saluki 128K test completed 131,020 input tokens at **243.1 prefill / 18.6
answer / 16.6 cached review tok/s**, passing 13 code checks and three distant retrieval
checks. This uses new engine flags and two drafts; it is not a measurement of the older
preset in the table. [Full configuration and saved results](SALUKI_128K.md).

Flash has a 128K configured ceiling. Dense profiles have an adaptive 256K ceiling;
no filled 256K dense coding or image-quality result is claimed. The larger-context
Saluki measurements support a performance preference for that model on this machine,
not a universal claim about code quality. Swift and Saluki still need matched broader
coding evaluations to compare quality.

Sources: [Swift tuning](SWIFT_IQ3_S_TUNING.md), [dense prefill tuning](PREFILL_TUNING.md),
[screenshot checks](SCREENSHOT_INPUT.md), [historical profiles](LOCAL_MODEL_PROFILES.md),
[Gyro investigation and latest QFN paired results](FLASH_GYRO_INVESTIGATION.md).
