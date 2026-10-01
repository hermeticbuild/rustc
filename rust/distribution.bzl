"""Install each compiler variant into a relocatable distribution directory."""

load("//llvm:defs.bzl", "LLVM_SHARED_LIBRARY_NAME")

def _variant_impl(_settings, attr):
    return {"//:linkage": attr.variant}

_variant = transition(
    implementation = _variant_impl,
    inputs = [],
    outputs = ["//:linkage"],
)

def _distribution_impl(ctx):
    directory = ctx.actions.declare_directory(ctx.label.name)
    archive = ctx.actions.declare_file(ctx.label.name + ".tar.gz")
    args = ctx.actions.args()
    args.add_all("--directory", [directory], expand_directories = False)
    args.add("--archive", archive)
    args.add("--variant", ctx.attr.variant)
    args.add_all(ctx.features, before_each = "--feature")
    args.add("--source-metadata", ctx.file.source_metadata)
    inputs = [ctx.file.source_metadata]
    destinations = set()
    groups = [
        ("bin", ctx.files.compiler),
        ("lib", ctx.files.driver),
        ("lib/rustlib/x86_64-unknown-linux-gnu/lib", ctx.files.stdlib),
    ]
    llvm_files = ctx.files.llvm if ctx.attr.variant == "upstream" else []
    if llvm_files:
        groups.append(("lib", llvm_files))
    groups += [
        ("share/licenses/rustc", ctx.files.licenses),
        ("share/licenses/llvm", [ctx.file.llvm_license]),
    ]
    for prefix, files in groups:
        for src in files:
            if prefix == "lib" and ".so" not in src.basename:
                continue
            basename = LLVM_SHARED_LIBRARY_NAME if src in llvm_files else src.basename
            destination = prefix + "/" + basename
            if destination in destinations:
                fail("Duplicate distribution file %s" % destination)
            destinations.add(destination)
            args.add("--file")
            args.add(destination)
            args.add(src)
            inputs.append(src)
    ctx.actions.run(
        executable = ctx.executable._packager,
        arguments = [args],
        inputs = depset(inputs),
        outputs = [directory, archive],
        mnemonic = "RustCompilerDistribution",
        progress_message = "Packaging %s rustc" % ctx.attr.variant,
    )
    return [
        DefaultInfo(files = depset([directory]), runfiles = ctx.runfiles(files = [directory])),
        OutputGroupInfo(archive = depset([archive])),
    ]

rustc_distribution = rule(
    implementation = _distribution_impl,
    attrs = {
        "variant": attr.string(mandatory = True, values = ["upstream", "static"]),
        "compiler": attr.label(
            default = Label("@rustc_sources//src/compiler/rustc:rustc"),
            cfg = _variant,
        ),
        "driver": attr.label(
            default = Label("@rustc_sources//src/compiler/rustc_driver:rustc_driver_distribution_files"),
            cfg = _variant,
        ),
        "llvm": attr.label(default = Label("//llvm:libLLVM"), cfg = _variant),
        "stdlib": attr.label(
            default = Label("@rust_stdlib_x86_64_unknown_linux_gnu_nightly_2026_10_01//:rust_std-x86_64-unknown-linux-gnu"),
        ),
        "source_metadata": attr.label(
            default = Label("@rustc_sources//src:source_metadata.json"),
            allow_single_file = True,
        ),
        "llvm_license": attr.label(default = Label("@llvm-project//llvm:LICENSE.TXT"), allow_single_file = True),
        "licenses": attr.label(default = Label("@rustc_sources//src:licenses")),
        "_packager": attr.label(default = Label("//tools:package"), cfg = "exec", executable = True),
        "_allowlist_function_transition": attr.label(
            default = Label("@bazel_tools//tools/allowlists/function_transition_allowlist"),
        ),
    },
)
