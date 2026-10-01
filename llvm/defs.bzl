"""LLVM libraries and the native implementation of the rustc_llvm crate."""

load("@rules_cc//cc:cc_library.bzl", "cc_library")
load("@rules_cc//cc:cc_shared_library.bzl", "cc_shared_library")
load("@rules_cc//cc/common:cc_common.bzl", "cc_common")
load("@rules_cc//cc/common:cc_info.bzl", "CcInfo")
load("@rules_cc//cc/common:cc_shared_library_info.bzl", "CcSharedLibraryInfo")

# Match src/bootstrap/src/core/build_steps/llvm.rs in the pinned Rust source.
LLVM_TARGETS = [
    "AArch64",
    "AMDGPU",
    "ARM",
    "AVR",
    "BPF",
    "CSKY",
    "Hexagon",
    "LoongArch",
    "M68k",
    "MSP430",
    "Mips",
    "NVPTX",
    "PowerPC",
    "RISCV",
    "Sparc",
    "SystemZ",
    "WebAssembly",
    "X86",
    "Xtensa",
]

_REQUIRED_COMPONENTS = [
    "ipo",
    "bitreader",
    "bitwriter",
    "linker",
    "asmparser",
    "lto",
    "coverage",
    "instrumentation",
]

_COMPONENTS = _REQUIRED_COMPONENTS + [target.lower() for target in LLVM_TARGETS]

# Replace the cfg output of compiler/rustc_llvm/build.rs. The same components
# configure LLVM target initialization in Rust and compilation of llvm-wrapper.
LLVM_RUSTC_FLAGS = [
    "--cfg=llvm_component=\"%s\"" % component
    for component in _COMPONENTS
] + [
    "--check-cfg=cfg(llvm_component,values(%s))" %
    ",".join(["\"%s\"" % component for component in _COMPONENTS]),
]

LLVM_SHARED_LIBRARY_NAME = "libLLVM-23-rust-1.101.0-nightly.so"

# rustc searches its bootstrap sysroot before Bazel's native libraries. Use a
# distinct link filename while retaining LLVM_SHARED_LIBRARY_NAME as the SONAME.
_LLVM_BUILD_LIBRARY_NAME = "libLLVM-23-rust-1.101.0-nightly-hermetic.so"

# List the libraries used directly by rustc's LLVM C API bindings and C++
# wrappers. cc_shared_library whole-archives these libraries so their APIs are
# retained even when LLVM itself does not reference every exported function.
_LLVM_LIBRARIES = [
    "Analysis",
    "AsmParser",
    "BinaryFormat",
    "BitReader",
    "BitWriter",
    "CodeGen",
    "Core",
    "Coverage",
    "DebugInfoDWARF",
    "IPO",
    "IRPrinter",
    "IRReader",
    "Instrumentation",
    "LTO",
    "Linker",
    "MC",
    "MCParser",
    "Object",
    "Passes",
    "Plugins",
    "ProfileData",
    "Remarks",
    "Support",
    "Target",
    "TargetParser",
    "TransformUtils",
] + [
    target + component
    for target in LLVM_TARGETS
    for component in ["CodeGen", "AsmParser", "Info", "UtilsAndDesc"]
]

_LLVM_DEPS = [Label("@llvm-project//llvm:" + name) for name in _LLVM_LIBRARIES]

def _llvm_shared_cc_info_impl(ctx):
    shared = ctx.attr.shared
    return [
        DefaultInfo(
            files = shared[DefaultInfo].files,
            runfiles = ctx.runfiles(transitive_files = shared[DefaultInfo].files).merge(
                shared[DefaultInfo].default_runfiles,
            ),
        ),
        CcInfo(
            compilation_context = ctx.attr.headers[CcInfo].compilation_context,
            linking_context = cc_common.create_linking_context(
                linker_inputs = depset([shared[CcSharedLibraryInfo].linker_input]),
            ),
        ),
    ]

_llvm_shared_cc_info = rule(
    implementation = _llvm_shared_cc_info_impl,
    attrs = {
        "headers": attr.label(mandatory = True, providers = [CcInfo]),
        "shared": attr.label(mandatory = True, providers = [CcSharedLibraryInfo]),
    },
    provides = [CcInfo],
)

def rustc_llvm_libraries():
    """Declare the static components and the separately packaged libLLVM."""
    cc_library(
        name = "static",
        deps = _LLVM_DEPS,
        visibility = ["//visibility:public"],
    )

    cc_shared_library(
        name = "libLLVM",
        deps = _LLVM_DEPS,
        exports_filter = ["@llvm-project//llvm:__pkg__"],
        shared_lib_name = _LLVM_BUILD_LIBRARY_NAME,
        user_link_flags = [
            "-Wl,-soname," + LLVM_SHARED_LIBRARY_NAME,
            "-Wl,-z,defs",
        ],
        target_compatible_with = ["@platforms//os:linux"],
        visibility = ["//visibility:public"],
    )

    # Copy only the compilation context from static LLVM. Passing its linking
    # context to rustc would also link LLVM statically into librustc_driver.
    _llvm_shared_cc_info(
        name = "shared",
        headers = ":static",
        shared = ":libLLVM",
        visibility = ["//visibility:public"],
    )

def rustc_llvm_native(name):
    """Compile llvm-wrapper in the generated rustc_llvm Bazel package."""
    cc_library(
        name = name,
        srcs = native.glob(["llvm-wrapper/*.cpp"]),
        hdrs = native.glob(["llvm-wrapper/*.h"]),
        local_defines = [
            "LLVM_COMPONENT_" + component.upper()
            for component in _COMPONENTS
        ] + [
            "LLVM_RUSTLLVM",
            "NDEBUG",
        ],
        features = ["-layering_check"],
        deps = select({
            Label("//:upstream"): [Label("//llvm:shared")],
            "//conditions:default": [Label("//llvm:static")],
        }),
        visibility = ["//visibility:public"],
    )
