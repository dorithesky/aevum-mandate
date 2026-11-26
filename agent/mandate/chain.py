"""QDay Aevum testnet client: JSON-RPC transport, EIP-1559 signing, ABI helpers."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import requests
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_utils import keccak, to_checksum_address

DEFAULT_RPC = "https://rpc-test.qday.info"
CHAIN_ID = 44005
TUSD8 = "0x456569838f1d43009A91ebA4263147Afd7233483"


def selector(signature: str) -> bytes:
    return keccak(text=signature)[:4]


def to_bytes32(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        return value
    text = value
    if text.startswith("0x") and len(text) == 66:
        return bytes.fromhex(text[2:])
    return keccak(text=text)


def u(value: int, decimals: int = 6) -> int:
    """'1.20' -> 1200000"""
    from decimal import Decimal

    return int(Decimal(str(value)) * (10**decimals))


def fmt(value: int, decimals: int = 6) -> str:
    from decimal import Decimal

    return f"{Decimal(value) / (10**decimals):.2f}"


class RpcError(RuntimeError):
    pass


class Rpc:
    def __init__(self, url: str = DEFAULT_RPC, timeout: int = 30):
        self.url = url
        self.timeout = timeout
        self.session = requests.Session()
        self._id = 0
        self.chain_id = self.call("eth_chainId")
        if int(self.chain_id, 16) != CHAIN_ID:
            raise RpcError(f"unexpected chain id {self.chain_id} at {url}, expected {CHAIN_ID}")

    def call(self, method: str, params: Sequence[Any] | None = None) -> Any:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": list(params or [])}
        for attempt in range(4):
            try:
                r = self.session.post(self.url, json=payload, timeout=self.timeout)
                data = r.json()
                break
            except (requests.RequestException, ValueError) as exc:  # transient RPC hiccups
                if attempt == 3:
                    raise RpcError(f"{method} failed: {exc}") from exc
                time.sleep(1.5 * (attempt + 1))
        if "error" in data:
            raise RpcError(f"{method}: {data['error']}")
        return data.get("result")

    # ------------------------------------------------------------------ reads
    def eth_call(self, to: str, data: bytes) -> str:
        return self.call("eth_call", [{"to": to, "data": "0x" + data.hex()}, "latest"])

    def balance(self, address: str) -> int:
        return int(self.call("eth_getBalance", [address, "latest"]), 16)

    def token_balance(self, token: str, address: str) -> int:
        raw = self.eth_call(token, selector("balanceOf(address)") + abi_encode(["address"], [address]))
        return int(raw, 16) if raw and raw != "0x" else 0

    def nonce(self, address: str) -> int:
        return int(self.call("eth_getTransactionCount", [address, "pending"]), 16)

    def block(self, number: str = "latest") -> dict:
        return self.call("eth_getBlockByNumber", [number, False])

    # ----------------------------------------------------------------- writes
    def _fees(self) -> dict:
        base = int(self.block()["baseFeePerGas"], 16)
        tip = max(1_000_000_000, base // 10)
        return {"maxPriorityFeePerGas": tip, "maxFeePerGas": base * 3 + tip}

    def send(
        self,
        key: str,
        to: str | None,
        data: bytes,
        value: int = 0,
        gas: int | None = None,
        label: str = "",
    ) -> str:
        acct = Account.from_key(key)
        tx: dict[str, Any] = {
            "data": data,
            "value": value,
            "nonce": self.nonce(acct.address),
            "chainId": CHAIN_ID,
            "type": 2,
            **self._fees(),
        }
        if to is not None:
            tx["to"] = to_checksum_address(to)
        try:
            probe = {k: tx[k] for k in ("to", "value") if k in tx}
            probe["data"] = "0x" + data.hex()
            probe["from"] = acct.address
            estimate = int(self.call("eth_estimateGas", [probe]), 16)
        except RpcError:
            estimate = 400_000
        tx["gas"] = gas or int(estimate * 1.35) + 30_000
        signed = acct.sign_transaction(tx)
        raw = signed.raw_transaction.hex()
        if not raw.startswith("0x"):
            raw = "0x" + raw
        try:
            tx_hash = self.call("eth_sendRawTransaction", [raw])
        except RpcError as exc:
            # Some Aevum builds price gas differently; retry once as a legacy tx.
            if "maxFeePerGas" not in str(exc) and "type" not in str(exc):
                raise
            base = int(self.block()["baseFeePerGas"], 16)
            legacy = {
                "data": data, "value": value, "nonce": tx["nonce"],
                "chainId": CHAIN_ID, "gas": tx["gas"], "gasPrice": base * 2 + 1_000_000_000,
            }
            if to is not None:
                legacy["to"] = tx["to"]
            signed = acct.sign_transaction(legacy)
            raw = signed.raw_transaction.hex()
            tx_hash = self.call("eth_sendRawTransaction", [raw if raw.startswith("0x") else "0x" + raw])
        if label:
            print(f"  sent {label}: {tx_hash}")
        return tx_hash

    def wait(self, tx_hash: str, timeout: int = 180) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            receipt = self.call("eth_getTransactionReceipt", [tx_hash])
            if receipt:
                if int(receipt["status"], 16) != 1:
                    raise RpcError(f"transaction reverted: {tx_hash}")
                return receipt
            time.sleep(2)
        raise RpcError(f"timeout waiting for {tx_hash}")

    def logs(self, address: str, topics: Sequence[str], from_block: int = 0) -> list[dict]:
        return self.call(
            "eth_getLogs",
            [{"address": address, "topics": list(topics), "fromBlock": hex(from_block), "toBlock": "latest"}],
        ) or []


# --------------------------------------------------------------------- ABI bits
def encode_call(signature: str, types: list[str], values: list[Any]) -> bytes:
    return selector(signature) + abi_encode(types, values)


def decode_words(raw: str, types: list[str]) -> tuple:
    if not raw or raw == "0x":
        return tuple(None for _ in types)
    return abi_decode(types, bytes.fromhex(raw[2:]))


def event_topic(signature: str) -> str:
    return "0x" + keccak(text=signature).hex()


def topic_address(address: str) -> str:
    return "0x" + "0" * 24 + address.lower().replace("0x", "")


def topic_uint(value: int) -> str:
    return "0x" + value.to_bytes(32, "big").hex()
