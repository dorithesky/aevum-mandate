"""End-to-end run against a local anvil chain with the same code paths as the testnet.

    python scripts/local_e2e.py

Starts anvil (chain id 44005 to exercise the same EIP-1559 signing path),
deploys a mock tUSD8, then runs deploy -> setup -> invoices -> agent decisions
for every demo case. Proves the agent, ABI encoding and contract agree before
spending testnet gas. Requires `anvil` on PATH (~/.foundry/bin).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from eth_account import Account  # noqa: E402
from eth_utils import keccak  # noqa: E402

ANVIL_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
PORT = 8545


def main() -> int:
    anvil = os.path.expanduser("~/.foundry/bin/anvil")
    proc = subprocess.Popen(
        [anvil, "--port", str(PORT), "--chain-id", "44005", "--silent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        from mandate.chain import Rpc, encode_call
        from mandate.contract import Mandate
        from mandate import cli, config

        rpc = None
        for _ in range(40):
            try:
                rpc = Rpc(f"http://127.0.0.1:{PORT}")
                break
            except Exception:
                time.sleep(0.25)
        if rpc is None:
            print("anvil did not start")
            return 1

        # mock stablecoin from the compiled test artifact
        art = json.loads((ROOT / "contracts/out/MandateAccount.t.sol/MockUSD.json").read_text())
        deployer = Account.from_key(ANVIL_KEY)
        tx = rpc.send(ANVIL_KEY, None, bytes.fromhex(art["bytecode"]["object"][2:]), gas=3_000_000)
        token = rpc.wait(tx)["contractAddress"]

        env = config.load_env()
        owner, agent = env["OWNER_ADDRESS"], env["AGENT_ADDRESS"]
        for addr in (owner, agent):
            rpc.send(ANVIL_KEY, addr, b"", value=10**19, gas=21000)
        mint = encode_call("mint(address,uint256)", ["address", "uint256"], [owner, 5_000_000])
        rpc.wait(rpc.send(ANVIL_KEY, token, mint, gas=200_000))

        os.environ["RPC_URL"] = f"http://127.0.0.1:{PORT}"
        os.environ["TUSD8"] = token
        (ROOT / "state").mkdir(exist_ok=True)
        for stale in ("deployment.json", "cases.json"):
            p = ROOT / "state" / stale
            if p.exists():
                p.unlink()

        print("== deploy ==")
        cli.cmd_deploy(None)
        print("== setup ==")
        cli.cmd_setup(None)
        print("== invoices ==")
        cli.cmd_invoices(None)
        for case in config.scenario()["invoices"]:
            print(f"== run {case['caseId']} ==")
            cli.cmd_run(type("A", (), {"case": case["caseId"], "approve": True})())
        print("== export ==")
        cli.cmd_export(None)

        data = json.loads((ROOT / "web/data/run.json").read_text())
        print("\nsummary:", json.dumps(data["totals"]))
        for case in data["cases"]:
            print(f"  {case['id']:<22} {case['status']:<10} {case['decision']['reasonLabel']}")
        ok = (
            data["totals"]["settled"] == 2
            and data["totals"]["refused"] == 3
            and data["mandate"]["balance"] == 300_000
        )
        print("E2E OK" if ok else "E2E MISMATCH")
        return 0 if ok else 2
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
