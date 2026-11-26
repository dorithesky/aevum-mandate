"""Generate docs/EVIDENCE.md from the chain and the local run record.

    python scripts/make_evidence.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from mandate import config, cli  # noqa: E402
from mandate.chain import fmt  # noqa: E402
from mandate.invoices import REASONS  # noqa: E402
from eth_utils import to_checksum_address  # noqa: E402

EXPLORER = "https://explorer-test.qday.info"


def main() -> int:
    payload = cli.build_payload()
    dep = config.deployment()
    m = payload["mandate"]
    lines = [
        "# Evidence — Aevum Testnet",
        "",
        f"Generated {payload['generatedAt']} from `{payload['network']['rpc']}` (chain {payload['network']['chainId']}).",
        "Every row is a transaction on QDay Aevum Testnet; open the hash on the explorer.",
        "",
        "## Deployment",
        "",
        "| Item | Value |",
        "| --- | --- |",
        f"| MandateAccount | [`{m['address']}`]({EXPLORER}/address/{m['address']}) |",
        f"| Deploy transaction | [`{dep.get('deployTx')}`]({EXPLORER}/tx/{dep.get('deployTx')}) |",
        f"| Deploy block | {dep.get('deployBlock')} (gas {dep.get('deployGasUsed')}) |",
        f"| tUSD8 | [`{m['token']}`]({EXPLORER}/address/{m['token']}) |",
        f"| Owner (human) | `{to_checksum_address(m['owner'])}` |",
        f"| Agent (hot key) | `{to_checksum_address(m['agent'])}` |",
        "",
        "## Mandate at a glance",
        "",
        "| | |",
        "| --- | --- |",
        f"| Balance | {fmt(m['balance'])} tUSD8 |",
        f"| Spent today | {fmt(m['spentToday'])} of {fmt(m['policy']['dailyCap'])} tUSD8 |",
        f"| Per-payment cap | {fmt(m['policy']['perPaymentCap'])} tUSD8 |",
        f"| Owner approval above | {fmt(m['policy']['approvalThreshold'])} tUSD8 |",
        f"| Policy expiry | {m['policy']['policyExpiry']} (unix) |",
        f"| Verified payees | {len(m['beneficiaries'])} |",
        "",
        "## Invoice decisions",
        "",
        "| Invoice | Payee | Amount | Decision | Reason | Transaction |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for c in payload["cases"]:
        dec = c.get("decision") or {}
        reason = REASONS.get(dec.get("reason"), dec.get("reasonLabel", ""))
        outcome = dec.get("outcome", c["status"])
        tx = f"[`{c['txHash'][:18]}…`]({EXPLORER}/tx/{c['txHash']})" if c.get("txHash") else "—"
        lines.append(
            f"| `{c['id']}` | {c['issuer']['name']} | {c['amount']} tUSD8 | {outcome} | {reason} | {tx} |"
        )

    lines += [
        "",
        "## On-chain events",
        "",
        "| Block | Event | Detail | Transaction |",
        "| --- | --- | --- | --- |",
    ]
    for e in payload["events"]:
        if e["type"] == "settled":
            detail = f"settled {fmt(e['amount'])} tUSD8 to `{e['payee']}`" + (
                " (owner co-signed)" if e.get("approvedByOwner") else ""
            )
            kind = "PaymentSettled"
        else:
            detail = f"refused: {REASONS.get(e['reason'], e['reason'])} ({fmt(e['amount'])} tUSD8)"
            kind = "RefusalRecorded"
        lines.append(f"| {e['block']} | {kind} | {detail} | [`{e['txHash'][:18]}…`]({EXPLORER}/tx/{e['txHash']}) |")

    lines += [
        "",
        "## Reproduce",
        "",
        "```bash",
        "git clone https://github.com/dorithesky/aevum-mandate && cd aevum-mandate",
        "cd contracts && forge test && cd ..",
        "python -m pytest agent/tests -q",
        "python scripts/local_e2e.py     # anvil rehearsal, same code path",
        "```",
        "",
        "The public desk reads these same addresses: "
        f"https://dorithesky.github.io/aevum-mandate/",
        "",
    ]
    out = ROOT / "docs" / "EVIDENCE.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}: {len(payload['cases'])} cases, {len(payload['events'])} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
