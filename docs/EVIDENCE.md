# Evidence — Aevum Testnet

Generated 2026-11-26T23:03:15+00:00 from `https://rpc-test.qday.info` (chain 44005).
Every row is a transaction on QDay Aevum Testnet; open the hash on the explorer.

## Deployment

| Item | Value |
| --- | --- |
| MandateAccount | [`0xde333fC2330EadB1F2c51BD2CDFD0713D12E2b63`](https://explorer-test.qday.info/address/0xde333fC2330EadB1F2c51BD2CDFD0713D12E2b63) |
| Deploy transaction | [`0xb60375a678d2bab243d9b04f836f258dd14aab28b1f6dcdf9684cb4fc23406bf`](https://explorer-test.qday.info/tx/0xb60375a678d2bab243d9b04f836f258dd14aab28b1f6dcdf9684cb4fc23406bf) |
| Deploy block | 4210560 (gas 1421097) |
| Verified source | [`MandateAccount.sol` on the explorer](https://explorer-test.qday.info/address/0xde333fC2330EadB1F2c51BD2CDFD0713D12E2b63?tab=contract) (Blockscout, solc 0.8.24) |
| tUSD8 | [`0x456569838f1d43009a91eba4263147afd7233483`](https://explorer-test.qday.info/address/0x456569838f1d43009a91eba4263147afd7233483) |
| Owner (human) | `0xf462E0E9525AEAA4298344F55FB75D41a9d90189` |
| Agent (hot key) | `0xa28bfc39ac193ff33a201086B81Fb10da4B08c75` |

## Mandate at a glance

| | |
| --- | --- |
| Balance | 0.30 tUSD8 |
| Spent today | 4.70 of 5.00 tUSD8 |
| Per-payment cap | 4.00 tUSD8 |
| Owner approval above | 2.00 tUSD8 |
| Policy expiry | 1798325523 (unix) |
| Verified payees | 2 |

## Invoice decisions

| Invoice | Payee | Amount | Decision | Reason | Transaction |
| --- | --- | --- | --- | --- | --- |
| `INV-2026-0412` | Acme Studio LLC | 1.20 tUSD8 | auto_paid | OK | [`0xe2e1aa1ed4305e46…`](https://explorer-test.qday.info/tx/0xe2e1aa1ed4305e460aaa4b5544992e5c324e33cf03d7902c168e0027093cc531) |
| `INV-2026-0517` | Acme Studio LLC | 1.20 tUSD8 | refused | PAYEE_ADDRESS_MISMATCH | [`0xd28af7c2cf8ee0ce…`](https://explorer-test.qday.info/tx/0xd28af7c2cf8ee0ce43fb9e02762144245d044c0e4585a973c4a723d444c786af) |
| `INV-2026-0620` | Ledger & Co. Accounting | 3.50 tUSD8 | owner_approved | APPROVAL_REQUIRED | [`0x8f1a3fcb740ce2b8…`](https://explorer-test.qday.info/tx/0x8f1a3fcb740ce2b8c3830ba34a992f532fd990f5245234ef3ef8606a22460eb5) |
| `INV-2026-0701` | Acme Studio LLC | 4.00 tUSD8 | refused | PAYEE_ADDRESS_MISMATCH | [`0x2f97e67eed83dd11…`](https://explorer-test.qday.info/tx/0x2f97e67eed83dd11ea6a60e4187b733e4eef92d80d616b184605be8f51ced9da) |
| `INV-2026-0412` | Acme Studio LLC | 1.20 tUSD8 | refused | DUPLICATE_INVOICE | [`0x736d0aa241c50c99…`](https://explorer-test.qday.info/tx/0x736d0aa241c50c997c4b1694b51d1d22f589021c14eaaa54607688049136af27) |

## On-chain events

| Block | Event | Detail | Transaction |
| --- | --- | --- | --- |
| 4210612 | PaymentSettled | settled 1.20 tUSD8 to `0x2aC33b8fd64dd9710c985a0e3eF0eeC7A04F549E` | [`0xe2e1aa1ed4305e46…`](https://explorer-test.qday.info/tx/0xe2e1aa1ed4305e460aaa4b5544992e5c324e33cf03d7902c168e0027093cc531) |
| 4210632 | RefusalRecorded | refused: PAYEE_ADDRESS_MISMATCH (1.20 tUSD8) | [`0xd28af7c2cf8ee0ce…`](https://explorer-test.qday.info/tx/0xd28af7c2cf8ee0ce43fb9e02762144245d044c0e4585a973c4a723d444c786af) |
| 4210653 | PaymentSettled | settled 3.50 tUSD8 to `0x29B212e69E77Ae8f2e103b8d8f73485Bf06a1160` (owner co-signed) | [`0x8f1a3fcb740ce2b8…`](https://explorer-test.qday.info/tx/0x8f1a3fcb740ce2b8c3830ba34a992f532fd990f5245234ef3ef8606a22460eb5) |
| 4210675 | RefusalRecorded | refused: PAYEE_ADDRESS_MISMATCH (4.00 tUSD8) | [`0x2f97e67eed83dd11…`](https://explorer-test.qday.info/tx/0x2f97e67eed83dd11ea6a60e4187b733e4eef92d80d616b184605be8f51ced9da) |
| 4210695 | RefusalRecorded | refused: DUPLICATE_INVOICE (1.20 tUSD8) | [`0x736d0aa241c50c99…`](https://explorer-test.qday.info/tx/0x736d0aa241c50c997c4b1694b51d1d22f589021c14eaaa54607688049136af27) |

## Reproduce

```bash
git clone https://github.com/dorithesky/aevum-mandate && cd aevum-mandate
cd contracts && forge test && cd ..
python -m pytest agent/tests -q
python scripts/local_e2e.py     # anvil rehearsal, same code path
```

The public desk reads these same addresses: https://dorithesky.github.io/aevum-mandate/
