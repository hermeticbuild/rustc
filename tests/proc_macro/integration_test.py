#!/usr/bin/env python3
"""Record procedural-macro behavior using a packaged Linux rustc compiler."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import traceback


CASES = {
    "basic": {
        "description": "Bang, derive, attribute, token cloning, groups, and punctuation.",
    },
    "global_state": {
        "description": "One DSO's process-global counter persists across repeated expansions; expansion order is not assumed.",
    },
    "nested": {
        "description": "TokenStream::expand_expr recursively invokes procedural macros and a builtin macro.",
    },
    "spans": {
        "description": "Span positions, byte range, displayed filename, local filename, and optional source text.",
    },
    "environment": {
        "description": "Tracked present/missing environment variables, tracked relative file, and compiler working directory.",
    },
    "output": {
        "description": "Procedural-macro stdout and stderr remain observable while expansion succeeds.",
    },
    "builtin_quote": {
        "description": "The compiler's builtin proc_macro::quote! expands while compiling a macro crate; the generated macro then runs.",
    },
    "incremental_derive": {
        "description": "Cached derive expansion produces correct binaries across initial, unchanged, and source-changed incremental compilations.",
    },
    "constructor_tls": {
        "macro_fixture": "constructor_macros.rs",
        "macro_crate": "constructor_macros",
        "description": "A DSO constructor's thread-local state remains alive and available to default same-thread macro expansion.",
    },
    "lazy_binding": {
        "macro_fixture": "lazy_binding_macros.rs",
        "macro_crate": "lazy_binding_macros",
        "description": "An unused exported macro has an unresolved native PLT call, while another macro expands successfully under lazy binding.",
    },
    "dynamic_std": {
        "macro_fixture": "dynamic_std_macros.rs",
        "macro_crate": "dynamic_std_macros",
        "description": "A macro linked with shared libstd exercises tokens, spans, allocation, TLS destructors, threads, and caught unwinding using inherited LD_LIBRARY_PATH.",
    },
    "panic_bang": {
        "panic_marker": "PROC_MACRO_CASE_BANG_PANIC",
        "description": "A bang macro panic becomes a compiler diagnostic.",
    },
    "panic_attribute": {
        "panic_marker": "PROC_MACRO_CASE_ATTRIBUTE_PANIC",
        "description": "An attribute macro panic becomes a compiler diagnostic.",
    },
    "panic_derive": {
        "panic_marker": "PROC_MACRO_CASE_DERIVE_PANIC",
        "description": "A derive macro panic becomes a compiler diagnostic.",
    },
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_archive(archive, destination):
    # tools/package.py produces directories and regular files. Refuse archive
    # entries that can write through a symlink or outside the destination.
    with tarfile.open(archive, "r:*") as source:
        for member in source:
            relative = Path(member.name)
            require(not relative.is_absolute() and ".." not in relative.parts,
                    "Invalid archive member: %s" % member.name)
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as data, target.open("wb") as output:
                    shutil.copyfileobj(data, output)
                target.chmod(member.mode & 0o777)
            else:
                raise RuntimeError("Archive member is not a directory or regular file: %s" % member.name)


class Recorder:
    def __init__(self, output, environment, command_timeout):
        self.output = output
        self.environment = environment
        self.command_timeout = command_timeout
        self.report = {
            "schema_version": 1,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": "Procedural-macro behavior in a relocated compiler distribution.",
            "platform": {"system": platform.system(), "machine": platform.machine()},
            "commands": [],
            "cases": [],
            "compatibility_notes": [
                "Process-global macro state continuity is checked against current rustc behavior, not asserted as a Rust language guarantee.",
                "Source text is diagnostic, best-effort information; unavailable source text is recorded without failing the case.",
                "constructor_tls checks Linux constructor/default same-thread behavior, not a Rust language guarantee.",
                "Macro expansion order and arbitrary thread-local continuity are not asserted.",
            ],
        }

    def save(self):
        (self.output / "result.json").write_text(
            json.dumps(self.report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def run(self, name, arguments, cwd, environment_overrides=None):
        command = [str(argument) for argument in arguments]
        timeout = self.command_timeout
        record = {"name": name, "command": command, "cwd": str(cwd),
                  "timeout_seconds": timeout, "status": "running"}
        environment = self.environment
        if environment_overrides:
            environment = {**environment, **environment_overrides}
            record["environment_overrides"] = environment_overrides
        self.report["commands"].append(record)
        self.save()
        print("COMMAND %s: %s" % (name, shlex.join(command)), flush=True)
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command, cwd=cwd, env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                record["status"] = "finished"
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
                record["status"] = "timeout"
            record.update(returncode=process.returncode, stdout=stdout, stderr=stderr)
        except OSError as error:
            record.update(status="unavailable", error=str(error), stdout="", stderr="")
        record["elapsed_seconds"] = time.monotonic() - started
        self.save()
        print("RESULT %s: %s returncode=%s" % (name, record["status"], record.get("returncode")), flush=True)
        if record["stdout"]:
            print(record["stdout"], end="", flush=True)
        if record["stderr"]:
            print("STDERR %s:\n%s" % (name, record["stderr"]), end="", flush=True)
        return record


def command_succeeded(command):
    return command["status"] == "finished" and command.get("returncode") == 0


def diagnostics(stderr):
    result = []
    for line in stderr.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("$message_type") == "diagnostic":
            result.append(value)
    return result


def run_cases(args, recorder, scratch):
    require(platform.system() == "Linux" and platform.machine() in ("x86_64", "amd64"),
            "These distribution cases require Linux x86_64")
    distribution = scratch / "relocated distribution"
    distribution.mkdir()
    extract_archive(args.archive, distribution)
    recorder.report["archive"] = {"path": str(args.archive), "sha256": sha256(args.archive)}
    manifest = distribution / "manifest.json"
    if manifest.is_file():
        recorder.report["manifest"] = json.loads(manifest.read_text(encoding="utf-8"))
    compiler = distribution / "bin/rustc"
    require(compiler.is_file(), "Compiler does not exist: %s" % compiler)
    recorder.report["compiler"] = {"path": str(compiler), "sha256": sha256(compiler),
                                   "bytes": compiler.stat().st_size}
    compile_cwd = scratch / "compilation cwd"
    compile_cwd.mkdir()
    fixture_source = args.fixtures
    saved_sources = recorder.output / "sources"
    saved_sources.mkdir()
    fixture_names = ["integration_macros.rs"] + [name + ".rs" for name in args.case]
    fixture_names.extend(CASES[name]["macro_fixture"] for name in args.case if "macro_fixture" in CASES[name])
    for filename in fixture_names:
        source = fixture_source / filename
        require(source.is_file(), "Fixture does not exist: %s" % source)
        shutil.copyfile(source, compile_cwd / filename)
        shutil.copyfile(source, saved_sources / filename)
    (compile_cwd / "fixture-input.txt").write_text("relative fixture contents\n", encoding="utf-8")
    shutil.copyfile(compile_cwd / "fixture-input.txt", saved_sources / "fixture-input.txt")
    version = recorder.run("rustc-version", [compiler, "-vV"], compile_cwd)
    require(command_succeeded(version), "Compiler version command failed")
    cc = shutil.which(args.cc, path=recorder.environment["PATH"])
    readelf = shutil.which(args.readelf, path=recorder.environment["PATH"])
    require(cc is not None and readelf is not None, "The worker requires a C linker and readelf")
    recorder.report["linker"] = cc
    common = [compiler, "--edition=2024", "--sysroot", distribution,
              "-Copt-level=0", "-Clinker=" + cc, "-Ctarget-feature=-crt-static"]
    library = compile_cwd / "libintegration_macros.so"
    macro_compile = recorder.run("compile-proc-macros", [
        *common, compile_cwd / "integration_macros.rs", "--crate-name=integration_macros",
        "--crate-type=proc-macro", "-o", library,
    ], compile_cwd)
    require(command_succeeded(macro_compile), "Procedural-macro fixture compilation failed")
    recorder.report["proc_macro_library"] = {"sha256": sha256(library), "bytes": library.stat().st_size}

    for name in args.case:
        specification = CASES[name]
        case = {"name": name, **specification, "passed": False}
        recorder.report["cases"].append(case)
        recorder.save()
        try:
            case_library = library
            macro_crate = "integration_macros"
            consumer_environment = None
            if "macro_fixture" in specification:
                macro_crate = specification["macro_crate"]
                case_library = compile_cwd / ("lib" + macro_crate + ".so")
                macro_command = [*common, compile_cwd / specification["macro_fixture"],
                                 "--crate-name=" + macro_crate, "--crate-type=proc-macro",
                                 "-o", case_library]
                if name == "lazy_binding":
                    macro_command.extend(["-Crelro-level=partial", "-Zplt=yes"])
                if name == "dynamic_std":
                    stdlib_directory = distribution / "lib/rustlib/x86_64-unknown-linux-gnu/lib"
                    std_libraries = sorted(stdlib_directory.glob("libstd-*.so"))
                    require(len(std_libraries) == 1, "Expected exactly one shared libstd in the distribution")
                    std_metadata = std_libraries[0].with_suffix(".rmeta")
                    require(std_metadata.is_file(), "The shared libstd requires its matching .rmeta file")
                    # ProcMacro prefers static dependencies. Supply std's .so
                    # and full .rmeta without its .rlib to select dynamic linkage.
                    macro_command.extend([
                        "-Cprefer-dynamic",
                        "--extern", "std=" + str(std_libraries[0]),
                        "--extern", "std=" + str(std_metadata),
                    ])
                    case["shared_std"] = str(std_libraries[0])
                    case["shared_std_metadata"] = str(std_metadata)
                case_macro = recorder.run("compile-" + macro_crate, macro_command, compile_cwd)
                case["macro_compile_command"] = case_macro["name"]
                require(command_succeeded(case_macro), "Dedicated procedural-macro fixture compilation failed")
                case["proc_macro_library"] = {"sha256": sha256(case_library), "bytes": case_library.stat().st_size}
                if name == "lazy_binding":
                    symbols = recorder.run("lazy-binding-symbols", [readelf, "--dyn-syms", "-W", case_library], compile_cwd)
                    relocations = recorder.run("lazy-binding-relocations", [readelf, "--relocs", "-W", case_library], compile_cwd)
                    tags = recorder.run("lazy-binding-dynamic-section", [readelf, "-dW", case_library], compile_cwd)
                    require(all(command_succeeded(item) for item in (symbols, relocations, tags)),
                            "Lazy-binding fixture ELF inspection failed")
                    unresolved = "proc_macro_case_unresolved_native"
                    require(any(unresolved in line and re.search(r"\bUND\b", line) for line in symbols["stdout"].splitlines()),
                            "Lazy-binding fixture lost its unresolved native symbol")
                    require(any(unresolved in line and "JUMP_SLOT" in line for line in relocations["stdout"].splitlines()),
                            "The unresolved native call must use a PLT relocation for lazy binding")
                    require("BIND_NOW" not in tags["stdout"] and not re.search(r"\(FLAGS_1\).*\bNOW\b", tags["stdout"]),
                            "Lazy-binding fixture unexpectedly requests eager binding")
                if name == "dynamic_std":
                    tags = recorder.run("dynamic-std-dynamic-section", [readelf, "-dW", case_library], compile_cwd)
                    require(command_succeeded(tags), "Shared-libstd fixture ELF inspection failed")
                    needed = re.findall(r"\(NEEDED\).*?\[(.*?)\]", tags["stdout"])
                    std_libraries = [item for item in needed if item.startswith("libstd-") and item.endswith(".so")]
                    require(std_libraries, "The macro DSO has no DT_NEEDED for the explicitly selected libstd")
                    for filename in std_libraries:
                        require((stdlib_directory / filename).is_file(), "The relocated distribution lacks %s" % filename)
                    case["dynamic_dependencies"] = needed
                    consumer_environment = {"LD_LIBRARY_PATH": str(stdlib_directory)}
                    case["loader_environment"] = consumer_environment
            executable = compile_cwd / name
            dependency_file = compile_cwd / (name + ".d")
            command = [*common, compile_cwd / (name + ".rs"), "--crate-name=" + name,
                       "--extern", macro_crate + "=" + str(case_library), "-o", executable,
                       "--emit=link,dep-info=" + str(dependency_file), "--error-format=json"]
            if name == "spans":
                command.append("--remap-path-prefix=" + str(compile_cwd) + "=/virtual/proc_macro_cases")
            if name == "incremental_derive":
                incremental_directory = compile_cwd / "incremental-derive-cache"
                command.extend(["-Cincremental=" + str(incremental_directory), "-Zcache-proc-macros"])
            compiled = recorder.run("compile-" + name, command, compile_cwd,
                                    environment_overrides=consumer_environment)
            case["compile_command"] = compiled["name"]
            case["diagnostics"] = diagnostics(compiled["stderr"])
            require("internal compiler error" not in compiled["stderr"].lower(), "Compiler reported an internal compiler error")
            if "panic_marker" in specification:
                require(compiled["status"] == "finished" and compiled.get("returncode", 0) > 0,
                        "Expected an ordinary compiler error for macro panic")
                errors = [item for item in case["diagnostics"] if item.get("level") == "error"]
                require(errors, "Expected structured compiler error diagnostics")
                error_text = json.dumps(errors, ensure_ascii=False)
                require("panicked" in error_text and specification["panic_marker"] in error_text,
                        "Panic diagnostic did not preserve the macro's panic message")
            else:
                require(command_succeeded(compiled), "Consumer compilation failed")
                if name == "output":
                    require("PROC_MACRO_CASE_STDOUT" in compiled["stdout"], "Macro stdout was lost")
                    require("PROC_MACRO_CASE_STDERR" in compiled["stderr"], "Macro stderr was lost")
                if name == "dynamic_std":
                    require("DYNAMIC_STD_RUNTIME_PASS tls_drops=1" in compiled["stdout"],
                            "Shared-libstd macro runtime checks did not complete")
                if name == "environment":
                    dependency_text = dependency_file.read_text(encoding="utf-8")
                    require("# env-dep:PROC_MACRO_CASE_TRACKED=tracked-value-λ" in dependency_text,
                            "Tracked environment value is absent from dep-info")
                    require("# env-dep:PROC_MACRO_CASE_MISSING" in dependency_text,
                            "Tracked missing environment variable is absent from dep-info")
                    require("fixture-input.txt" in dependency_text, "Tracked file is absent from dep-info")
                executable_arguments = [executable, compile_cwd]
                if name == "incremental_derive":
                    executable_arguments.append("42")
                if name == "dynamic_std":
                    executable_arguments.append(stdlib_directory)
                executed = recorder.run("run-" + name, executable_arguments, compile_cwd)
                case["run_command"] = executed["name"]
                require(command_succeeded(executed), "Consumer executable failed")
                require("CASE_PASS " + name in executed["stdout"], "Consumer success marker is absent")
                if name == "spans":
                    case["source_text_available"] = "SOURCE_TEXT_AVAILABLE true" in executed["stdout"]
                    require("SPAN_FILE /virtual/proc_macro_cases/spans.rs" in executed["stdout"],
                            "Span::file did not preserve the compiler's filename remapping")
                if name == "incremental_derive":
                    case["incremental_rounds"] = [{"name": "initial", "expected_value": 42,
                                                   "compile_command": compiled["name"], "run_command": executed["name"]}]
                    source = compile_cwd / "incremental_derive.rs"
                    for round_name, expected in (("unchanged", 42), ("source-changed", 43)):
                        if round_name == "source-changed":
                            text = source.read_text(encoding="utf-8")
                            require(text.count("const INPUT_VALUE: u32 = 40;") == 1, "Unexpected incremental fixture source")
                            require(text.count("Record") == 2, "Unexpected incremental derive input")
                            text = text.replace("const INPUT_VALUE: u32 = 40;", "const INPUT_VALUE: u32 = 41;")
                            source.write_text(text.replace("Record", "UpdatedRecord"), encoding="utf-8")
                            shutil.copyfile(source, saved_sources / "incremental_derive_changed.rs")
                        repeated = recorder.run("compile-incremental-derive-" + round_name, command, compile_cwd)
                        require(command_succeeded(repeated), "Incremental %s compilation failed" % round_name)
                        repeated_run = recorder.run("run-incremental-derive-" + round_name,
                                                    [executable, compile_cwd, expected], compile_cwd)
                        require(command_succeeded(repeated_run), "Incremental %s executable failed" % round_name)
                        require("CASE_PASS incremental_derive" in repeated_run["stdout"], "Incremental success marker is absent")
                        case["incremental_rounds"].append({"name": round_name, "expected_value": expected,
                                                           "compile_command": repeated["name"], "run_command": repeated_run["name"]})
            if dependency_file.is_file():
                shutil.copyfile(dependency_file, recorder.output / dependency_file.name)
                case["dependency_file"] = dependency_file.name
            case["passed"] = True
        except Exception as error:
            case["error"] = str(error)
            case["traceback"] = traceback.format_exc()
        recorder.save()
        print("CASE %s: %s" % (name, "PASS" if case["passed"] else "FAIL"), flush=True)
    recorder.report["passed"] = all(case["passed"] for case in recorder.report["cases"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=Path(__file__).resolve().parent / "fixtures",
                        help="Fixture directory")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append", choices=tuple(CASES))
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--readelf", default="readelf")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    args.case = args.case or list(CASES)
    require(args.timeout_seconds > 0, "Command timeout must be positive")
    args.archive = args.archive.resolve(strict=True)
    args.fixtures = args.fixtures.resolve(strict=True)
    if args.output is not None:
        output = args.output.resolve()
    elif os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR"):
        output = Path(os.environ["TEST_UNDECLARED_OUTPUTS_DIR"]).resolve()
    else:
        output = Path(tempfile.mkdtemp(prefix="proc-macro-integration-results-"))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="proc-macro-integration-", dir=os.environ.get("TEST_TMPDIR")) as temporary:
        scratch = Path(temporary)
        environment = {
            "PATH": "/usr/bin:/bin", "LC_ALL": "C",
            "TMPDIR": str(scratch), "RUST_BACKTRACE": "0",
            "PROC_MACRO_CASE_TRACKED": "tracked-value-λ",
        }
        recorder = Recorder(output, environment, args.timeout_seconds)
        try:
            run_cases(args, recorder, scratch)
        except Exception as error:
            recorder.report.update(passed=False, error=str(error), traceback=traceback.format_exc())
        finally:
            recorder.report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            recorder.save()
        print("INTEGRATION_RESULT %s" % ("PASS" if recorder.report.get("passed") else "FAIL"), flush=True)
        print("REPORT %s" % (output / "result.json"), flush=True)
        if recorder.report.get("error"):
            print(recorder.report["error"], flush=True)
        raise SystemExit(0 if recorder.report.get("passed") else 1)


if __name__ == "__main__":
    main()
