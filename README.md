# Rust compiler builds with Bazel

This repository builds Rust nightly `2026-10-01` from its vendored source archive. `rules_rs` reads the pinned Cargo manifests and lockfile and generates Bazel targets for the compiler's dependencies. Rust compilation, build scripts, and LLVM compilation run as Bazel actions.

The compiler uses Rust commit `21b707e3f97e0b522ebd2f277a862339625ad83f`. LLVM is built from the Rust fork at commit `1b9c0d5ff9bbe7634aead059efe6b11a7eeba145` through `hermetic-llvm`. The LLVM revision is the `src/llvm-project` gitlink in that Rust commit. Both compiler variants enable the same 19 LLVM backends and use the system allocator.

The initial host platform is `x86_64-unknown-linux-gnu`, targeting glibc 2.28 or newer. A matching nightly binary compiles the Rust sources. The distribution currently includes the matching nightly's standard library, including `test` and `proc_macro`.

## Build

```sh
bazel build //:upstream_archive //:static_archive --features=thin_lto
```

The archives are `bazel-bin/upstream_distribution.tar.gz` and `bazel-bin/static_distribution.tar.gz`. Their extracted directories are also available as `//:upstream_distribution` and `//:static_distribution`.

| Artifact | Compiler libraries |
| --- | --- |
| `upstream_archive` | `bin/rustc`, `lib/librustc_driver-*.so`, and `lib/libLLVM-23-rust-1.101.0-nightly.so` |
| `static_archive` | `bin/rustc` contains Rust compiler code and LLVM; glibc remains dynamically linked |

Both archives contain `lib/rustlib/x86_64-unknown-linux-gnu/lib`, licenses, and `manifest.json`. A system C linker is required for producing executables, as with a Rust installation using the default system linker.

The compiler and LLVM are built from source; the bootstrap compiler and packaged standard library are downloaded binaries from the matching nightly. This build does not yet rebuild the standard library or perform a second self-hosted compiler stage.

Fully static glibc is not supported by these artifacts. A separate glibc 2.36 experiment could load a Rust shared library and allocate memory, but accessing the shared library's TLS crashed: `__tls_get_addr` returned null. The same library passed all ten allocation, TLS, thread, and panic-recovery cases when the host used dynamic glibc. Procedural macros require these operations, so `static_archive` retains dynamic glibc.

`//:rustc` builds the compiler alone. Select `--config=upstream` or `--config=static` for that target. The archive targets select their own compiler variant.

`--features=thin_lto` enables native LLVM ThinLTO and Rust ThinLTO. Both final compiler links run through rustc, preserving the Rust metadata required by `rustc_driver`. The upstream driver uses `-Zdylib-lto`; the LLVM shared library remains a separate optimization unit.

## Remote builds

The repository includes `--config=remote` for BuildBuddy Linux executors. Supply credentials through a private Bazel configuration, such as `.bazelrc.user`, then run:

```sh
bazel build //:upstream_archive //:static_archive --config=remote --features=thin_lto
bazel test //tests:all --config=remote --features=thin_lto
```

The remote configuration disables local action fallback. Downloading sources and generating Cargo build rules still run on the machine invoking Bazel.

## Validate and benchmark

Distribution tests relocate each compiler and check its reported version, ELF dependencies, executable compilation, test harnesses, procedural macros, and LLVM output. Run the benchmark script on one Linux machine with both distributions to compare compiler execution. The benchmark records individual measurements and alternates the order of the variants; build scheduling is not included in compiler timings.

See `benchmarks/README.md` for the benchmark command and output fields. Benchmark results are published only after both distributions pass validation.

The [initial ThinLTO measurements](benchmarks/results/README.md) favored the monolithic compiler for startup, frontend work, and most code-generation workloads. The optimized generic-pipeline comparison was inconclusive. The report includes raw measurements and the limits of the comparison.
