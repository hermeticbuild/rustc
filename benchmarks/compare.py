#!/usr/bin/env python3
"""Compare two Linux rustc distributions with paired, alternating measurements."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time


EXPECTED_COMMIT = "21b707e3f97e0b522ebd2f277a862339625ad83f"
EXPECTED_LLVM_COMMIT = "1b9c0d5ff9bbe7634aead059efe6b11a7eeba145"
VARIANTS = ("upstream", "static")


def clean_environment():
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("LD_", "DYLD_", "RUST", "CARGO")):
            del env[key]
    env["LC_ALL"] = "C"
    return env


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compiler_info(directory, env, description):
    binary = directory / "bin/rustc"
    version = subprocess.run(
        [binary, "-vV"], env=env, capture_output=True, text=True, timeout=30, check=True
    ).stdout.strip()
    fields = dict(line.split(": ", 1) for line in version.splitlines() if ": " in line)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise ValueError(f"Distribution manifest must be a JSON object: {manifest_path}")
    files = [path for path in directory.rglob("*") if path.is_file() and not path.is_symlink()]
    return {
        "directory": str(directory),
        "binary_sha256": sha256(binary),
        "binary_bytes": binary.stat().st_size,
        "compiler_libraries": {
            str(path.relative_to(directory)): {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in sorted(files)
            if path.parent == directory / "lib" and ".so" in path.name
        },
        "distribution_regular_file_bytes": sum(path.stat().st_size for path in files),
        "version": version,
        "version_fields": fields,
        "manifest": manifest,
        "build_description": description,
    }


def host_info():
    cpu_model = None
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    governor_files = sorted(Path("/sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_governor"))
    governors = sorted({path.read_text().strip() for path in governor_files})
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": cpu_model,
        "cpu_count": os.cpu_count(),
        "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "cpu_governors": governors,
        "load_average_at_start": os.getloadavg(),
        "python": sys.version,
    }


def measure(command, *, cwd, env):
    # wait4 reports this process's usage, unlike the cumulative RUSAGE_CHILDREN maximum.
    with tempfile.TemporaryFile() as output:
        start = time.perf_counter_ns()
        process = subprocess.Popen(
            command, cwd=cwd, env=env, stdout=output, stderr=output, start_new_session=True
        )
        try:
            _, status, usage = os.wait4(process.pid, 0)
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            _, status, _ = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
            raise
        elapsed_ns = time.perf_counter_ns() - start
        process.returncode = os.waitstatus_to_exitcode(status)
        if process.returncode:
            output.seek(0)
            diagnostic = output.read().decode(errors="replace")
            raise RuntimeError(f"Command failed ({process.returncode}): {command}\n{diagnostic}")
    return {
        "elapsed_ns": elapsed_ns,
        "user_cpu_ns": round(usage.ru_utime * 1_000_000_000),
        "system_cpu_ns": round(usage.ru_stime * 1_000_000_000),
        "max_rss_bytes": usage.ru_maxrss * 1024,
        "minor_page_faults": usage.ru_minflt,
        "major_page_faults": usage.ru_majflt,
        "voluntary_context_switches": usage.ru_nvcsw,
        "involuntary_context_switches": usage.ru_nivcsw,
    }


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def median_bootstrap_interval(values, seed):
    rng = random.Random(seed)
    resampled = [statistics.median(rng.choices(values, k=len(values))) for _ in range(4000)]
    return [percentile(resampled, 0.025), percentile(resampled, 0.975)]


def summarize(samples, workload_names):
    summaries = {}
    for index, name in enumerate(workload_names):
        observations = [sample for sample in samples if sample["workload"] == name and not sample["warmup"]]
        variants = {}
        for variant in VARIANTS:
            rows = [sample for sample in observations if sample["variant"] == variant]
            elapsed = [row["elapsed_ns"] for row in rows]
            variants[variant] = {
                "median_elapsed_ns": statistics.median(elapsed),
                "min_elapsed_ns": min(elapsed),
                "max_elapsed_ns": max(elapsed),
                "p25_elapsed_ns": percentile(elapsed, 0.25),
                "p75_elapsed_ns": percentile(elapsed, 0.75),
                "median_max_rss_bytes": statistics.median(row["max_rss_bytes"] for row in rows),
            }
        paired = {}
        for row in observations:
            paired.setdefault(row["pair"], {})[row["variant"]] = row["elapsed_ns"]
        speedups = [pair["upstream"] / pair["static"] for _, pair in sorted(paired.items())]
        interval = median_bootstrap_interval(speedups, seed=index)
        conclusion = "static" if interval[0] > 1 else "upstream" if interval[1] < 1 else "inconclusive"
        summaries[name] = {
            "variants": variants,
            "paired_static_speedups": speedups,
            "median_paired_static_speedup": statistics.median(speedups),
            "median_paired_static_speedup_bootstrap_95pct_interval": interval,
            "faster_in_this_sample": conclusion,
        }
    return summaries


def write_json(path, report):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def prepare_proc_macro_libraries(directories, source, work, env, linker, report, output):
    """Build each compiler's macro DSO before the timed consumer compilations."""
    linker_path = shutil.which(linker, path=env.get("PATH"))
    if linker_path is None:
        raise RuntimeError(f"Procedural-macro preparation requires a C linker: {linker}")
    linker_path = str(Path(linker_path).resolve())
    linker_version = subprocess.run(
        [linker_path, "--version"], env=env, capture_output=True, text=True, timeout=30, check=True
    ).stdout.strip()
    libraries = {}
    for variant in VARIANTS:
        directory = work / variant
        directory.mkdir()
        library = directory / "librecord_derive.so"
        command = [
            str(directories[variant] / "bin/rustc"), str(source),
            "--crate-name=record_derive", "--crate-type=proc-macro", "--edition=2024",
            "-Copt-level=2", "-Cdebuginfo=0", "-Ccodegen-units=1",
            "-Ctarget-feature=-crt-static", "-Clinker=" + linker_path, "-o", str(library),
        ]
        completed = subprocess.run(
            command, cwd=work, env=env, capture_output=True, text=True, timeout=300, check=False
        )
        preparation = {
            "kind": "proc_macro_library", "variant": variant,
            "timed": False, "command": command, "returncode": completed.returncode,
            "source": str(source), "source_sha256": sha256(source),
            "stdout": completed.stdout, "stderr": completed.stderr,
            "compiler_binary_sha256": report["compilers"][variant]["binary_sha256"],
            "linker": {"path": linker_path, "sha256": sha256(Path(linker_path)), "version": linker_version},
        }
        if completed.returncode == 0:
            preparation["library"] = {
                "path": str(library), "sha256": sha256(library), "bytes": library.stat().st_size,
            }
        report["preparations"].append(preparation)
        write_json(output, report)
        if completed.returncode:
            raise RuntimeError(
                f"Procedural-macro library compilation failed for {variant}: {command}"
                f"\n{completed.stdout}{completed.stderr}"
            )
        libraries[variant] = library
    return libraries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-dir", required=True, type=Path)
    parser.add_argument("--static-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="JSON report, updated after each invocation")
    parser.add_argument("--runs", type=int, default=15, help="Measured pairs per workload; minimum 3")
    parser.add_argument("--warmups", type=int, default=2, help="Unmeasured pairs per workload; minimum 1")
    parser.add_argument(
        "--workload", action="append", metavar="NAME",
        help="Select an exact workload name; repeat to select more; omitted means all workloads",
    )
    parser.add_argument("--expected-commit", default=EXPECTED_COMMIT)
    parser.add_argument("--expected-llvm-commit", default=EXPECTED_LLVM_COMMIT)
    parser.add_argument("--upstream-build-description", default="unreported")
    parser.add_argument("--static-build-description", default="unreported")
    parser.add_argument("--fixtures", type=Path, default=Path(__file__).resolve().parent / "fixtures")
    parser.add_argument(
        "--proc-macro-fixtures", type=Path,
        default=Path(__file__).resolve().parent / "proc_macro_fixtures",
    )
    parser.add_argument("--proc-macro-linker", default="cc", help="C linker used only for untimed macro DSO preparation")
    parser.add_argument("--work-dir", type=Path, help="Parent directory for temporary compiler outputs")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Linux is required for ELF distributions and wait4 RSS units")
    if args.runs < 3 or args.warmups < 1:
        parser.error("Use at least 3 measured pairs and 1 warmup pair per workload")
    env = clean_environment()
    directories = {"upstream": args.upstream_dir.resolve(), "static": args.static_dir.resolve()}
    descriptions = {"upstream": args.upstream_build_description, "static": args.static_build_description}
    compilers = {variant: compiler_info(directories[variant], env, descriptions[variant]) for variant in VARIANTS}
    for variant, compiler in compilers.items():
        if compiler["version_fields"].get("commit-hash") != args.expected_commit:
            parser.error(f"{variant} does not report expected commit {args.expected_commit}")
        manifest = compiler["manifest"]
        for field, expected in (
            ("variant", variant), ("rust_commit", args.expected_commit),
            ("llvm_commit", args.expected_llvm_commit),
        ):
            if manifest.get(field) != expected:
                parser.error(f"{variant} manifest {field} is {manifest.get(field)!r}; expected {expected!r}")
        if manifest.get("host") != compiler["version_fields"].get("host"):
            parser.error(f"{variant} manifest host disagrees with rustc -vV")
    for key in ("commit-hash", "host", "release", "LLVM version"):
        values = [compilers[variant]["version_fields"].get(key) for variant in VARIANTS]
        if not all(values) or values[0] != values[1]:
            parser.error(f"Compiler {key} fields differ or are missing: {values}")
    for key in ("rust_commit", "llvm_commit", "host", "bootstrap", "stdlib", "allocator", "glibc"):
        values = [compilers[variant]["manifest"].get(key) for variant in VARIANTS]
        if not all(values) or values[0] != values[1]:
            parser.error(f"Distribution manifest {key} fields differ or are missing: {values}")
    fixtures = sorted(args.fixtures.resolve().glob("*.rs"))
    if not fixtures:
        parser.error(f"No Rust fixtures found in {args.fixtures}")
    workloads = [{"name": "startup", "flags": ["--version"], "source": None, "extension": None}]
    configurations = {
        "frontend": (["--emit=metadata", "-C", "opt-level=0"], ".rmeta"),
        "debug": (["--emit=obj", "-C", "opt-level=0", "-C", "debuginfo=2", "-C", "codegen-units=1"], ".o"),
        "optimized": (["--emit=obj", "-C", "opt-level=2", "-C", "debuginfo=0", "-C", "codegen-units=1"], ".o"),
    }
    for source in fixtures:
        for configuration, (flags, extension) in configurations.items():
            workloads.append({
                "name": f"{source.stem}/{configuration}",
                "source": str(source),
                "source_sha256": sha256(source),
                "flags": ["--crate-type=lib", "--edition=2024", "--crate-name", source.stem, *flags],
                "extension": extension,
            })
    macro_directory = args.proc_macro_fixtures.resolve()
    macro_source = macro_directory / "record_derive.rs"
    macro_consumer = macro_directory / "proc_macro_records.rs"
    for source in (macro_source, macro_consumer):
        if not source.is_file():
            parser.error(f"Missing procedural-macro fixture: {source}")
    for configuration in ("frontend", "debug"):
        flags, extension = configurations[configuration]
        workloads.append({
            "name": f"proc_macro_records/{configuration}",
            "source": str(macro_consumer), "source_sha256": sha256(macro_consumer),
            "flags": ["--crate-type=lib", "--edition=2024", "--crate-name=proc_macro_records", *flags],
            "extension": extension, "proc_macro": "record_derive",
            "macro_source": str(macro_source), "macro_source_sha256": sha256(macro_source),
            "derive_invocations": 64, "fields_per_record": 8,
        })
    if args.workload is not None:
        selected_names = set(args.workload)
        if not selected_names or "" in selected_names:
            parser.error("Workload selection must contain nonempty exact names")
        unknown = sorted(selected_names - {workload["name"] for workload in workloads})
        if unknown:
            parser.error(f"Unknown workloads: {unknown}")
        workloads = [workload for workload in workloads if workload["name"] in selected_names]
    if not workloads:
        parser.error("No workloads selected")
    requires_proc_macro = any(workload.get("proc_macro") for workload in workloads)
    report = {
        "schema_version": 1,
        "status": "running",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": host_info(),
        "compilers": compilers,
        "runs": args.runs,
        "warmups": args.warmups,
        "workload_selection": {
            "requested": args.workload,
            "selected": [workload["name"] for workload in workloads],
        },
        "method": {
            "order": "AB/BA alternating paired measurements, balanced starting variant across workloads",
            "clock": "time.perf_counter_ns around Popen and wait4, including process startup",
            "memory": "os.wait4 child ru_maxrss, Linux KiB converted to bytes; may include Python's pre-exec memory, so this is not compiler-only peak RSS",
            "cache": "warm filesystem cache; outputs removed before every invocation; no incremental compilation",
            "compiler_environment": "LD_*, DYLD_*, RUST*, and CARGO* variables removed; LC_ALL=C",
            "speedup": "upstream elapsed / static elapsed; values above 1 favor static",
            "interval": "4000 deterministic bootstrap resamples of paired speedup medians; exploratory 95% interval",
            "scope": "timed synthetic compile-only workloads, without an external linker; results compare complete compiler builds",
        },
        "warnings": [
            "The confidence intervals do not correct for multiple workloads or prove performance on other programs.",
            "Different compiler LTO configurations prevent attributing a difference exclusively to linkage.",
        ],
        "workloads": workloads,
        "preparations": [],
        "samples": [],
    }
    if requires_proc_macro:
        report["method"].update({
            "proc_macros": "64 eight-field WireRecord derives per consumer compilation; each compiler builds the identical macro source once before timing; the consumer compilation includes macro loading, macro execution and compiler callbacks",
            "preparation": "Macro DSO compilation and its external C linker run are excluded from all samples; macro DSOs remain available for every warmup and measured invocation",
        })
    if args.runs < 10:
        report["warnings"].append("Fewer than 10 measured pairs: treat speedups and confidence intervals as preliminary.")
    if any(description == "unreported" for description in descriptions.values()):
        report["warnings"].append("Compiler build flags/LTO mode are unreported for at least one variant.")
    if compilers["upstream"]["binary_sha256"] == compilers["static"]["binary_sha256"]:
        report["warnings"].append("Both rustc binaries have the same SHA-256; this run measures repeatability, not two variants.")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, report)
    try:
        with tempfile.TemporaryDirectory(prefix="rustc-benchmark-", dir=args.work_dir) as temporary:
            work = Path(temporary)
            macro_libraries = {}
            if requires_proc_macro:
                macro_libraries = prepare_proc_macro_libraries(
                    directories, macro_source, work, env, args.proc_macro_linker, report, output
                )
            for workload_index, workload in enumerate(workloads):
                destination = work / ("output" + (workload["extension"] or ""))
                print(f"{workload['name']}: {args.warmups} warmup pairs, {args.runs} measured pairs", flush=True)
                for warmup, count in ((True, args.warmups), (False, args.runs)):
                    for pair in range(count):
                        order = VARIANTS if (pair + workload_index) % 2 == 0 else tuple(reversed(VARIANTS))
                        for position, variant in enumerate(order):
                            destination.unlink(missing_ok=True)
                            command = [str(directories[variant] / "bin/rustc")]
                            if workload["source"]:
                                command += [workload["source"], *workload["flags"], "-o", str(destination)]
                                if workload.get("proc_macro"):
                                    command += ["--extern", "record_derive=" + str(macro_libraries[variant])]
                            else:
                                command += workload["flags"]
                            measurement = measure(command, cwd=work, env=env)
                            report["samples"].append({
                                "workload": workload["name"],
                                "variant": variant,
                                "warmup": warmup,
                                "pair": pair,
                                "position_in_pair": position,
                                "command": command,
                                **measurement,
                            })
                            write_json(output, report)
        report["summary"] = summarize(report["samples"], [workload["name"] for workload in workloads])
        report["status"] = "complete"
    except BaseException as error:
        report["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        report["error"] = str(error)
        raise
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(output, report)
    print("\nWorkload                         upstream ms    static ms    static speedup    paired 95% interval")
    for name, result in report["summary"].items():
        upstream = result["variants"]["upstream"]["median_elapsed_ns"] / 1_000_000
        static = result["variants"]["static"]["median_elapsed_ns"] / 1_000_000
        low, high = result["median_paired_static_speedup_bootstrap_95pct_interval"]
        print(f"{name:32} {upstream:11.3f} {static:12.3f} {result['median_paired_static_speedup']:15.3f}x [{low:.3f}, {high:.3f}]")
    print(f"\nFull measurements: {output}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        print(f"Benchmark failed: {error}", file=sys.stderr)
        sys.exit(1)
