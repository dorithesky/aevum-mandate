"""Thin, dependency-light wrapper around MandateAccount + tUSD8."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_abi import encode as abi_encode
from eth_utils import to_checksum_address

from .chain import (
    CHAIN_ID,
    TUSD8,
    Rpc,
    decode_words,
    encode_call,
    event_topic,
    topic_address,
    u,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "contracts" / "out" / "MandateAccount.sol" / "MandateAccount.json"

PAYMENT_TYPE = "(bytes32,uint256,address,bytes32,uint256,bytes32,uint256,uint256,uint256)"


@dataclass
class MandateState:
    address: str
    owner: str
    agent: str
    paused: bool
    per_payment_cap: int
    daily_cap: int
    approval_threshold: int
    policy_expiry: int
    spent_today: int
    remaining_today: int
    balance: int
    beneficiary_count: int
    beneficiaries: list[dict]
    chain_id: int
    token: str

    def policy(self) -> dict:
        return {
            "perPaymentCap": self.per_payment_cap,
            "dailyCap": self.daily_cap,
            "approvalThreshold": self.approval_threshold,
            "policyExpiry": self.policy_expiry,
        }

    def to_json(self) -> dict:
        return {
            "address": self.address,
            "owner": self.owner,
            "agent": self.agent,
            "paused": self.paused,
            "policy": self.policy(),
            "spentToday": self.spent_today,
            "remainingToday": self.remaining_today,
            "balance": self.balance,
            "beneficiaries": self.beneficiaries,
            "chainId": self.chain_id,
            "token": self.token,
            "explorer": f"https://explorer-test.qday.info/address/{self.address}",
        }


class Mandate:
    def __init__(self, rpc: Rpc, address: str):
        self.rpc = rpc
        self.address = to_checksum_address(address)

    # ------------------------------------------------------------------ deploy
    @classmethod
    def deploy(cls, rpc: Rpc, key: str, token: str = TUSD8) -> "Mandate":
        artifact = json.loads(ARTIFACT.read_text())
        bytecode = artifact["bytecode"]["object"]
        from eth_account import Account

        owner = Account.from_key(key).address
        data = bytes.fromhex(bytecode[2:]) + abi_encode(["address", "address"], [to_checksum_address(token), owner])
        tx_hash = rpc.send(key, None, data, gas=3_000_000, label="deploy MandateAccount")
        receipt = rpc.wait(tx_hash)
        address = to_checksum_address(receipt["contractAddress"])
        deployed = cls(rpc, address)
        deployed.deploy_tx = tx_hash
        return deployed

    # ------------------------------------------------------------------- reads
    def _view(self, signature: str, types: list[str], values: list[Any], out: list[str]):
        raw = self.rpc.eth_call(self.address, encode_call(signature, types, values))
        return decode_words(raw, out)

    def owner(self) -> str:
        return self._view("owner()", [], [], ["address"])[0]

    def agent(self) -> str:
        return self._view("agent()", [], [], ["address"])[0]

    def token(self) -> str:
        return self._view("token()", [], [], ["address"])[0]

    def paused(self) -> bool:
        return self._view("paused()", [], [], ["bool"])[0]

    def beneficiary_count(self) -> int:
        return self._view("beneficiaryCount()", [], [], ["uint256"])[0]

    def beneficiary(self, index: int) -> dict:
        name_hash, wallet, signer, active = self._view(
            "getBeneficiary(uint256)", ["uint256"], [index], ["bytes32", "address", "address", "bool"]
        )
        return {
            "id": index,
            "nameHash": "0x" + name_hash.hex(),
            "wallet": wallet,
            "signer": signer,
            "active": active,
        }

    def policy(self) -> dict:
        per_tx, daily, threshold, expiry = self._view(
            "perPaymentCap()", [], [], ["uint256"]
        ) + self._view("dailyCap()", [], [], ["uint256"]) + self._view(
            "approvalThreshold()", [], [], ["uint256"]
        ) + self._view("policyExpiry()", [], [], ["uint256"])
        return {
            "perPaymentCap": per_tx,
            "dailyCap": daily,
            "approvalThreshold": threshold,
            "policyExpiry": expiry,
        }

    def spent_today(self) -> int:
        return self._view("spentToday()", [], [], ["uint256"])[0]

    def remaining_today(self) -> int:
        return self._view("remainingToday()", [], [], ["uint256"])[0]

    def balance(self) -> int:
        return self.rpc.token_balance(self.token(), self.address)

    def invoice_used(self, invoice_hash: str) -> bool:
        return bool(self._view("invoiceUsed(bytes32)", ["bytes32"], [bytes.fromhex(invoice_hash[2:])], ["bool"])[0])

    def preview(self, payment: dict, approval: bytes = b"") -> int:
        return self._view(
            "preview(" + PAYMENT_TYPE + ",bytes)",
            [PAYMENT_TYPE, "bytes"],
            [_payment_tuple(payment), approval],
            ["uint8"],
        )[0]

    def approval_digest(self, payment: dict) -> bytes:
        return self._view(
            "approvalDigest(bytes32,uint256,address,uint256,uint256,uint256)",
            ["bytes32", "uint256", "address", "uint256", "uint256", "uint256"],
            [
                bytes.fromhex(payment["invoiceHash"][2:]),
                payment["beneficiaryId"],
                payment["payee"],
                payment["amount"],
                payment["validUntil"],
                payment["nonce"],
            ],
            ["bytes32"],
        )[0]

    def state(self, names: dict[int, str] | None = None) -> MandateState:
        count = self.beneficiary_count()
        registry = []
        for i in range(1, count + 1):
            entry = self.beneficiary(i)
            entry["name"] = (names or {}).get(i, "")
            registry.append(entry)
        return MandateState(
            address=self.address,
            owner=self.owner(),
            agent=self.agent(),
            paused=self.paused(),
            per_payment_cap=self.policy()["perPaymentCap"],
            daily_cap=self.policy()["dailyCap"],
            approval_threshold=self.policy()["approvalThreshold"],
            policy_expiry=self.policy()["policyExpiry"],
            spent_today=self.spent_today(),
            remaining_today=self.remaining_today(),
            balance=self.balance(),
            beneficiary_count=count,
            beneficiaries=registry,
            chain_id=CHAIN_ID,
            token=self.token(),
        )

    # ------------------------------------------------------------------ writes
    def set_agent(self, key: str, agent: str) -> str:
        tx = self.rpc.send(key, self.address, encode_call("setAgent(address)", ["address"], [agent]), label="setAgent")
        self.rpc.wait(tx)
        return tx

    def set_policy(self, key: str, per_tx: int, daily: int, threshold: int, expiry: int = 0) -> str:
        data = encode_call(
            "setPolicy(uint256,uint256,uint256,uint256)",
            ["uint256", "uint256", "uint256", "uint256"],
            [per_tx, daily, threshold, expiry],
        )
        tx = self.rpc.send(key, self.address, data, label="setPolicy")
        self.rpc.wait(tx)
        return tx

    def add_beneficiary(self, key: str, name_hash_bytes: bytes, wallet: str, signer: str) -> str:
        data = encode_call(
            "addBeneficiary(bytes32,address,address)", ["bytes32", "address", "address"], [name_hash_bytes, wallet, signer]
        )
        tx = self.rpc.send(key, self.address, data, label="addBeneficiary")
        self.rpc.wait(tx)
        return tx

    def pay(self, key: str, payment: dict, approval: bytes = b"") -> str:
        data = encode_call("pay(" + PAYMENT_TYPE + ",bytes)", [PAYMENT_TYPE, "bytes"], [_payment_tuple(payment), approval])
        tx = self.rpc.send(key, self.address, data, label="pay")
        self.rpc.wait(tx)
        return tx

    def record_refusal(self, key: str, invoice_hash: str, reason: int, amount: int, payee_name_hash: str) -> str:
        data = encode_call(
            "recordRefusal(bytes32,uint8,uint256,bytes32)",
            ["bytes32", "uint8", "uint256", "bytes32"],
            [bytes.fromhex(invoice_hash[2:]), reason, amount, bytes.fromhex(payee_name_hash[2:])],
        )
        tx = self.rpc.send(key, self.address, data, label="recordRefusal")
        self.rpc.wait(tx)
        return tx

    def fund(self, key: str, amount: int) -> str:
        """Move tUSD8 from an EOA into the mandate."""
        data = encode_call("transfer(address,uint256)", ["address", "uint256"], [self.address, amount])
        tx = self.rpc.send(key, self.token(), data, label="fund mandate")
        self.rpc.wait(tx)
        return tx

    # ------------------------------------------------------------------ events
    def events(self, from_block: int = 0) -> list[dict]:
        settled = event_topic("PaymentSettled(bytes32,uint256,address,uint256,bool,bytes32,uint256)")
        refused = event_topic("RefusalRecorded(bytes32,address,uint8,uint256,bytes32)")
        out: list[dict] = []
        for log in self.rpc.logs(self.address, [[settled, refused]], from_block):
            topic0 = log["topics"][0]
            block = int(log["blockNumber"], 16)
            if topic0 == settled:
                invoice_id = "0x" + log["topics"][1][-64:]
                beneficiary_id = int(log["topics"][2], 16)
                payee = to_checksum_address("0x" + log["topics"][3][-40:])
                amount, approved, memo_hash, due_date = decode_words(
                    log["data"], ["uint256", "bool", "bytes32", "uint256"]
                )
                out.append({
                    "type": "settled", "block": block, "txHash": log["transactionHash"],
                    "invoiceHash": invoice_id, "beneficiaryId": beneficiary_id, "payee": payee,
                    "amount": amount, "approvedByOwner": approved,
                    "memoHash": "0x" + memo_hash.hex(), "dueDate": due_date,
                })
            else:
                invoice_id = "0x" + log["topics"][1][-64:]
                agent = to_checksum_address("0x" + log["topics"][2][-40:])
                reason, amount, name_hash = decode_words(log["data"], ["uint8", "uint256", "bytes32"])
                out.append({
                    "type": "refused", "block": block, "txHash": log["transactionHash"],
                    "invoiceHash": invoice_id, "agent": agent, "reason": reason,
                    "amount": amount, "payeeNameHash": "0x" + name_hash.hex(),
                })
        return sorted(out, key=lambda e: (e["block"], e["txHash"]))


def _payment_tuple(payment: dict) -> tuple:
    return (
        bytes.fromhex(payment["invoiceHash"][2:]),
        payment["beneficiaryId"],
        to_checksum_address(payment["payee"]),
        bytes.fromhex(payment["payeeNameHash"][2:]),
        payment["amount"],
        bytes.fromhex(payment["memoHash"][2:]),
        payment["dueDate"],
        payment["validUntil"],
        payment["nonce"],
    )


def payment_from_invoice(invoice, beneficiary_id: int, nonce: int, chain_now: int) -> dict:
    from eth_utils import keccak

    return {
        "invoiceHash": invoice.invoice_hash,
        "beneficiaryId": beneficiary_id,
        "payee": to_checksum_address(invoice.issuer["wallet"]),
        "payeeNameHash": invoice.name_hash,
        "amount": invoice.amount_atomic,
        "memoHash": "0x" + keccak(text=invoice.memo or invoice.id).hex(),
        "dueDate": invoice.due_at,
        "validUntil": invoice.valid_until,
        "nonce": nonce,
    }


def approve_payment(mandate: Mandate, owner_key: str, payment: dict) -> bytes:
    from eth_account import Account

    digest = mandate.approval_digest(payment)
    signed = Account.unsafe_sign_hash(digest, private_key=owner_key)
    return signed.signature
