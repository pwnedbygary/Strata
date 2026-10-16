# Local model library

Real GGUF files are arranged as `model-name/quantization/file.gguf`. Swift's
embedded-MTP and plain files share their quantization folder. Vision projectors
live under the model's `vision/F16` folder; the shared BF16 projector has its own
`shared-vision/BF16` directory. Prepared Strata expert packs remain separate.

Saved runner profiles and the external llama.cpp presets.ini point directly to
these organized files. Compatibility aliases were removed; no weight copies were
created. Original configuration backups are kept locally. The external llama.cpp
presets now live in `models/presets.ini`; measured performance tuning is documented
in `docs/LLAMA_PRESETS.md`. Sampling preferences are preserved. The AppImage uses
its model registry and does not bundle or consume that presets.ini.

Model weights are not included in the repository or AppImage.
