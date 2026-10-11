"""Storing and loading regression baselines."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from testbench.compare import Snapshot


class BaselineStore:
    """Baselines live under ``<output_dir>/baselines/<suite>/<scenario>/<check>.json``."""

    def __init__(self, output_dir: Path) -> None:
        self.root = output_dir / "baselines"

    def path(self, suite: str, scenario: str, check: str) -> Path:
        return self.root / suite / scenario / f"{check}.json"

    def load(self, suite: str, scenario: str, check: str) -> Snapshot | None:
        path = self.path(suite, scenario, check)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Snapshot.from_json(data["snapshot"])

    def save(self, suite: str, scenario: str, check: str, snapshot: Snapshot) -> Path:
        path = self.path(suite, scenario, check)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "snapshot": snapshot.to_json(),
        }
        path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
        return path
