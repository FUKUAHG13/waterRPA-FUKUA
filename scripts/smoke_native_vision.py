"""Run the real-screen native/OpenCV parity smoke test from source."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fukua_rpa.native_smoke import run_native_smoke  # noqa: E402


def main() -> int:
    report = run_native_smoke(str(ROOT))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
