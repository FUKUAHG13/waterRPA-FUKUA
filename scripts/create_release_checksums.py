"""Create or verify SHA256SUMS for external release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from pathlib import Path


CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  ([^\\/\r\n]+)$")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_checksums(paths: list[Path]) -> str:
    names = [path.name for path in paths]
    if len(names) != len({name.casefold() for name in names}):
        raise ValueError("校验文件名不能重复")
    if any(not path.is_file() for path in paths):
        raise ValueError("校验对象必须是普通文件")
    if any(CHECKSUM_LINE.fullmatch(f"{'0' * 64}  {name}") is None for name in names):
        raise ValueError("校验文件名包含不安全字符")
    return "".join(f"{hash_file(path)}  {path.name}\n" for path in paths)


def parse_checksums(text: str) -> dict[str, str]:
    if not text or not text.endswith("\n"):
        raise ValueError("SHA256SUMS 必须是以换行结尾的非空 ASCII 文本")
    entries: dict[str, str] = {}
    for line in text.splitlines():
        match = CHECKSUM_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"SHA256SUMS 条目格式无效：{line!r}")
        checksum, name = match.groups()
        key = name.casefold()
        if key in entries:
            raise ValueError(f"SHA256SUMS 包含重复文件名：{name}")
        entries[key] = checksum
    return entries


def verify_checksums(paths: list[Path], text: str) -> dict:
    entries = parse_checksums(text)
    expected_names = {path.name.casefold(): path for path in paths}
    if len(expected_names) != len(paths) or set(entries) != set(expected_names):
        raise ValueError("SHA256SUMS 文件列表与待校验发布物不一致")
    for key, path in expected_names.items():
        if not path.is_file() or entries[key] != hash_file(path):
            raise ValueError(f"SHA256 校验失败：{path.name}")
    return {"verified": True, "file_count": len(paths)}


def atomic_write(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    paths = [path.resolve() for path in args.files]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit(f"Release artifact not found: {missing}")
    expected = build_checksums(paths)
    output = args.output.resolve()
    if output in paths:
        raise SystemExit("SHA256SUMS output must not overwrite an input artifact")
    if args.check:
        if not output.is_file():
            raise SystemExit("SHA256SUMS verification failed: file not found")
        try:
            verify_checksums(paths, output.read_text(encoding="ascii"))
        except (OSError, UnicodeError, ValueError) as error:
            raise SystemExit(f"SHA256SUMS verification failed: {error}") from error
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(output, expected)
    print(expected, end="")


if __name__ == "__main__":
    main()
