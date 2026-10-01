"""Run paired compiler measurements as one uncached Linux action."""

def _compiler_benchmark_impl(ctx):
    if "thin_lto" not in ctx.features:
        fail("Compiler benchmarks require --features=thin_lto")
    result = ctx.actions.declare_file(ctx.label.name + ".json")
    fixture_directory = ctx.actions.declare_directory(ctx.label.name + "_fixtures")
    copy_arguments = ctx.actions.args()
    copy_arguments.add_all([fixture_directory], expand_directories = False)
    copy_arguments.add_all(ctx.files.fixtures)
    ctx.actions.run_shell(
        inputs = ctx.files.fixtures,
        outputs = [fixture_directory],
        arguments = [copy_arguments],
        command = """destination="$1"
shift
mkdir -p "$destination"
for source in "$@"; do
  cp "$source" "$destination/${source##*/}"
done
""",
        mnemonic = "PrepareRustcBenchmarkFixtures",
    )
    arguments = ctx.actions.args()
    arguments.add_all("--upstream-dir", [ctx.file.upstream], expand_directories = False)
    arguments.add_all("--static-dir", [ctx.file.static], expand_directories = False)
    arguments.add("--output", result)
    arguments.add_all("--fixtures", [fixture_directory], expand_directories = False)
    arguments.add("--runs", ctx.attr.runs)
    arguments.add("--warmups", ctx.attr.warmups)
    description = "Bazel features: %s; Rust-managed final ThinLTO requested" % ", ".join(sorted(ctx.features))
    arguments.add("--upstream-build-description", description)
    arguments.add("--static-build-description", description)
    ctx.actions.run(
        executable = ctx.attr._compare[DefaultInfo].files_to_run,
        inputs = [ctx.file.upstream, ctx.file.static, fixture_directory],
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
        "fixtures": attr.label_list(allow_files = [".rs"], mandatory = True),
        "runs": attr.int(default = 15),
        "warmups": attr.int(default = 2),
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
