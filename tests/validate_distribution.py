#!/usr/bin/env python3
"""Validate a relocated Linux rustc distribution and its library dependencies."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


EXPECTED_COMMIT = "21b707e3f97e0b522ebd2f277a862339625ad83f"
EXPECTED_LLVM_COMMIT = "1b9c0d5ff9bbe7634aead059efe6b11a7eeba145"
EXPECTED_HOST = "x86_64-unknown-linux-gnu"
GLIBC_BASELINE = (2, 28)
COMPILER_LIBRARY = re.compile(r"^(?:librustc_driver|libLLVM)(?:[-.]|$)")


class ValidationError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def tool_path(name):
    path = shutil.which(name)
    require(path, f"Required Linux worker tool is unavailable: {name}")
    return str(Path(path).resolve())


def clean_environment():
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("LD_", "DYLD_", "RUST", "CARGO")):
            del env[key]
    env["LC_ALL"] = "C"
    return env


def run(command, *, cwd, env, timeout, success=True):
    result = subprocess.run(
        [str(arg) for arg in command],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if success and result.returncode:
        raise ValidationError(
            f"Command failed ({result.returncode}): {shlex.join(map(str, command))}"
            f"\n{result.stdout}{result.stderr}"
        )
    return result


def assert_contained_symlinks(directory):
    for path in directory.rglob("*"):
        if path.is_symlink():
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError) as error:
                raise ValidationError(f"Invalid distribution symlink: {path}: {error}") from error
            require(
                resolved.is_relative_to(directory),
                f"Distribution symlink resolves outside the distribution: {path} -> {resolved}",
            )


def required_glibc_versions(version_info, *, has_version_needs, path):
    requirements = set()
    in_needs = False
    found_needs = False
    for line in version_info.splitlines():
        section = re.match(r"^\s*Version (needs|definition|symbols) section\b", line)
        if section:
            in_needs = section.group(1) == "needs"
            found_needs |= in_needs
        if in_needs:
            requirements.update(re.findall(r"\bName:\s+(GLIBC_\S+)", line))
    require(
        not has_version_needs or found_needs,
        f"readelf did not report ELF version needs for {path}",
    )
    for name in sorted(requirements):
        version = re.fullmatch(r"GLIBC_(\d+)\.(\d+)(?:\.\d+)*", name)
        require(
            version is not None,
            f"Cannot verify glibc 2.28 compatibility for {path}: imported {name}",
        )
        require(
            (int(version.group(1)), int(version.group(2))) <= GLIBC_BASELINE,
            f"ELF requires newer than glibc 2.28: {path}: imported {name}",
        )
    return sorted(requirements)


def elf_info(path, distribution, *, readelf, cwd, env, timeout):
    dynamic = run([readelf, "-W", "-d", path], cwd=cwd, env=env, timeout=timeout).stdout
    headers = run([readelf, "-W", "-l", path], cwd=cwd, env=env, timeout=timeout).stdout
    needed = re.findall(r"\(NEEDED\).*?\[(.*?)\]", dynamic)
    require(
        all("/" not in name for name in needed),
        f"ELF dependency names must not contain filesystem paths: {path}: {needed}",
    )
    search_paths = re.findall(r"\((?:RPATH|RUNPATH)\).*?\[(.*?)\]", dynamic)
    interpreter = re.search(r"\[Requesting program interpreter: (.*?)\]", headers)
    for search_path in search_paths:
        for entry in search_path.split(":"):
            require(
                entry in ("$ORIGIN", "${ORIGIN}")
                or entry.startswith(("$ORIGIN/", "${ORIGIN}/")),
                f"ELF search path is not relative to $ORIGIN: {path}: {entry!r}",
            )
            expanded = entry.replace("${ORIGIN}", str(path.parent)).replace("$ORIGIN", str(path.parent))
            require(
                Path(expanded).resolve().is_relative_to(distribution),
                f"ELF search path resolves outside the distribution: {path}: {entry!r}",
            )
    info = {
        "needed": needed,
        "search_paths": search_paths,
        "interpreter": interpreter.group(1) if interpreter else None,
    }
    relative = path.relative_to(distribution)
    if relative == Path("bin/rustc") or (
        relative.parent == Path("lib") and re.search(r"\.so(?:\.|$)", relative.name)
    ):
        version_info = run(
            [readelf, "-W", "--version-info", path], cwd=cwd, env=env, timeout=timeout
        ).stdout
        info["required_glibc_versions"] = required_glibc_versions(
            version_info, has_version_needs="(VERNEED)" in dynamic, path=path
        )
    return info


def inspect_elf(distribution, variant, *, readelf, cwd, env, timeout):
    inspected = {}
    for path in sorted(distribution.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                is_elf = stream.read(4) == b"\x7fELF"
            if is_elf:
                inspected[str(path.relative_to(distribution))] = elf_info(
                    path, distribution, readelf=readelf, cwd=cwd, env=env, timeout=timeout
                )
    require("bin/rustc" in inspected, "bin/rustc is not an ELF binary")
    compiler_dependencies = inspected["bin/rustc"]["needed"]
    compiler_libraries = [
        path for path in distribution.rglob("*") if COMPILER_LIBRARY.match(path.name)
    ]
    all_dependencies = [name for info in inspected.values() for name in info["needed"]]
    if variant == "static":
        require(
            not compiler_libraries,
            f"Static distribution contains rustc_driver or LLVM shared libraries: {compiler_libraries}",
        )
        require(
            not any(COMPILER_LIBRARY.match(name) for name in all_dependencies),
            f"Static distribution depends on rustc_driver or LLVM shared libraries: {all_dependencies}",
        )
    else:
        require(
            any(name.startswith("librustc_driver") for name in compiler_dependencies),
            f"Upstream rustc has no librustc_driver dependency: {compiler_dependencies}",
        )
        for prefix in ("librustc_driver", "libLLVM"):
            require(
                any(path.name.startswith(prefix) for path in compiler_libraries),
                f"Upstream distribution does not contain {prefix}",
            )
            require(
                any(name.startswith(prefix) for name in all_dependencies),
                f"Upstream distribution has no dynamic dependency on {prefix}",
            )
        packaged_elf_names = {Path(path).name for path in inspected}
        for dependency in set(all_dependencies):
            if COMPILER_LIBRARY.match(dependency):
                require(
                    dependency in packaged_elf_names,
                    f"Required compiler library is not packaged with its exact name: {dependency}",
                )
    return inspected


RUNTIME_SOURCE = r"""
use std::{fs, panic, thread};

fn main() {
    let directory = std::env::args().nth(1).expect("scratch directory");
    let values: Vec<u64> = (0..4096).collect();
    let expected: u64 = values.iter().sum();
    let total = thread::spawn(move || values.into_iter().sum::<u64>())
        .join().expect("thread join");
    assert_eq!(total, expected);
    assert!(panic::catch_unwind(|| panic!("expected validation panic")).is_err());
    let file = std::path::Path::new(&directory).join("round-trip.txt");
    fs::write(&file, format!("{total}\n")).expect("write");
    assert_eq!(fs::read_to_string(&file).expect("read"), format!("{expected}\n"));
    println!("runtime validation passed");
}
"""

HARNESS_SOURCE = r"""
#[test]
fn allocation_and_sorting() {
    let mut values: Vec<_> = (0..1024).rev().collect();
    values.sort_unstable();
    assert_eq!(values, (0..1024).collect::<Vec<_>>());
}

#[test]
#[should_panic(expected = "expected test panic")]
fn panic_is_observed() {
    panic!("expected test panic");
}
"""

PROC_MACRO_SOURCE = r"""
extern crate proc_macro;
use proc_macro::TokenStream;
use std::cell::RefCell;
use std::sync::{Arc, atomic::{AtomicUsize, Ordering}};

struct MacroThreadState {
    values: Vec<u64>,
    drops: Arc<AtomicUsize>,
}

impl Drop for MacroThreadState {
    fn drop(&mut self) {
        self.drops.fetch_add(1, Ordering::SeqCst);
    }
}

thread_local! {
    static MACRO_TLS: RefCell<Option<MacroThreadState>> = RefCell::new(None);
}

#[proc_macro]
pub fn answer(_: TokenStream) -> TokenStream {
    MACRO_TLS.with(|state| assert!(state.borrow().is_none()));
    let drops = Arc::new(AtomicUsize::new(0));
    let thread_drops = Arc::clone(&drops);
    let answer = std::thread::spawn(move || {
        MACRO_TLS.with(|state| {
            *state.borrow_mut() = Some(MacroThreadState {
                values: (0..4096).collect(),
                drops: thread_drops,
            });
        });
        MACRO_TLS.with(|state| {
            let state = state.borrow();
            let values = &state.as_ref().unwrap().values;
            assert_eq!(values.iter().sum::<u64>(), 4095 * 4096 / 2);
        });
        assert!(std::panic::catch_unwind(|| {
            panic!("expected proc-macro validation panic");
        }).is_err());
        42_u64
    }).join().expect("proc-macro thread join");
    assert_eq!(drops.load(Ordering::SeqCst), 1, "proc-macro TLS destructor");
    format!("{answer}_u64").parse().unwrap()
}
"""

PROC_MACRO_USER_SOURCE = r"""
use validation_macro::answer;
fn main() {
    assert_eq!(answer!(), 42);
    println!("proc macro validation passed");
}
"""

CODEGEN_SOURCE = r"""
#[unsafe(no_mangle)]
pub extern "C" fn validation_mix(value: u64) -> u64 {
    value.wrapping_mul(6364136223846793005).rotate_left(17) ^ 1442695040888963407
}
"""


def validate(args):
    require(sys.platform == "linux", "Distribution validation requires Linux")
    source = Path(args.distribution).resolve(strict=True)
    require((source / "bin/rustc").is_file(), f"No bin/rustc in {source}")
    manifest = json.loads((source / "manifest.json").read_text())
    require(isinstance(manifest, dict), "Distribution manifest must be a JSON object")
    for field, expected in (
        ("variant", args.variant), ("rust_commit", args.expected_commit),
        ("llvm_commit", args.expected_llvm_commit), ("host", EXPECTED_HOST),
    ):
        require(manifest.get(field) == expected, f"Unexpected manifest {field}: {manifest.get(field)!r}")
    assert_contained_symlinks(source)
    cc = tool_path(args.cc)
    readelf = tool_path(args.readelf)
    env = clean_environment()
    with tempfile.TemporaryDirectory(prefix="rustc-distribution-") as temporary:
        work = Path(temporary)
        distribution = work / "relocated" / "toolchain"
        shutil.copytree(source, distribution, symlinks=True)
        assert_contained_symlinks(distribution)
        scratch = work / "programs"
        scratch.mkdir()
        rustc = distribution / "bin/rustc"
        common = {"cwd": scratch, "env": env, "timeout": args.timeout}
        inspected = inspect_elf(distribution, args.variant, readelf=readelf, **common)
        version = run([rustc, "-vV"], **common).stdout
        fields = dict(line.split(": ", 1) for line in version.splitlines() if ": " in line)
        require(
            fields.get("commit-hash") == args.expected_commit,
            f"Unexpected rustc commit: {fields.get('commit-hash')!r}; expected {args.expected_commit}",
        )
        require(fields.get("host") == EXPECTED_HOST, f"Unexpected host: {fields.get('host')!r}")
        sysroot = run([rustc, "--print", "sysroot"], **common).stdout.strip()
        require(Path(sysroot).resolve() == distribution, f"Relocated rustc reports sysroot {sysroot!r}")
        target_libdir = run([rustc, "--print", "target-libdir"], **common).stdout.strip()
        require(
            Path(target_libdir).resolve().is_relative_to(distribution),
            f"Relocated rustc reports external target-libdir {target_libdir!r}",
        )

        def compile_source(name, source_text, flags):
            source_path = scratch / f"{name}.rs"
            source_path.write_text(source_text)
            return run(
                [rustc, source_path, "--edition=2024", "-C", f"linker={cc}", *flags],
                **common,
            )

        for level in ("0", "2"):
            executable = scratch / f"runtime_o{level}"
            compile_source("runtime", RUNTIME_SOURCE, ["-C", f"opt-level={level}", "-o", executable])
            result = run([executable, scratch], **common)
            require("runtime validation passed" in result.stdout, "Runtime validation produced no result")
        print("PASS allocation, threads, panic unwinding, and filesystem access at -O0 and -O2", flush=True)

        harness = scratch / "harness"
        compile_source("harness", HARNESS_SOURCE, ["--test", "-o", harness])
        run([harness, "--test-threads=1"], **common)
        print("PASS libtest test harness", flush=True)

        macro = scratch / "libvalidation_macro.so"
        compile_source(
            "validation_macro", PROC_MACRO_SOURCE, ["--crate-type=proc-macro", "-o", macro]
        )
        macro_user = scratch / "macro_user"
        compile_source(
            "macro_user",
            PROC_MACRO_USER_SOURCE,
            ["--extern", f"validation_macro={macro}", "-o", macro_user],
        )
        run([macro_user], **common)
        print("PASS loaded proc macro allocation, TLS destructor, threads, and panic unwinding", flush=True)

        compile_source(
            "validation_codegen", CODEGEN_SOURCE,
            ["--crate-type=lib", "--emit=llvm-ir,obj", "-C", "opt-level=2", "--out-dir", scratch],
        )
        llvm_ir = (scratch / "validation_codegen.ll").read_text()
        require("define" in llvm_ir and "@validation_mix" in llvm_ir, "Missing LLVM IR definition")
        with (scratch / "validation_codegen.o").open("rb") as stream:
            require(stream.read(4) == b"\x7fELF", "Native object is not ELF")
        run([readelf, "-h", scratch / "validation_codegen.o"], **common)
        print("PASS LLVM IR and native object generation", flush=True)

        diagnostic_source = scratch / "diagnostic.rs"
        diagnostic_source.write_text('fn main() { let _: u8 = "not a number"; }\n')
        diagnostic = run(
            [rustc, diagnostic_source, "--emit=metadata", "--error-format=json"],
            success=False, **common,
        )
        require(diagnostic.returncode == 1, f"Unexpected diagnostic exit code: {diagnostic.returncode}")
        diagnostics = [json.loads(line) for line in diagnostic.stderr.splitlines() if line.startswith("{")]
        require(
            any(item.get("code", {}).get("code") == "E0308" for item in diagnostics if item.get("code")),
            f"Expected E0308 diagnostic is missing: {diagnostic.stderr}",
        )
        print("PASS type-error diagnostic", flush=True)
        print(json.dumps({
            "variant": args.variant,
            "version": version.strip(),
            "manifest": manifest,
            "elf": inspected,
            "cc": cc,
            "readelf": readelf,
            "note": "Static means rustc_driver and LLVM are linked into rustc; dynamic glibc is allowed.",
        }, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--variant", choices=("upstream", "static"), required=True)
    parser.add_argument("--expected-commit", default=EXPECTED_COMMIT)
    parser.add_argument("--expected-llvm-commit", default=EXPECTED_LLVM_COMMIT)
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"), help="Linux C linker driver executable")
    parser.add_argument("--readelf", default=os.environ.get("READELF", "readelf"))
    parser.add_argument("--timeout", type=int, default=180, help="Timeout for each command, in seconds")
    args = parser.parse_args()
    try:
        validate(args)
    except (ValidationError, OSError, subprocess.TimeoutExpired, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
