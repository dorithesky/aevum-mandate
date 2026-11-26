"""Signed invoices (EIP-712) and the agent's preflight policy mirror.

The contract is the source of truth. `evaluate` is a pure mirror of
MandateAccount._check plus the two things only the agent can verify: the
merchant's signature on the invoice and whether the invoice is well formed.
Its job is to explain a decision before any gas is spent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address

CHAIN_ID = 44005
INVOICE_DOMAIN = "Aevum Mandate Invoice"
INVOICE_VERSION = "1"

REASONS = {
    0: "OK",
    1: "PAUSED",
    2: "POLICY_OR_INVOICE_EXPIRED",
    3: "UNKNOWN_PAYEE",
    4: "PAYEE_INACTIVE",
    5: "PAYEE_NAME_MISMATCH",
    6: "PAYEE_ADDRESS_MISMATCH",
    7: "DUPLICATE_INVOICE",
    8: "ZERO_AMOUNT",
    9: "OVER_PER_PAYMENT_CAP",
    10: "OVER_DAILY_CAP",
    11: "APPROVAL_REQUIRED",
    12: "INVALID_APPROVAL",
    13: "INSUFFICIENT_BALANCE",
    14: "NOT_AGENT",
    15: "INVOICE_SIGNATURE_INVALID",
    16: "INVOICE_EXPIRED",
    17: "MALFORMED_INVOICE",
}

INVOICE_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
    ],
    "Invoice": [
        {"name": "id", "type": "string"},
        {"name": "issuerName", "type": "string"},
        {"name": "payee", "type": "address"},
        {"name": "amount", "type": "uint256"},
        {"name": "memo", "type": "string"},
        {"name": "issuedAt", "type": "uint256"},
        {"name": "dueAt", "type": "uint256"},
        {"name": "validUntil", "type": "uint256"},
    ],
}


def name_hash(name: str) -> str:
    return "0x" + keccak(text=name).hex()


@dataclass
class Invoice:
    id: str
    issuer: dict[str, str]  # name, wallet, signer
    payer: str  # mandate account address
    amount: str  # decimal string, e.g. "1.20"
    memo: str
    issued_at: int
    due_at: int
    valid_until: int
    signature: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- helpers
    @property
    def amount_atomic(self) -> int:
        return int(Decimal(self.amount) * 1_000_000)

    @property
    def name_hash(self) -> str:
        return name_hash(self.issuer["name"])

    @property
    def invoice_hash(self) -> str:
        """On-chain invoice id: hash over the issuer, id and payer."""
        body = f"{self.id}|{self.issuer['wallet']}|{self.payer}".encode()
        return "0x" + keccak(body).hex()

    def typed_data(self) -> dict:
        return {
            "types": INVOICE_TYPES,
            "primaryType": "Invoice",
            "domain": {"name": INVOICE_DOMAIN, "version": INVOICE_VERSION, "chainId": CHAIN_ID},
            "message": {
                "id": self.id,
                "issuerName": self.issuer["name"],
                "payee": to_checksum_address(self.issuer["wallet"]),
                "amount": self.amount_atomic,
                "memo": self.memo,
                "issuedAt": self.issued_at,
                "dueAt": self.due_at,
                "validUntil": self.valid_until,
            },
        }

    def sign(self, signer_key: str) -> "Invoice":
        signed = Account.sign_typed_data(signer_key, full_message=self.typed_data())
        self.signature = signed.signature.hex()
        if not self.signature.startswith("0x"):
            self.signature = "0x" + self.signature
        return self

    def recover(self) -> str | None:
        if not self.signature:
            return None
        try:
            return Account.recover_message(
                encode_typed_data(full_message=self.typed_data()), signature=self.signature
            )
        except Exception:
            return None

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "issuer": self.issuer,
            "payer": self.payer,
            "amount": self.amount,
            "memo": self.memo,
            "issuedAt": self.issued_at,
            "dueAt": self.due_at,
            "validUntil": self.valid_until,
            "signature": self.signature,
            "invoiceHash": self.invoice_hash,
            "meta": self.meta,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Invoice":
        return cls(
            id=data["id"],
            issuer=data["issuer"],
            payer=data["payer"],
            amount=str(data["amount"]),
            memo=data.get("memo", ""),
            issued_at=int(data["issuedAt"]),
            due_at=int(data["dueAt"]),
            valid_until=int(data["validUntil"]),
            signature=data.get("signature", ""),
            meta=data.get("meta", {}),
        )

    @classmethod
    def load(cls, path: str) -> "Invoice":
        with open(path, encoding="utf-8") as fh:
            return cls.from_json(json.load(fh))


@dataclass
class Check:
    key: str
    label: str
    status: str  # pass | fail | warn | skip
    detail: str
    code: int | None = None

    def to_json(self) -> dict:
        return {"key": self.key, "label": self.label, "status": self.status, "detail": self.detail, "code": self.code}


def evaluate(
    invoice: Invoice,
    registry: list[dict],
    policy: dict,
    *,
    now: int,
    spent_today: int,
    balance: int,
    used_invoices: set[str],
) -> dict:
    """Run every preflight check and return the decision the agent will take."""
    checks: list[Check] = []
    amount = invoice.amount_atomic

    def add(key, label, ok, detail, code, warn=False):
        status = "pass" if ok else ("warn" if warn else "fail")
        checks.append(Check(key, label, status, detail, None if ok else code))

    # 1. Is the payee one the owner has already verified?
    by_name = next((r for r in registry if r["nameHash"].lower() == invoice.name_hash.lower()), None)
    by_wallet = next((r for r in registry if r["wallet"].lower() == invoice.issuer["wallet"].lower()), None)
    payee = by_name if (by_name and by_wallet and by_name["id"] == by_wallet["id"]) else (by_name or by_wallet)
    add("registered", "Verified payee", payee is not None,
        f"Beneficiary #{payee['id']} — {payee['name']}" if payee else "Payee is not in the mandate's verified registry", 3)
    active = bool(payee and payee["active"])
    add("active", "Payee active", active, "Registry entry is active" if active else "Registry entry is disabled", 4)

    # 2. Confirmation of payee: name and address must both match the registry.
    name_ok = by_name is not None
    add("name", "Payee name matches", name_ok,
        f"{invoice.issuer['name']} matches the verified name" if name_ok
        else f"'{invoice.issuer['name']}' does not match any verified name", 5)
    addr_ok = by_name is not None and by_wallet is not None and by_name["id"] == by_wallet["id"]
    add("address", "Payout address matches", addr_ok,
        "Payout address equals the registered wallet" if addr_ok
        else ("Payout address differs from the verified wallet" if name_ok
              else "Payout address is not a verified wallet"), 6)

    # 3. Is the invoice really from that merchant?
    signer = invoice.recover()
    expected = (invoice.issuer.get("signer") or "").lower()
    ok_sig = bool(signer) and signer.lower() == expected and expected != ""
    add(
        "signature",
        "Invoice signature",
        ok_sig,
        f"Signed by {signer}" if signer else "No valid EIP-712 signature",
        15,
    )

    # 4. Replay and deadline.
    dup = invoice.invoice_hash.lower() in {k.lower() for k in used_invoices}
    add("duplicate", "Not already paid", not dup, "Invoice id is unused" if not dup else "Invoice id was already settled", 7)
    live = now <= invoice.valid_until
    add("deadline", "Within settlement window", live,
        f"Valid until {_ts(invoice.valid_until)}" if live else "Invoice settlement window has closed", 16)

    # 5. Mandate limits.
    per_ok = amount <= policy["perPaymentCap"]
    add("per_tx", "Per-payment cap", per_ok,
        f"{_amt(amount)} of {_amt(policy['perPaymentCap'])} allowed" if per_ok
        else f"{_amt(amount)} exceeds the {_amt(policy['perPaymentCap'])} per-payment cap", 9)
    remaining = max(0, policy["dailyCap"] - spent_today)
    daily_ok = amount <= remaining
    add("daily", "Daily cap", daily_ok,
        f"{_amt(remaining)} left of {_amt(policy['dailyCap'])} today" if daily_ok
        else f"{_amt(amount)} exceeds the {_amt(remaining)} left today", 10)
    funded = balance >= amount
    add("balance", "Mandate funded", funded, f"{_amt(balance)} available" if funded else "Mandate balance is too low", 13)

    # 6. Human-in-the-loop line.
    needs_approval = amount > policy["approvalThreshold"]
    checks.append(
        Check("approval", "Owner approval", "warn" if needs_approval else "pass",
              "Above the owner-approval line — the owner must co-sign" if needs_approval
              else f"At or below the {_amt(policy['approvalThreshold'])} approval line", None)
    )

    failed = [c for c in checks if c.status == "fail"]
    if failed:
        decision = "refuse"
        reason = failed[0].code or 17
    elif needs_approval:
        decision = "needs_approval"
        reason = 11
    else:
        decision = "pay"
        reason = 0

    return {
        "decision": decision,
        "reason": reason,
        "reasonLabel": REASONS.get(reason, "UNKNOWN"),
        "beneficiaryId": payee["id"] if payee else None,
        "checks": [c.to_json() for c in checks],
    }


def _amt(atomic: int) -> str:
    return f"{Decimal(atomic) / 1_000_000:.2f} tUSD8"


def _ts(value: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
