"""Create a deterministic per-file hash manifest for an onedir release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def build_manifest(release_dir):
    release_dir = Path(release_dir).resolve()
    files = []
    aggregate = hashlib.sha256()
    total_bytes = 0
    for path in sorted(release_dir.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        relative = path.relative_to(release_dir).as_posix()
        size = path.stat().st_size
        checksum = file_hash(path)
        total_bytes += size
        files.append({"path": relative, "size": size, "sha256": checksum})
        aggregate.update(f"{checksum}  {relative}\n".encode("utf-8"))
    return {
        "format": "fukuaRPA_onedir_manifest",
        "version": 1,
        "build": release_dir.name,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "directory_sha256": aggregate.hexdigest(),
        "files": files,
    }


def verify_manifest(release_dir, manifest_path):
    expected = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    actual = build_manifest(release_dir)
    for key in ("format", "version", "build", "file_count", "total_bytes", "directory_sha256", "files"):
        if expected.get(key) != actual.get(key):
            raise RuntimeError(f"Release manifest mismatch in {key}")
    return actual


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    release_dir = args.release_dir.resolve()
    if not release_dir.is_dir():
        raise SystemExit(f"Release directory not found: {release_dir}")
    output = args.output.resolve() if args.output else release_dir.parent / f"{release_dir.name}_manifest.json"
    if args.check:
        if not output.is_file():
            raise SystemExit(f"Manifest not found: {output}")
        manifest = verify_manifest(release_dir, output)
    else:
        manifest = build_manifest(release_dir)
        atomic_write(output, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: manifest[key] for key in manifest if key != "files"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
