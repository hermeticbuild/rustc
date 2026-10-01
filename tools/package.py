"""Create a relocatable Rust compiler directory and reproducible gzip archive."""

import argparse
import gzip
import json
from pathlib import Path
import shutil
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--source-metadata", required=True, type=Path)
    parser.add_argument("--variant", required=True, choices=("upstream", "static"))
    parser.add_argument("--feature", action="append", default=[])
    parser.add_argument("--file", nargs=2, action="append", default=[])
    args = parser.parse_args()
    source_metadata = json.loads(args.source_metadata.read_text())
    bootstrap = "nightly/" + source_metadata["nightly"]
    args.directory.mkdir(parents=True, exist_ok=True)
    for destination, source in args.file:
        relative = Path(destination)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Invalid installed filename: {destination}")
        output = args.directory / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, output)
        output.chmod(0o755 if relative.parts[0] == "bin" else 0o644)
    (args.directory / "manifest.json").write_text(json.dumps({
        "variant": args.variant,
        "rust_commit": source_metadata["rust_commit"],
        "llvm_commit": source_metadata["llvm_commit"],
        "nightly": source_metadata["nightly"],
        "host": "x86_64-unknown-linux-gnu",
        "bootstrap": bootstrap,
        "stdlib": "upstream " + bootstrap,
        "allocator": "system",
        "glibc": "dynamic",
        "build_features": sorted(args.feature),
        "rust_lto": "thin" if "thin_lto" in args.feature else "default",
        "llvm_lto": "thin" if "thin_lto" in args.feature else "off",
    }, sort_keys=True, indent=2) + "\n")
    with args.archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for entry in sorted(args.directory.rglob("*")):
                    info = archive.gettarinfo(str(entry), str(entry.relative_to(args.directory)))
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    if entry.is_file():
                        with entry.open("rb") as content:
                            archive.addfile(info, content)
                    else:
                        archive.addfile(info)


if __name__ == "__main__":
    main()
