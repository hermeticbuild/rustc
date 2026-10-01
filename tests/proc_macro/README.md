# Procedural-macro integration tests

The two public targets compile and run fourteen cases from relocated compiler
archives on Linux x86-64. Both targets are included in `bazel test //...`:

```sh
bazel test //tests/proc_macro:upstream_test //tests/proc_macro:monolithic_test \
  --features=thin_lto --config=remote
```

The cases cover bang, derive, and attribute macros; token cloning and groups;
nested `TokenStream::expand_expr`; builtin `proc_macro::quote!`; span positions,
source text, and filename remapping; tracked environment and file dependencies;
working directory; stdout and stderr; and panic diagnostics for all three macro
kinds. `incremental_derive` checks initial, unchanged, and changed derive inputs
using one incremental directory with `-Zcache-proc-macros`. It checks the results
without claiming to measure cache hits.

`constructor_tls` checks that a DSO constructor's thread-local state remains
available during default same-thread expansion. `global_state` checks repeated
invocations of a process-global counter without assuming expansion order. These
are compatibility expectations for this compiler, not Rust language guarantees.
Missing `Span::source_text` is recorded without failing because source text is
best-effort diagnostic information.

`lazy_binding` builds a DSO with an unresolved native call in an unused macro.
It verifies an undefined symbol, a `JUMP_SLOT` relocation, and absence of eager
binding flags before invoking another macro from that DSO.

`dynamic_std` links a macro to the archive's shared `libstd` and verifies its
`DT_NEEDED` entry. Rust's `dependency_format.rs` prefers static dependencies for
`CrateType::ProcMacro`, even with `-Cprefer-dynamic`, so this fixture explicitly
passes the `.so` and matching `.rmeta` in repeated `--extern std=...` arguments,
without the `.rlib`. The `.so` contains only a metadata stub; the `.rmeta`
provides full compiler metadata. The consumer compilation sets
`LD_LIBRARY_PATH` to the relocated sysroot's library directory. The macro checks
that value and exercises tokens, spans, allocation, threads, TLS destruction,
and caught unwinding.

Every command, working directory, exit status, environment override, diagnostic,
and complete stdout/stderr output is recorded in `result.json` under
`TEST_UNDECLARED_OUTPUTS_DIR`, alongside sources and dep-info files. The report
also records archive/compiler hashes and macro ELF inspections. Timeouts kill the command's process group and fail the case.
Later cases still run after a consumer failure.

Use `--test_arg=--case=dynamic_std` to select one case. The Python runner also
accepts `--archive`, `--fixtures`, `--output`, `--timeout-seconds`, `--cc`, and
`--readelf`. The system C linker builds only the temporary test programs; it is
not an input to the packaged compiler build.
