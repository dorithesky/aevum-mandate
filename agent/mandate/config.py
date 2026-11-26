"""Config loading: .env for keys, config/scenario.json for the demo business."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path | None = None) -> dict[str, str]:
    path = path or ROOT / ".env"
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    values.update({k: v for k, v in os.environ.items() if k in values or k.startswith(("OWNER_", "AGENT_", "MERCHANT_", "ATTACKER_", "RPC_", "CHAIN_", "TUSD8", "FAUCET"))})
    return values


def scenario(path: Path | None = None) -> dict:
    path = path or ROOT / "config" / "scenario.json"
    return json.loads(path.read_text(encoding="utf-8"))


def deployment(path: Path | None = None) -> dict:
    path = path or ROOT / "state" / "deployment.json"
    if not path.exists():
        raise SystemExit("no deployment yet: run `python -m mandate.cli deploy` first")
    return json.loads(path.read_text(encoding="utf-8"))


def save_deployment(data: dict) -> None:
    path = ROOT / "state" / "deployment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
