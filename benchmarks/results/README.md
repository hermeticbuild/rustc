# ThinLTO compiler comparison: 2026-10-01

Both distributions passed relocation, ELF dependency, executable, test-harness,
and procedural-macro validation before this run. Both use dynamic glibc. The
`static` variant links Rust compiler code and LLVM into `bin/rustc`.

The monolithic compiler had lower paired wall-clock times in nine of ten
workloads under the exploratory interval criterion. Startup showed a 3.39×
paired speedup; frontend workloads showed 1.26–1.30× speedups. The optimized
generic-pipeline result was inconclusive. These measurements compare the complete
compiler configurations, including their different ThinLTO optimization boundaries.

The run used an AMD EPYC 9755 Linux worker with a three-CPU affinity, 15 measured
pairs and two warmup pairs per workload, alternating the first compiler in each
pair. Filesystem caches were warm; incremental compilation and external linking
were excluded. The remote worker was not established to be dedicated, and its
reported host load was nonzero. Intervals describe variation in these pairs;
they do not account for every source of contention, multiple comparisons, or
performance on other Cargo projects.

| Workload | Upstream median ms | Monolithic median ms | Median paired speedup | Exploratory 95% interval |
| --- | ---: | ---: | ---: | ---: |
| `startup` | 13.521 | 4.068 | 3.394× | 3.104–3.769 |
| `generic_pipeline/frontend` | 48.788 | 38.537 | 1.263× | 1.187–1.337 |
| `generic_pipeline/debug` | 3,955.774 | 3,680.044 | 1.065× | 1.009–1.171 |
| `generic_pipeline/optimized` | 12,379.850 | 11,886.885 | 1.031× | 0.945–1.065 |
| `graph_algorithms/frontend` | 43.675 | 35.331 | 1.272× | 1.242–1.276 |
| `graph_algorithms/debug` | 1,153.740 | 1,083.889 | 1.042× | 1.002–1.100 |
| `graph_algorithms/optimized` | 3,601.657 | 3,478.250 | 1.059× | 1.016–1.073 |
| `numeric_kernels/frontend` | 35.486 | 27.299 | 1.296× | 1.246–1.334 |
| `numeric_kernels/debug` | 125.498 | 117.097 | 1.085× | 1.034–1.111 |
| `numeric_kernels/optimized` | 396.557 | 365.866 | 1.079× | 1.061–1.090 |

Speedup is upstream time divided by monolithic time within each measured pair.
The median of those ratios can differ from the ratio of the two median times.
An interval containing 1 does not identify a faster compiler for that workload.

| Size | Upstream | Monolithic |
| --- | ---: | ---: |
| Compiler executable and direct compiler shared libraries | 256,173,992 bytes | 223,475,512 bytes |
| Full distribution, uncompressed regular files | 425,267,101 bytes | 392,568,619 bytes |
| Distribution archive | 129,967,613 bytes | 120,078,016 bytes |

Compiler files are 12.8% smaller in the monolithic distribution. Both distributions
include the same prebuilt nightly standard library. Neither is a fully static
glibc distribution.

[Raw measurements](2026-10-01-thin-lto.json) include all 340 invocations, compiler
and library SHA-256 hashes, manifests, commands, fixture hashes, CPU usage, and
child peak RSS. Child peak RSS can include the Python launcher's memory before
`exec`; startup RSS is not a compiler-only measurement.

Validation: [Bazel test invocation](https://app.buildbuddy.io/invocation/2fead773-9874-421a-9395-766c23e3b559).
Benchmarks and archives: [Bazel build invocation](https://app.buildbuddy.io/invocation/cb6ec524-5a6f-45c9-99b7-74c54edb7d63).

Reproduce with the commands in [the benchmark instructions](../README.md).
