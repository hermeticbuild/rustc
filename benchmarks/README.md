# Compiler benchmarks

The [2026-10-01 ThinLTO results](results/README.md) include the measured timings,
compiler sizes, and raw measurements for the initial two distributions.

`compare.py` measures compiler startup and three compilation configurations for
each self-contained Rust fixture: frontend metadata, debug object code, and
optimized object code. The fixtures exercise generic iterators, collections and
graph algorithms, and const-generic numerical kernels. Object generation excludes
the external linker. These synthetic workloads do not predict every Cargo build.

Build and validate both distributions before benchmarking:

```sh
bazel build --features=thin_lto //:upstream_distribution //:static_distribution
bazel test --features=thin_lto //tests:upstream_distribution_test //tests:static_distribution_test
```

After both validation tests pass, `//benchmarks:results` runs all measurements in
one Linux x86-64 action and writes `bazel-bin/benchmarks/results.json`:

```sh
bazel build --config=remote --features=thin_lto //benchmarks:results
```

The benchmark target is manual, requires `thin_lto`, records the requested Bazel
features, and bypasses action caching. It permits up to one hour for the benchmark
action. Build records are still needed to confirm the compiler LTO implementation.

Run the benchmark on a quiet Linux x86-64 machine using the distribution directories
reported by Bazel, or unpack both distribution archives on that machine:

```sh
python3 benchmarks/compare.py \
  --upstream-dir /path/to/upstream-distribution \
  --static-dir /path/to/static-distribution \
  --runs 15 --warmups 2 \
  --upstream-build-description='--features=thin_lto; record actual compiler LTO mode here' \
  --static-build-description='--features=thin_lto; record actual compiler LTO mode here' \
  --output results.json
```

Each measured pair compiles the same source with the same flags. Order alternates
upstream/static and static/upstream; warmups use both variants. Compiler outputs
are removed before each invocation. Incremental compilation is disabled and the
filesystem cache is warm. Avoid concurrent builds, tests, or other benchmarks.
The script starts only one compiler process at a time.

The JSON report includes every elapsed time, CPU time, and per-child peak RSS from
Linux `wait4`; compiler versions, SHA-256 hashes, distribution manifests, source
hashes, commands, CPU details, and build descriptions; medians, quartiles, and
paired speedups. A speedup above 1 favors the static variant. Exploratory 95%
bootstrap intervals describe variation in the measured pairs; intervals crossing
1 are inconclusive. Intervals do not correct for multiple workload comparisons.
The script updates the report after each invocation and marks incomplete runs.

Peak RSS can include the Python launcher's memory before `exec`. Treat it as the
launched process's peak RSS, and do not use startup RSS to claim a compiler-only
memory improvement.

Record each compiler's actual LTO configuration. If the variants use different
LTO implementations, the results compare the complete compiler configurations;
they do not isolate linkage as the cause of a difference. No measurements are
checked in until both distributions have actually been built and benchmarked.

`static` describes linking Rust compiler code and LLVM into `bin/rustc`.
The current distribution uses dynamic glibc. It is not a fully static ELF binary.
