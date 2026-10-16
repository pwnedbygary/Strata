The initial native frontend files were imported from robertkarl/UnbiasedStrata,
commit b124b59ce48e4d53abd14d1fd08979350fc27358, under the MIT license in LICENSE.
The engine remains this fork's engine. Local adaptations add existing profile
support, optional MTP, SSD-backed QFN tables, native routing and Linux packaging.
No model or dependency is downloaded by the native runtime. Build dependencies
must already be present locally. No outgoing HTTP client is used except the
router's loopback connection to its own model worker.
