# Distribution validation

```sh
python3 tests/validate_distribution.py \
  --distribution /path/to/distribution --variant upstream
python3 tests/validate_distribution.py \
  --distribution /path/to/distribution --variant static
```

Validation requires a Linux x86-64 worker with `cc` and `readelf` on `PATH`.
`--cc /path/to/cc` and `--readelf /path/to/readelf` select explicit executables.
The compiler receives the selected C linker driver with `-C linker=...`.

The script copies the distribution to a temporary directory and checks contained
symlinks, ELF dependencies and search paths, the manifest's Rust and LLVM commits,
the reported compiler commit, implicit
sysroot discovery, allocation, threads, panic unwinding, filesystem access,
libtest, proc-macro creation and use, LLVM IR, native object code, and a type-error
diagnostic. Runtime examples compile at both optimization levels 0 and 2. Loader
and Rust/Cargo environment overrides are removed during validation.

The upstream variant must ship and use `librustc_driver` and `libLLVM`; the static
variant must have neither shared-library dependency. The static variant may use
dynamic glibc, and its sysroot may contain `libstd.so` for downstream Rust code.
`bin/rustc` and shared libraries directly in `lib/` must require glibc 2.28 or
older. Validation reads only imported versions from ELF version needs, excluding
version definitions and `GLIBCXX` requirements, and records the required GLIBC
versions in its JSON output. Unrecognized `GLIBC_` requirements, including private
glibc interfaces and newer ABI markers, fail compatibility validation.
Runtime checks validate compiler behavior and reported identity. Bazel build
inputs and build records establish construction from the pinned source commits.

Run all distribution and [procedural-macro tests](proc_macro/README.md) with:

```sh
bazel test //tests/... --features=thin_lto --config=remote
```
