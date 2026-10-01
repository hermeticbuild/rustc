"""Bzlmod extension for the pinned Rust compiler source repository."""

load(":repository.bzl", "rustc_source_repository")

_HOSTS = ["linux_aarch64", "linux_x86_64", "macos_aarch64", "macos_x86_64"]

def _host(module_ctx):
    os = module_ctx.os.name.lower()
    if os == "mac os x":
        os = "macos"
    arch = module_ctx.os.arch
    if arch == "arm64":
        arch = "aarch64"
    elif arch == "amd64":
        arch = "x86_64"
    host = os + "_" + arch
    if host not in _HOSTS:
        fail("Rust source generation supports Linux and macOS on aarch64 and x86_64; found %s" % host)
    return host

def _rustc_impl(module_ctx):
    host = _host(module_ctx)
    root_deps = []
    root_dev_deps = []
    names = set()
    for module in module_ctx.modules:
        for source in module.tags.source:
            if source.name in names:
                fail("Rust source repository %s was requested more than once" % source.name)
            names.add(source.name)
            rustc_source_repository(
                name = source.name,
                cargo = getattr(source, "cargo_" + host),
                rustc = getattr(source, "rustc_" + host),
            )
            if module.is_root:
                if module_ctx.is_dev_dependency(source):
                    root_dev_deps.append(source.name)
                else:
                    root_deps.append(source.name)
    return module_ctx.extension_metadata(
        reproducible = True,
        root_module_direct_deps = root_deps,
        root_module_direct_dev_deps = root_dev_deps,
    )

_source = tag_class(
    attrs = {
        "name": attr.string(default = "rustc_sources"),
    } | {
        tool + "_" + host: attr.label(
            default = Label("@%s_%s_nightly_2026_10_01//:bin/%s" % (tool, host, tool)),
        )
        for tool in ["cargo", "rustc"]
        for host in _HOSTS
    },
)

rustc = module_extension(
    implementation = _rustc_impl,
    arch_dependent = True,
    os_dependent = True,
    tag_classes = {"source": _source},
)
