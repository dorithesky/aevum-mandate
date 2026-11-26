"""Command line for the Aevum Mandate demo.

    python -m mandate.cli deploy       # deploy MandateAccount to Aevum testnet
    python -m mandate.cli setup        # agent, policy, verified payees, funding
    python -m mandate.cli invoices     # issue the signed demo invoices
    python -m mandate.cli run <case>   # let the agent settle one invoice
    python -m mandate.cli scenario     # the whole story, then export web data
    python -m mandate.cli status
    python -m mandate.cli export
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eth_account import Account
from eth_utils import keccak, to_checksum_address

from . import config
from .chain import CHAIN_ID, Rpc, fmt, u
from .contract import Mandate, approve_payment, payment_from_invoice
from .invoices import REASONS, Invoice, evaluate, name_hash

ROOT = config.ROOT
CASES = ROOT / "state" / "cases.json"
INVOICES_DIR = ROOT / "invoices"


# --------------------------------------------------------------------------- io
def load_cases() -> dict:
    if CASES.exists():
        return json.loads(CASES.read_text())
    return {"cases": []}


def save_cases(data: dict) -> None:
    CASES.parent.mkdir(parents=True, exist_ok=True)
    CASES.write_text(json.dumps(data, indent=2), encoding="utf-8")


def key(env: dict, role: str) -> str:
    value = env.get(f"{role.upper()}_KEY")
    if not value:
        raise SystemExit(f"{role.upper()}_KEY missing from .env")
    return value


def registry_for(mandate: Mandate, sc: dict) -> list[dict]:
    names = {b["index"]: b["name"] for b in sc["beneficiaries"]}
    return mandate.state(names).beneficiaries


def chain_now(rpc: Rpc) -> int:
    return int(rpc.block()["timestamp"], 16)


# ---------------------------------------------------------------------- deploy
def cmd_deploy(args) -> None:
    env = config.load_env()
    rpc = Rpc(env.get("RPC_URL", "https://rpc-test.qday.info"))
    mandate = Mandate.deploy(rpc, key(env, "owner"), env.get("TUSD8"))
    info = {
        "address": mandate.address,
        "token": mandate.token(),
        "deployTx": getattr(mandate, "deploy_tx", None),
        "deployedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chainId": CHAIN_ID,
    }
    config.save_deployment(info)
    print(f"MandateAccount deployed at {mandate.address}")
    print(f"Explorer: https://explorer-test.qday.info/address/{mandate.address}")


def cmd_setup(args) -> None:
    env = config.load_env()
    sc = config.scenario()
    dep = config.deployment()
    rpc = Rpc(env.get("RPC_URL", "https://rpc-test.qday.info"))
    mandate = Mandate(rpc, dep["address"])
    owner_key = key(env, "owner")

    if mandate.agent().lower() != env["AGENT_ADDRESS"].lower():
        mandate.set_agent(owner_key, env["AGENT_ADDRESS"])
        print("agent set")

    mandate.set_policy(
        owner_key,
        u(sc["policy"]["perPaymentCap"]),
        u(sc["policy"]["dailyCap"]),
        u(sc["policy"]["approvalThreshold"]),
        int(datetime.now(timezone.utc).timestamp()) + int(sc["policy"].get("validDays", 30)) * 86400,
    )
    print("policy set")

    existing = {b["wallet"].lower() for b in mandate.state().beneficiaries}
    for b in sc["beneficiaries"]:
        wallet = to_checksum_address(env[f"{b['wallet']}_ADDRESS"])
        if wallet.lower() in existing:
            continue
        mandate.add_beneficiary(
            owner_key,
            bytes.fromhex(name_hash(b["name"])[2:]),
            wallet,
            to_checksum_address(env[f"{b['signer']}_ADDRESS"]),
        )
        print(f"payee #{b['index']} {b['name']} verified")

    target = u(sc["funding"])
    balance = mandate.balance()
    if balance < target:
        mandate.fund(owner_key, target - balance)
        print(f"funded {fmt(target - balance)} tUSD8")

    print(json.dumps(mandate.state({b["index"]: b["name"] for b in sc["beneficiaries"]}).to_json(), indent=2))


# --------------------------------------------------------------------- invoices
def cmd_invoices(args) -> None:
    env = config.load_env()
    sc = config.scenario()
    dep = config.deployment()
    INVOICES_DIR.mkdir(exist_ok=True)
    now = int(datetime.now(timezone.utc).timestamp())
    data = load_cases()
    data["cases"] = []

    for spec in sc["invoices"]:
        issuer_name = spec["name"]
        wallet = to_checksum_address(env[f"{spec['wallet']}_ADDRESS"])
        signer_role = spec["signer"]
        inv = Invoice(
            id=spec.get("invoiceId", spec["caseId"]),
            issuer={"name": issuer_name, "wallet": wallet, "signer": to_checksum_address(env[f"{signer_role}_ADDRESS"])},
            payer=dep["address"],
            amount=spec["amount"],
            memo=spec["memo"],
            issued_at=now - 86400,
            due_at=now + int(spec.get("dueInDays", 7)) * 86400,
            valid_until=now + int(spec.get("validDays", 14)) * 86400,
            meta={
                "from": spec.get("from", issuer_name),
                "subject": spec.get("subject", ""),
                "note": spec.get("note", ""),
                "kind": spec.get("kind", "invoice"),
            },
        )
        inv.sign(key(env, signer_role.lower()))
        path = INVOICES_DIR / f"{spec['caseId']}.json"
        path.write_text(json.dumps(inv.to_json(), indent=2), encoding="utf-8")
        data["cases"].append({
            "caseId": spec["caseId"],
            "path": str(path.relative_to(ROOT)),
            "status": "pending",
            "decision": None,
            "txHash": None,
        })
        print(f"issued {spec['caseId']} — {spec['amount']} tUSD8 to {issuer_name} ({wallet[:10]}…)")

    save_cases(data)


# -------------------------------------------------------------------- agent run
def _context(env, sc, mandate, invoice):
    rpc = mandate.rpc
    now = chain_now(rpc)
    registry = registry_for(mandate, sc)
    state = mandate.state({b["index"]: b["name"] for b in sc["beneficiaries"]})
    used = set()
    for case in load_cases()["cases"]:
        if case["status"] == "settled":
            path = ROOT / case["path"]
            if path.exists():
                used.add(Invoice.load(str(path)).invoice_hash)
    decision = evaluate(
        invoice,
        registry,
        state.policy(),
        now=now,
        spent_today=state.spent_today,
        balance=state.balance,
        used_invoices=used,
    )
    return decision, state, now


def run_case(case_id: str, approve: bool = False, record: bool = True) -> dict:
    """Evaluate one invoice and act on it. Returns the result the UI renders."""
    env = config.load_env()
    sc = config.scenario()
    dep = config.deployment()
    rpc = Rpc(env.get("RPC_URL", "https://rpc-test.qday.info"))
    mandate = Mandate(rpc, dep["address"])
    data = load_cases()
    case = next((c for c in data["cases"] if c["caseId"] == case_id), None)
    if not case:
        raise SystemExit(f"unknown case {case_id}")
    invoice = Invoice.load(str(ROOT / case["path"]))
    decision, state, now = _context(env, sc, mandate, invoice)

    tx = None
    outcome = decision["decision"]
    if decision["decision"] == "refuse":
        tx = mandate.record_refusal(
            key(env, "agent"), invoice.invoice_hash, decision["reason"],
            invoice.amount_atomic, invoice.name_hash,
        )
        case["status"] = "refused"
        outcome = "refused"
    elif decision["decision"] == "needs_approval":
        if not approve:
            case["status"] = "needs_approval"
            outcome = "needs_approval"
        else:
            payment = payment_from_invoice(invoice, decision["beneficiaryId"], now, now)
            approval = approve_payment(mandate, key(env, "owner"), payment)
            tx = mandate.pay(key(env, "agent"), payment, approval)
            case["status"] = "settled"
            outcome = "owner_approved"
    else:
        payment = payment_from_invoice(invoice, decision["beneficiaryId"], now, now)
        tx = mandate.pay(key(env, "agent"), payment)
        case["status"] = "settled"
        outcome = "auto_paid"

    decision["outcome"] = outcome
    case["decision"] = decision
    case["txHash"] = tx
    case["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if record:
        save_cases(data)
    return {
        "caseId": case_id,
        "invoice": invoice.to_json(),
        "status": case["status"],
        "decision": decision,
        "txHash": tx,
        "txUrl": f"https://explorer-test.qday.info/tx/{tx}" if tx else None,
        "state": mandate.state({b["index"]: b["name"] for b in sc["beneficiaries"]}).to_json(),
    }


def cmd_run(args) -> None:
    result = run_case(args.case, approve=args.approve)
    invoice = result["invoice"]
    decision = result["decision"]
    print(f"\n{invoice['id']} — {invoice['amount']} tUSD8 — {invoice['issuer']['name']} → {invoice['issuer']['wallet']}")
    for c in decision["checks"]:
        mark = {"pass": "✓", "fail": "✗", "warn": "!"}.get(c["status"], "·")
        print(f"  {mark} {c['label']:<28} {c['detail']}")
    print(f"  decision: {decision['decision'].upper()} ({decision['reasonLabel']})")
    if decision["decision"] == "needs_approval" and args.approve:
        print("  owner signature collected (EIP-712) — the owner's key never reaches the agent")
    if result["txUrl"]:
        print(f"  tx: {result['txUrl']}")


def cmd_scenario(args) -> None:
    for step in ("deploy", "setup", "invoices"):
        print(f"\n== {step} ==")
        globals()[f"cmd_{step}"](args)
    cases = [i["caseId"] for i in config.scenario()["invoices"]]
    for case_id in cases:
        print(f"\n== run {case_id} ==")
        run_args = argparse.Namespace(case=case_id, approve=True)
        cmd_run(run_args)
        time.sleep(1)
    cmd_export(args)


# -------------------------------------------------------------------- reporting
def cmd_status(args) -> None:
    env = config.load_env()
    sc = config.scenario()
    dep = config.deployment()
    rpc = Rpc(env.get("RPC_URL", "https://rpc-test.qday.info"))
    mandate = Mandate(rpc, dep["address"])
    state = mandate.state({b["index"]: b["name"] for b in sc["beneficiaries"]})
    print(json.dumps(state.to_json(), indent=2))
    print(f"balance: {fmt(state.balance)} tUSD8")


def build_payload() -> dict:
    env = config.load_env()
    sc = config.scenario()
    dep = config.deployment()
    rpc = Rpc(env.get("RPC_URL", "https://rpc-test.qday.info"))
    mandate = Mandate(rpc, dep["address"])
    state = mandate.state({b["index"]: b["name"] for b in sc["beneficiaries"]})
    data = load_cases()
    cases = []
    for case in data["cases"]:
        invoice = Invoice.load(str(ROOT / case["path"]))
        cases.append({
            **invoice.to_json(),
            "caseId": case["caseId"],
            "status": case["status"],
            "decision": case["decision"],
            "txHash": case["txHash"],
            "updatedAt": case.get("updatedAt"),
        })
    events = mandate.events(0)
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "live",
        "network": {"name": "QDay Aevum Testnet", "chainId": CHAIN_ID, "rpc": env.get("RPC_URL"),
                    "explorer": "https://explorer-test.qday.info"},
        "mandate": {
            "address": state.address,
            "owner": state.owner,
            "agent": state.agent,
            "token": state.token,
            "balance": state.balance,
            "spentToday": state.spent_today,
            "remainingToday": state.remaining_today,
            "paused": state.paused,
            "policy": state.policy(),
            "beneficiaries": state.beneficiaries,
        },
        "company": sc.get("company", "Oakline Studio"),
        "cases": cases,
        "events": events,
        "totals": {
            "settled": sum(1 for c in cases if c["status"] == "settled"),
            "refused": sum(1 for c in cases if c["status"] == "refused"),
            "paid": sum(Invoice.load(str(ROOT / c["path"])).amount_atomic
                        for c in data["cases"] if c["status"] == "settled"),
        },
    }


def cmd_export(args) -> None:
    payload = build_payload()
    out = ROOT / "web" / "data" / "run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} — {payload['totals']}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="mandate")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("deploy", "setup", "invoices", "status", "export", "scenario"):
        sub.add_parser(name)
    run = sub.add_parser("run")
    run.add_argument("case")
    run.add_argument("--approve", action="store_true", help="owner co-signs if the amount is above the line")
    args = parser.parse_args()
    globals()[f"cmd_{args.command}"](args)


if __name__ == "__main__":
    main()
