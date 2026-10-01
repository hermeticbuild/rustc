"""Run paired compiler measurements as one uncached Linux action."""

def _compiler_benchmark_impl(ctx):
    if "thin_lto" not in ctx.features:
        fail("Compiler benchmarks require --features=thin_lto")
    result = ctx.actions.declare_file(ctx.label.name + ".json")
    arguments = ctx.actions.args()
    arguments.add_all("--upstream-dir", [ctx.file.upstream], expand_directories = False)
    arguments.add_all("--static-dir", [ctx.file.static], expand_directories = False)
    arguments.add("--output", result)
    arguments.add("--runs", ctx.attr.runs)
    arguments.add("--warmups", ctx.attr.warmups)
    arguments.add_all(ctx.attr.workloads, before_each = "--workload")
    description = "Bazel features: %s; Rust-managed final ThinLTO requested" % ", ".join(sorted(ctx.features))
    arguments.add("--upstream-build-description", description)
    arguments.add("--static-build-description", description)
    ctx.actions.run(
        executable = ctx.attr._compare[DefaultInfo].files_to_run,
        inputs = [ctx.file.upstream, ctx.file.static],
        outputs = [result],
        arguments = [arguments],
        execution_requirements = {
            "no-cache": "1",
            "timeout": "3600",
        },
        mnemonic = "BenchmarkRustcDistributions",
        progress_message = "Comparing upstream and static rustc distributions",
    )
    return [DefaultInfo(files = depset([result]))]

compiler_benchmark = rule(
    implementation = _compiler_benchmark_impl,
    attrs = {
        "upstream": attr.label(allow_single_file = True, mandatory = True),
        "static": attr.label(allow_single_file = True, mandatory = True),
        "runs": attr.int(default = 15),
        "warmups": attr.int(default = 2),
        "workloads": attr.string_list(),
        "_compare": attr.label(
            default = Label("//benchmarks:compare"),
            executable = True,
            cfg = "exec",
        ),
    },
    exec_compatible_with = [
        "@platforms//cpu:x86_64",
        "@platforms//os:linux",
    ],
)
