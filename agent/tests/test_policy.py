"""Unit tests for invoice signing and the agent's preflight policy mirror."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from eth_account import Account

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mandate.invoices import Invoice, evaluate, name_hash  # noqa: E402

MERCHANT = Account.create()
ACCOUNTING = Account.create()
ATTACKER = Account.create()
OWNER = Account.create()

NOW = 1_800_000_000

POLICY = {"perPaymentCap": 4_000_000, "dailyCap": 5_000_000, "approvalThreshold": 2_000_000, "policyExpiry": 0}
REGISTRY = [
    {"id": 1, "name": "Acme Studio LLC", "nameHash": name_hash("Acme Studio LLC"),
     "wallet": MERCHANT.address, "signer": MERCHANT.address, "active": True},
    {"id": 2, "name": "Ledger & Co. Accounting", "nameHash": name_hash("Ledger & Co. Accounting"),
     "wallet": ACCOUNTING.address, "signer": ACCOUNTING.address, "active": True},
]


def invoice(amount="1.20", name="Acme Studio LLC", wallet=None, signer=None, key=None, invoice_id="INV-1", valid_until=NOW + 86400):
    inv = Invoice(
        id=invoice_id,
        issuer={"name": name, "wallet": wallet or MERCHANT.address, "signer": signer or MERCHANT.address},
        payer="0x00000000000000000000000000000000000000AA",
        amount=amount,
        memo="November retainer",
        issued_at=NOW - 86400,
        due_at=NOW + 86400,
        valid_until=valid_until,
    )
    return inv.sign(key or MERCHANT.key)


def run(inv, *, spent=0, balance=5_000_000, used=None, policy=None):
    return evaluate(
        inv, REGISTRY, policy or POLICY, now=NOW, spent_today=spent,
        balance=balance, used_invoices=used or set(),
    )


def test_signature_roundtrip():
    inv = invoice()
    assert inv.recover().lower() == MERCHANT.address.lower()


def test_tampered_invoice_breaks_signature():
    inv = invoice()
    inv.amount = "9.99"
    assert inv.recover().lower() != MERCHANT.address.lower()


def test_clean_invoice_is_paid():
    d = run(invoice())
    assert d["decision"] == "pay"
    assert d["beneficiaryId"] == 1
    assert all(c["status"] in ("pass", "warn") for c in d["checks"])


def test_spoofed_payout_wallet_is_refused():
    inv = invoice(wallet=ATTACKER.address, signer=ATTACKER.address, key=ATTACKER.key)
    d = run(inv)
    assert d["decision"] == "refuse"
    assert d["reason"] == 6  # PAYEE_ADDRESS_MISMATCH


def test_invoice_signed_by_unregistered_key_is_refused():
    stranger = Account.create()
    inv = invoice(signer=MERCHANT.address, key=stranger.key)  # claims the vendor, signed by someone else
    d = run(inv)
    assert d["decision"] == "refuse"
    assert d["reason"] == 15  # INVOICE_SIGNATURE_INVALID


def test_unverified_merchant_is_refused():
    other = Account.create()
    inv = Invoice(
        id="INV-9", issuer={"name": "Unverified Ltd", "wallet": other.address, "signer": other.address},
        payer="0x00000000000000000000000000000000000000AA", amount="1.00", memo="x",
        issued_at=NOW, due_at=NOW + 3600, valid_until=NOW + 3600,
    ).sign(other.key)
    d = run(inv)
    assert d["decision"] == "refuse"
    assert d["reason"] == 3  # UNKNOWN_PAYEE


def test_duplicate_invoice_is_refused():
    inv = invoice()
    d = run(inv, used={inv.invoice_hash})
    assert d["reason"] == 7


def test_over_per_payment_cap_is_refused():
    d = run(invoice(amount="4.50"), policy={**POLICY, "perPaymentCap": 4_000_000})
    assert d["reason"] == 9


def test_over_daily_cap_is_refused():
    d = run(invoice(amount="3.50"), spent=2_000_000)
    assert d["reason"] == 10


def test_above_approval_line_needs_owner():
    d = run(invoice(amount="3.50", name="Ledger & Co. Accounting", wallet=ACCOUNTING.address, signer=ACCOUNTING.address, key=ACCOUNTING.key))
    assert d["decision"] == "needs_approval"
    assert d["reason"] == 11


def test_expired_invoice_is_refused():
    d = run(invoice(valid_until=NOW - 1))
    assert d["reason"] == 16


def test_underfunded_mandate_is_refused():
    d = run(invoice(amount="1.20"), balance=1_000_000)
    assert d["reason"] == 13


def test_inactive_payee_is_refused():
    registry = [dict(REGISTRY[0], active=False), REGISTRY[1]]
    d = evaluate(invoice(), registry, POLICY, now=NOW, spent_today=0, balance=5_000_000, used_invoices=set())
    assert d["reason"] == 4


def test_check_list_explains_every_rule():
    d = run(invoice())
    keys = {c["key"] for c in d["checks"]}
    assert {"registered", "name", "address", "signature", "duplicate", "deadline",
            "per_tx", "daily", "balance", "approval"} <= keys
