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

A separate procedural-macro run used the same compiler binaries (verified by
SHA-256), the same worker CPU model, and the same 15 measured pairs plus two
warmup pairs. Each consumer compiled 64 eight-field `WireRecord` derives. Each
compiler built its macro DSO before timing; the timed consumer includes macro
loading and execution. This run had its own worker affinity and host load,
recorded in [the macro measurements](2026-10-01-proc-macro-thin-lto.json).

| Procedural-macro workload | Upstream median ms | Monolithic median ms | Median paired speedup | Exploratory 95% interval |
| --- | ---: | ---: | ---: | ---: |
| `proc_macro_records/frontend` | 158.005 | 149.272 | 1.059× | 1.039–1.075 |
| `proc_macro_records/debug` | 232.627 | 222.655 | 1.057× | 0.981–1.096 |

The final macro frontend comparison favors monolithic; the debug comparison is
inconclusive. An [earlier macro run](2026-10-01-proc-macro-thin-lto-before-cleanup.json)
before removal of unused iterator machinery and fixture-copy actions favored
monolithic in both cases (1.084× frontend, 1.054× debug). The variation between
runs reinforces the limits of the small debug difference.

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

Validation: [initial distribution tests](https://app.buildbuddy.io/invocation/2fead773-9874-421a-9395-766c23e3b559) and [final distribution plus procedural-macro tests](https://app.buildbuddy.io/invocation/dd3a7ead-ed90-429a-95da-7de27cc424aa). The final run passed all four tests, including fourteen procedural-macro cases per compiler. Cleanup preserved both distribution archives byte for byte.
Initial benchmarks and archives: [Bazel build invocation](https://app.buildbuddy.io/invocation/cb6ec524-5a6f-45c9-99b7-74c54edb7d63).

Procedural-macro benchmarks: [Bazel build invocation](https://app.buildbuddy.io/invocation/5f89262b-cfc4-40fe-a21a-41eff42c7737), with 68 timed invocations including warmups and two untimed macro DSO builds.

Reproduce with the commands in [the benchmark instructions](../README.md).
