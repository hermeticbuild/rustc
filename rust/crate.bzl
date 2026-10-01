"""Compiler-specific declarations for generated Rust Cargo packages."""

load("@package_metadata//rules:package_metadata.bzl", "package_metadata")
load("@rules_rs//rs/private:rust_crate.bzl", _rust_crate = "rust_crate")
load("@rules_rust//rust:defs.bzl", "rust_binary", "rust_dylib_library")
load("@rustc//llvm:defs.bzl", "LLVM_RUSTC_FLAGS", "rustc_llvm_native")

_COMPILE_DATA_EXCLUDES = [
    "**/* *",
    ".git",
    ".tmp_git_root/**/*",
    "BUILD",
    "BUILD.bazel",
    "REPO.bazel",
    "Cargo.toml.orig",
    "WORKSPACE",
    "WORKSPACE.bazel",
]

_RUST_THIN_LTO_FLAGS = select({
    "@rustc//:thin_lto": ["-Zdylib-lto", "-Clto=thin", "-Cembed-bitcode=yes"],
    "//conditions:default": [],
})

_RUST_LINK_FEATURES = [
    "-runtime_library_search_directories",
    "-runtime_library_search_directories_workaround",
    "-thin_lto",
]

def _compiler_env(env):
    # cargo_build_script copies this dictionary during macro evaluation, so it
    # cannot contain select(). The supported compiler host is Linux x86_64.
    return env | {"CFG_COMPILER_HOST_TRIPLE": "x86_64-unknown-linux-gnu"}

def _crate_features(kwargs):
    return kwargs["crate_features"] + select({
        "@rules_rs//rs/platforms/config:" + triple: features
        for triple, features in kwargs["conditional_crate_features"].items()
    } | {"//conditions:default": []})

def _compile_data(kwargs):
    return native.glob(
        ["**"],
        exclude = _COMPILE_DATA_EXCLUDES,
        allow_empty = True,
    ) + kwargs.get("extra_compile_data", [])

def _crate_tags(name, kwargs):
    return ["crate-name=" + name, "manual", "noclippy", "norustfmt"] + kwargs["tags"]

def _rustc_driver(name, kwargs):
    static_name = name + "_static"
    dynamic_name = name + "_dynamic"

    # rust_crate declares the build script and Cargo package metadata once.
    _rust_crate(name = static_name, **kwargs)

    rust_dylib_library(
        name = dynamic_name,
        crate_name = kwargs["crate_name"],
        crate_root = kwargs["crate_root"],
        srcs = native.glob(["**/*.rs"], allow_empty = True),
        compile_data = _compile_data(kwargs),
        aliases = kwargs["aliases"],
        deps = kwargs["deps"] + ([":_bs"] if kwargs["build_script"] else []),
        link_deps = kwargs["link_deps"],
        data = kwargs["data"],
        crate_features = _crate_features(kwargs),
        edition = kwargs["edition"],
        version = kwargs["version"],
        rustc_env = kwargs["rustc_env"],
        rustc_env_files = ["cargo_toml_env_vars.env"],
        rustc_flags = kwargs["rustc_flags"] + ["--cap-lints=allow"] + _RUST_THIN_LTO_FLAGS + select({
            "@platforms//os:linux": ["-Clink-arg=-Wl,-rpath,$$ORIGIN"],
            "//conditions:default": [],
        }),
        # Upstream rustc_driver contains std; bin/rustc uses rustc_private to
        # consume std from rustc_driver without a separate libstd shared object.
        link_std_dylib = False,
        cc_runtime_linkage = "static",
        # rustc generates the dylib metadata, export list, and dependency map
        # during its link action. cc_common.link cannot reproduce those outputs.
        features = _RUST_LINK_FEATURES,
        package_metadata = [":" + static_name + "_package_metadata"],
        skip_deps_verification = kwargs.get("skip_deps_verification", False),
        skip_per_crate_rustc_flags = True,
        tags = _crate_tags(name, kwargs),
        target_compatible_with = kwargs["target_compatible_with"],
        visibility = ["//visibility:public"],
    )

    native.alias(
        name = name,
        actual = select({
            "@rustc//:upstream": ":" + dynamic_name,
            "//conditions:default": ":" + static_name,
        }),
        visibility = ["//visibility:public"],
    )

    native.filegroup(
        name = "rustc_driver_distribution_files",
        srcs = select({
            "@rustc//:upstream": [":" + dynamic_name],
            "//conditions:default": [],
        }),
        visibility = ["//visibility:public"],
    )

def _rustc_main(name, kwargs):
    package_metadata(
        name = name + "_package_metadata",
        purl = kwargs["purl"],
        visibility = ["//visibility:public"],
    )

    # compiler/rustc/build.rs only embeds Windows resources. The Linux
    # distributions use the unmodified main.rs and its rustc_driver dependency.
    rust_binary(
        name = "rustc",
        crate_name = "rustc_main",
        crate_root = kwargs["binaries"]["rustc-main"],
        srcs = native.glob(["**/*.rs"], allow_empty = True),
        compile_data = _compile_data(kwargs),
        deps = ["//src:rustc_driver"],
        data = kwargs["data"],
        crate_features = _crate_features(kwargs),
        edition = kwargs["edition"],
        version = kwargs["version"],
        rustc_env = kwargs["rustc_env"],
        rustc_env_files = ["cargo_toml_env_vars.env"],
        rustc_flags = kwargs["rustc_flags"] + ["--cap-lints=allow"] + _RUST_THIN_LTO_FLAGS + select({
            "@platforms//os:linux": ["-Clink-arg=-Wl,-rpath,$$ORIGIN/../lib"],
            "//conditions:default": [],
        }),
        # rustc_private tells rustc that rustc_driver already contains std and
        # its compiler crates. Both distributions use rustc for their final
        # link and ThinLTO; LLVM still uses the C++ toolchain's ThinLTO.
        features = _RUST_LINK_FEATURES,
        experimental_use_cc_common_link = 0,
        package_metadata = [":" + name + "_package_metadata"],
        skip_deps_verification = kwargs.get("skip_deps_verification", False),
        skip_per_crate_rustc_flags = True,
        tags = _crate_tags(name, kwargs),
        target_compatible_with = kwargs["target_compatible_with"],
        visibility = ["//visibility:public"],
    )

    for alias_name in [name, name + "__bin"]:
        native.alias(
            name = alias_name,
            actual = ":rustc",
            visibility = ["//visibility:public"],
        )

def rust_crate(name, **kwargs):
    """Declare one generated Cargo package, preserving rules_rs attributes."""
    if native.package_name().startswith("src/compiler/"):
        kwargs["rustc_env"] = _compiler_env(kwargs.get("rustc_env", {}))
        kwargs["build_script_env"] = _compiler_env(kwargs["build_script_env"])

    if name == "rustc_driver":
        _rustc_driver(name, kwargs)
    elif name == "rustc-main":
        _rustc_main(name, kwargs)
    else:
        if name == "rustc_llvm":
            rustc_llvm_native(name = "llvm-wrapper")
            kwargs["deps"] = kwargs["deps"] + [":llvm-wrapper"]
            kwargs["rustc_flags"] = kwargs["rustc_flags"] + LLVM_RUSTC_FLAGS
        _rust_crate(name = name, **kwargs)
