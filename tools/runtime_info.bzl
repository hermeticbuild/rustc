"""Collect runtime details from a Linux x86-64 execution worker."""

def _runtime_info_impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".json")
    arguments = ctx.actions.args()
    arguments.add(output)
    ctx.actions.run(
        executable = ctx.attr._tool[DefaultInfo].files_to_run,
        arguments = [arguments],
        outputs = [output],
        execution_requirements = {
            "no-cache": "1",
            "timeout": "120",
        },
        mnemonic = "RustcRuntimeInfo",
        progress_message = "Collecting Linux worker glibc and package versions",
    )
    return [DefaultInfo(files = depset([output]))]

runtime_info = rule(
    implementation = _runtime_info_impl,
    attrs = {
        "_tool": attr.label(
            default = Label("//tools:runtime_info_tool"),
            executable = True,
            cfg = "exec",
        ),
    },
    exec_compatible_with = [
        "@platforms//cpu:x86_64",
        "@platforms//os:linux",
    ],
)
