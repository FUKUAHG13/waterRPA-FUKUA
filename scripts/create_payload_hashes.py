"""Create the in-release offline payload hash list."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fukua_rpa.integrity import (  # noqa: E402
    PAYLOAD_MANIFEST_NAME,
    atomic_write_manifest,
    build_payload_manifest,
    verify_payload,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    release_dir = args.release_dir.resolve()
    output = release_dir / PAYLOAD_MANIFEST_NAME
    if args.check:
        report = verify_payload(release_dir)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report.get("ok"):
            raise SystemExit("Payload verification failed")
        return
    manifest = build_payload_manifest(release_dir)
    atomic_write_manifest(output, manifest)
    print(
        json.dumps(
            {key: value for key, value in manifest.items() if key != "files"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
