"""Smoke-test the demo API against a local chain (no faucet needed).

    python scripts/api_smoke.py

Starts anvil + mock tUSD8, sets up the mandate and invoices, then drives the
same HTTP routes the desk uses: GET /api/state, POST /api/run/<case>.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from eth_account import Account  # noqa: E402

ANVIL_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
RPC_PORT, WEB_PORT = 8547, 8799


def http(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{WEB_PORT}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.loads(res.read())


def main() -> int:
    anvil = subprocess.Popen(
        [os.path.expanduser("~/.foundry/bin/anvil"), "--port", str(RPC_PORT), "--chain-id", "44005", "--silent"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    server = None
    try:
        from mandate import cli, config
        from mandate.chain import Rpc

        rpc = None
        for _ in range(40):
            try:
                rpc = Rpc(f"http://127.0.0.1:{RPC_PORT}")
                break
            except Exception:
                time.sleep(0.25)

        art = json.loads((ROOT / "contracts/out/MandateAccount.t.sol/MockUSD.json").read_text())
        token = rpc.wait(rpc.send(ANVIL_KEY, None, bytes.fromhex(art["bytecode"]["object"][2:]), gas=3_000_000))["contractAddress"]

        env = config.load_env()
        for addr in (env["OWNER_ADDRESS"], env["AGENT_ADDRESS"]):
            rpc.send(ANVIL_KEY, addr, b"", value=10**19, gas=21000)
        from mandate.chain import encode_call
        rpc.wait(rpc.send(ANVIL_KEY, token, encode_call("mint(address,uint256)", ["address", "uint256"],
                                                        [env["OWNER_ADDRESS"], 5_000_000]), gas=200_000))

        os.environ["RPC_URL"] = f"http://127.0.0.1:{RPC_PORT}"
        os.environ["TUSD8"] = token
        for stale in ("deployment.json", "cases.json"):
            p = ROOT / "state" / stale
            if p.exists():
                p.unlink()
        cli.cmd_deploy(None)
        cli.cmd_setup(None)
        cli.cmd_invoices(None)

        server = subprocess.Popen([sys.executable, str(ROOT / "server/app.py")],
                                  env={**os.environ, "PORT": str(WEB_PORT)},
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            try:
                http("GET", "/api/health")
                break
            except Exception:
                time.sleep(0.25)

        state = http("GET", "/api/state")
        print("state:", state["mandate"]["balance"], "tUSD8,", len(state["cases"]), "cases",
              [c["status"] for c in state["cases"]])

        paid = http("POST", "/api/run/INV-2026-0412", {})
        print("auto pay:", paid["status"], paid["decision"]["outcome"], paid["txHash"][:18])

        refused = http("POST", "/api/run/INV-2026-0517", {})
        print("spoof:", refused["status"], refused["decision"]["reasonLabel"], refused["txHash"][:18])

        pending = http("POST", "/api/run/INV-2026-0620", {})
        print("large (no approval):", pending["status"], pending["decision"]["decision"])
        approved = http("POST", "/api/run/INV-2026-0620", {"approve": True})
        print("large (owner signed):", approved["status"], approved["decision"]["outcome"], approved["txHash"][:18])

        final = http("GET", "/api/state")
        print("final balance:", final["mandate"]["balance"], "spent today:", final["mandate"]["spentToday"],
              "events:", len(final["events"]))
        ok = (final["totals"]["settled"] == 2 and final["totals"]["refused"] == 1
              and final["mandate"]["spentToday"] == 4_700_000)
        print("API SMOKE OK" if ok else "API SMOKE MISMATCH")
        return 0 if ok else 2
    finally:
        if server:
            server.terminate()
        anvil.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
