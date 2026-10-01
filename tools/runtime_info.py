"""Write OS, glibc, package, and CPU details for the worker executing this action."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def read_text(path):
    try:
        return {"status": "ok", "text": Path(path).read_text()}
    except OSError as error:
        return {"status": "unavailable", "error": str(error)}


def command_info(arguments):
    executable = shutil.which(arguments[0], path=os.defpath)
    if executable is None:
        return {"status": "unavailable", "command": arguments}
    command = [executable, *arguments[1:]]
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": os.defpath, "LC_ALL": "C"},
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "command": command, "timeout_seconds": 30}
    except OSError as error:
        return {"status": "unavailable", "command": command, "error": str(error)}
    return {
        "status": "ok" if result.returncode == 0 else "failed",
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def cpu_info():
    source = read_text("/proc/cpuinfo")
    fields = {"model name", "vendor_id", "cpu family", "model", "stepping", "flags"}
    values = {key: set() for key in fields}
    if source["status"] == "ok":
        for line in source["text"].splitlines():
            key, separator, value = line.partition(":")
            key = key.strip()
            if separator and key in values:
                values[key].add(value.strip())
    result = {
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "cpuinfo_status": source["status"],
        "cpuinfo": {key: sorted(value) for key, value in sorted(values.items()) if value},
    }
    if hasattr(os, "sched_getaffinity"):
        try:
            result["affinity"] = sorted(os.sched_getaffinity(0))
        except OSError as error:
            result["affinity_error"] = str(error)
    return result


def runtime_info():
    try:
        gnu_libc = {"status": "ok", "value": os.confstr("CS_GNU_LIBC_VERSION")}
    except (AttributeError, OSError, ValueError) as error:
        gnu_libc = {"status": "unavailable", "error": str(error)}
    packages = command_info([
        "dpkg-query", "--show", "--showformat=${binary:Package}\t${Version}\t${db:Status-Status}\n",
        "libc6", "libc6-dev", "libgcc-s1",
    ])
    packages["versions"] = {}
    for line in packages.get("stdout", "").splitlines():
        columns = line.split("\t")
        if len(columns) == 3:
            packages["versions"][columns[0]] = {"version": columns[1], "status": columns[2]}
    libc_name, libc_version = platform.libc_ver()
    return {
        "schema_version": 1,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "The worker executing the runtime_info action; other actions may execute on different workers.",
        "os": {"system": platform.system(), "release": platform.release(), "version": platform.version()},
        "platform_libc_ver": {"name": libc_name, "version": libc_version},
        "gnu_libc_confstr": gnu_libc,
        "os_release": read_text("/etc/os-release"),
        "ldd_version": command_info(["ldd", "--version"]),
        "dpkg_query": packages,
        "cpu": cpu_info(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(runtime_info(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
