"""Download Rust source and generate compiler BUILD files from Cargo manifests."""

load("@bazel_skylib//lib:paths.bzl", "paths")
load(
    "@rules_rs//rs/private:cargo_workspace_graph.bzl",
    "fq_crate",
    "manifest_package_dir",
    "normalize_path",
    "platform_label",
    "resolve_cargo_metadata_packages",
    "resolve_cargo_workspace_members",
    "split_lockfile_packages",
    "workspace_dep_data",
)
load("@rules_rs//rs/private:repository_utils.bzl", "cargo_build_file_values", "inherit_workspace_package_fields", "render_rust_crate_call")
load("@rules_rs//rs/private:toml2json.bzl", "run_toml2json")

RUST_NIGHTLY = "2026-10-01"
RUST_COMMIT = "21b707e3f97e0b522ebd2f277a862339625ad83f"
RUST_LLVM_COMMIT = "1b9c0d5ff9bbe7634aead059efe6b11a7eeba145"
RUST_SOURCE_SHA256 = "bfc25283563db9c214520fc97a657464b474f698342434332ac34ebf89c3a522"

_SOURCE_ROOT = "src"
_PLATFORM_TRIPLES = [
    "aarch64-apple-darwin",
    "aarch64-unknown-linux-gnu",
    "x86_64-apple-darwin",
    "x86_64-unknown-linux-gnu",
]
_COMPILER_FEATURES = ["llvm", "max_level_info"]
_COMPILER_ENV = {
    "CFG_DEFAULT_CODEGEN_BACKEND": "llvm",
    "CFG_DEFAULT_NEXT_SOLVER_GLOBALLY": "1",
    "CFG_DEFAULT_POLONIUS_NEXT": "1",
    "CFG_LIBDIR_RELATIVE": "lib",
    "CFG_RELEASE": "1.101.0-nightly",
    "CFG_RELEASE_CHANNEL": "nightly",
    "CFG_VERSION": "1.101.0-nightly (21b707e3f 2026-09-30)",
    "CFG_VER_DATE": "2026-09-30",
    "CFG_VER_HASH": RUST_COMMIT,
    "RUSTC_BOOTSTRAP": "1",
    "RUSTC_INSTALL_BINDIR": "bin",
}
_EXTRA_COMPILE_DATA = {
    "rustc_attr_ir": ["//src:attribute_doc_examples"],
    "rustc_errors": ["//src/compiler/rustc_error_codes:srcs"],
    "rustc_proc_macro": ["//src/library/proc_macro:srcs"],
}

def _compiler_metadata(rctx):
    rctx.report_progress("Resolving the vendored Rust compiler Cargo workspace")
    result = rctx.execute(
        [
            rctx.path(rctx.attr.cargo),
            "metadata",
            "--manifest-path",
            str(rctx.path(paths.join(_SOURCE_ROOT, "Cargo.toml"))),
            "--offline",
            "--locked",
            "--features",
            ",".join(["rustc-main/" + feature for feature in _COMPILER_FEATURES]),
            "--format-version=1",
            "--quiet",
        ],
        environment = {
            "CARGO_ENCODED_RUSTFLAGS": "",
            "CARGO_HOME": str(rctx.path(".cargo-home")),
            "CARGO_NET_OFFLINE": "true",
            "RUSTC": str(rctx.path(rctx.attr.rustc)),
            "RUSTC_BOOTSTRAP": "1",
            "RUSTC_WORKSPACE_WRAPPER": "",
            "RUSTC_WRAPPER": "",
            "RUSTFLAGS": "",
        },
        working_directory = str(rctx.path(_SOURCE_ROOT)),
        timeout = 300,
    )
    if result.return_code:
        fail("Cargo metadata failed:\n%s\n%s" % (result.stdout, result.stderr))
    return json.decode(result.stdout)

def _compiler_package_ids(metadata):
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    roots = [package["id"] for package in metadata["packages"] if package["name"] == "rustc-main"]
    if len(roots) != 1:
        fail("Expected one rustc-main package, found %s" % len(roots))
    selected = set(roots)
    pending = roots
    for _ in range(len(nodes)):
        next_pending = []
        for package_id in pending:
            for dependency in nodes[package_id]["deps"]:
                if not any([kind["kind"] != "dev" for kind in dependency["dep_kinds"]]):
                    continue
                dep_id = dependency["pkg"]
                if dep_id not in selected:
                    selected.add(dep_id)
                    next_pending.append(dep_id)
        if not next_pending:
            return selected
        pending = next_pending
    fail("Rust compiler dependency traversal did not finish")

def _filtered_metadata(metadata, selected):
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    names = {package["id"]: package["name"] for package in metadata["packages"]}
    packages = []
    for package in metadata["packages"]:
        if package["id"] not in selected:
            continue
        package = dict(package)
        enabled_deps = set([
            (names[dependency["pkg"]], kind["kind"], kind["target"])
            for dependency in nodes[package["id"]]["deps"]
            if dependency["pkg"] in selected
            for kind in dependency["dep_kinds"]
            if kind["kind"] != "dev"
        ])
        package["dependencies"] = [
            dependency
            for dependency in package["dependencies"]
            if (
                dependency["name"],
                dependency["kind"],
                dependency["target"],
            ) in enabled_deps
        ]
        packages.append(package)
    return metadata | {"packages": packages}

def _select_by_triple(by_platform):
    if not by_platform:
        return {}
    return {
        triple: sorted(by_platform.get(platform_label(triple, False), []))
        for triple in _PLATFORM_TRIPLES
    }

def _crate_attr(*, aliases, build_deps, build_deps_select, features, features_select, deps, deps_select, name):
    return struct(
        aliases = aliases,
        allow_build_script_to_detect_nonhermetic_paths = False,
        build_script_data = [],
        build_script_data_select = {},
        build_script_deps = build_deps,
        build_script_deps_select = build_deps_select,
        build_script_env = _COMPILER_ENV,
        build_script_env_select = {},
        build_script_tags = [],
        build_script_toolchains = [],
        build_script_tools = [],
        build_script_tools_select = {},
        crate_features = features,
        crate_features_select = features_select,
        crate_tags = [],
        data = [],
        deps = deps,
        deps_select = deps_select,
        extra_compile_data = _EXTRA_COMPILE_DATA.get(name, []),
        rustc_env = _COMPILER_ENV,
        rustc_flags = ["-Zforce-unstable-if-unmarked"],
        rustc_flags_select = {},
        use_legacy_rules_rust_platforms = False,
    )

def _workspace_crate_attr(name, data):
    return _crate_attr(
        name = name,
        aliases = data["aliases"],
        build_deps = data["build_deps"],
        build_deps_select = _select_by_triple(data["build_deps_by_platform"]),
        features = data["crate_features"],
        features_select = _select_by_triple(data["crate_features_by_platform"]),
        deps = data["deps"],
        deps_select = _select_by_triple(data["deps_by_platform"]),
    )

def _registry_crate_attr(name, resolution):
    return _crate_attr(
        name = name,
        aliases = resolution.aliases,
        build_deps = [],
        build_deps_select = {triple: sorted(resolution.build_deps[triple]) for triple in _PLATFORM_TRIPLES},
        features = [],
        features_select = {triple: sorted(resolution.features_enabled[triple]) for triple in _PLATFORM_TRIPLES},
        deps = [],
        deps_select = {triple: sorted(resolution.deps[triple]) for triple in _PLATFORM_TRIPLES},
    )

def _render_package(rctx, package, bazel_package, workspace_toml, crate_attr):
    manifest = run_toml2json(rctx, paths.join(bazel_package, "Cargo.toml"))
    manifest = inherit_workspace_package_fields(manifest, workspace_toml)
    name = package["name"]
    cargo = cargo_build_file_values(
        rctx,
        manifest,
        ["rustc-main"] if name == "rustc-main" else [],
        gen_build_script = "off" if name == "rustc_llvm" else "auto",
        package_path = bazel_package,
    )
    crate_name = cargo.values["crate_name"]
    if crate_name == "None":
        crate_name = repr(name.replace("-", "_"))
    values = cargo.values | {
        "crate_name": crate_name,
        "name": repr(name),
        "purl": repr("pkg:cargo/%s@%s" % (name, package["version"])),
        "version": repr(package["version"]),
    }
    if name == "rustc_proc_macro":
        # compiler/rustc_proc_macro reuses library/proc_macro/src/lib.rs.
        values["crate_root"] = repr("//src/library/proc_macro:src/lib.rs")
    rctx.file(paths.join(bazel_package, "BUILD.bazel"), """\
load("@rustc//rust:crate.bzl", "rust_crate")
load("//src:defs.bzl", "RESOLVED_PLATFORMS")

package(default_visibility = ["//visibility:public"])

filegroup(
    name = "srcs",
    srcs = glob(["**/*"]),
)

%s
""" % render_rust_crate_call(
        crate_attr,
        values,
        bazel_metadata = cargo.bazel_metadata,
    ))

def _alias(name, actual):
    return "alias(name = %s, actual = %s)\n" % (repr(name), repr(actual))

def _prune_vendor(rctx, packages):
    vendor_root = paths.join(_SOURCE_ROOT, "vendor")
    vendor_prefix = vendor_root + "/"
    selected = set([
        package["bazel_package"].removeprefix(vendor_prefix).split("/")[0]
        for package in packages
        if package["bazel_package"].startswith(vendor_prefix)
    ])
    for package_dir in rctx.path(vendor_root).readdir():
        if package_dir.basename not in selected and package_dir.get_child("Cargo.toml").exists:
            rctx.delete(package_dir)

def _generate_build_files(rctx, metadata):
    selected = _compiler_package_ids(metadata)
    metadata = _filtered_metadata(metadata, selected)
    workspace_ids = set(metadata["workspace_members"])
    workspace_metadata = metadata | {
        "packages": [package for package in metadata["packages"] if package["id"] in workspace_ids],
    }
    repo_root = normalize_path(rctx.path(_SOURCE_ROOT))
    workspace_toml = run_toml2json(rctx, paths.join(_SOURCE_ROOT, "Cargo.toml"))
    package_keys = set([(package["name"], package["version"]) for package in metadata["packages"]])
    lock_packages = [
        package
        for package in run_toml2json(rctx, paths.join(_SOURCE_ROOT, "Cargo.lock"))["package"]
        if (package["name"], package["version"]) in package_keys
    ]
    split = split_lockfile_packages(
        hub_name = "rustc_sources",
        cargo_metadata = workspace_metadata,
        workspace_cargo_toml = workspace_toml,
        all_packages = lock_packages,
        repo_root = repo_root,
    )
    metadata_by_name = {
        fq_crate(package["name"], package["version"]): package
        for package in metadata["packages"]
    }
    packages = split.packages
    for package in packages:
        package_metadata = metadata_by_name[fq_crate(package["name"], package["version"])]
        package["bazel_package"] = paths.join(
            _SOURCE_ROOT,
            manifest_package_dir(package_metadata["manifest_path"], repo_root),
        )
    package_info = resolve_cargo_metadata_packages(packages, metadata, _PLATFORM_TRIPLES)
    resolution = resolve_cargo_workspace_members(
        rctx,
        cargo_metadata = workspace_metadata,
        packages = packages,
        workspace_members = split.workspace_members,
        versions_by_name = package_info.versions_by_name,
        feature_resolutions_by_fq_crate = package_info.feature_resolutions_by_fq_crate,
        annotations = {
            "rustc-main": {"*": struct(crate_features = _COMPILER_FEATURES, crate_features_select = {})},
        },
        platform_triples = _PLATFORM_TRIPLES,
        materialize_workspace_members = True,
        dep_label_prefix = "//src:",
    )
    dep_data = workspace_dep_data(
        cargo_metadata = workspace_metadata,
        cfg_match_cache = resolution.cfg_match_cache,
        feature_resolutions_by_fq_crate = resolution.feature_resolutions_by_fq_crate,
        platform_cfg_attrs = resolution.platform_cfg_attrs,
        platform_triples = _PLATFORM_TRIPLES,
        repo_root = repo_root,
        workspace_package = _SOURCE_ROOT,
        use_legacy_rules_rust_platforms = False,
    )
    root_build = [
        'package(default_visibility = ["//visibility:public"])',
        'exports_files(["COPYRIGHT", "LICENSE-APACHE", "LICENSE-MIT", "version", "git-commit-hash", "git-commit-info", "source_metadata.json"])',
        'filegroup(name = "licenses", srcs = ["COPYRIGHT", "LICENSE-APACHE", "LICENSE-MIT", "license-metadata.json"] + glob(["LICENSES/**"]))',
        'filegroup(name = "attribute_doc_examples", srcs = glob(["tests/ui/attributes/doc_examples/**"]))',
    ]
    rctx.file(paths.join(_SOURCE_ROOT, "library/proc_macro/BUILD.bazel"), """\
package(default_visibility = ["//visibility:public"])

exports_files(["src/lib.rs"])

filegroup(
    name = "srcs",
    srcs = glob(["**/*"]),
)
""")
    for package in workspace_metadata["packages"]:
        name = package["name"]
        bazel_package = paths.join(_SOURCE_ROOT, manifest_package_dir(package["manifest_path"], repo_root))
        _render_package(rctx, package, bazel_package, workspace_toml, _workspace_crate_attr(name, dep_data[bazel_package]))
        target = "rustc" if name == "rustc-main" else name
        qualified_name = fq_crate(name, package["version"])
        root_build.append(_alias(qualified_name, "//%s:%s" % (bazel_package, target)))
        root_build.append(_alias(name, ":" + qualified_name))
    for package in packages:
        name = package["name"]
        bazel_package = package["bazel_package"]
        _render_package(rctx, package, bazel_package, workspace_toml, _registry_crate_attr(name, package["feature_resolutions"]))
        root_build.append(_alias(fq_crate(name, package["version"]), "//%s:%s" % (bazel_package, name)))
    root_build.append(_alias("rustc", "//src/compiler/rustc:rustc"))
    rctx.file(paths.join(_SOURCE_ROOT, "BUILD.bazel"), "\n".join(root_build))
    rctx.file(paths.join(_SOURCE_ROOT, "defs.bzl"), "RESOLVED_PLATFORMS = []\n")
    rctx.file(paths.join(_SOURCE_ROOT, "source_metadata.json"), json.encode_indent({
        "cargo_features": _COMPILER_FEATURES,
        "generated_crates": len(metadata["packages"]),
        "llvm_commit": RUST_LLVM_COMMIT,
        "nightly": RUST_NIGHTLY,
        "patches": [patch.name for patch in rctx.attr._patches],
        "rust_commit": RUST_COMMIT,
        "source_sha256": RUST_SOURCE_SHA256,
    }) + "\n")
    _prune_vendor(rctx, packages)

def _rustc_source_repository_impl(rctx):
    rctx.download_and_extract(
        url = "https://static.rust-lang.org/dist/%s/rustc-nightly-src.tar.xz" % RUST_NIGHTLY,
        sha256 = RUST_SOURCE_SHA256,
        strip_prefix = "rustc-nightly-src",
        output = _SOURCE_ROOT,
    )
    commit = rctx.read(paths.join(_SOURCE_ROOT, "git-commit-hash")).strip()
    if commit != RUST_COMMIT:
        fail("Rust source commit %s does not match %s" % (commit, RUST_COMMIT))
    for patch in rctx.attr._patches:
        rctx.patch(rctx.path(patch), strip = 1)
    _generate_build_files(rctx, _compiler_metadata(rctx))
    rctx.delete(".cargo-home")
    rctx.file("BUILD.bazel", 'package(default_visibility = ["//visibility:public"])\n' + _alias("rustc", "//src:rustc"))
    return rctx.repo_metadata(reproducible = True)

rustc_source_repository = repository_rule(
    implementation = _rustc_source_repository_impl,
    attrs = {
        "cargo": attr.label(allow_single_file = True, mandatory = True),
        "rustc": attr.label(allow_single_file = True, mandatory = True),
        "_patches": attr.label_list(
            allow_files = [".patch"],
            default = [Label("//rust/patches:llvm-wrapper-no-bundle.patch")],
        ),
    },
)
