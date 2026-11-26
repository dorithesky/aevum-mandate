# Demo script (≈2 min 40 s)

Every scene is a real screen of the deployed desk or the Aevum explorer. The
recorded run is bundled in `web/data/run.json`; the transaction hashes are in
[`EVIDENCE.md`](EVIDENCE.md).

| # | Time | Screen | Caption |
| --- | --- | --- | --- |
| 1 | 0:00 | Title | **Mandate** — stablecoin payments your AI agent cannot abuse. Aevum Builder Challenge #1. |
| 2 | 0:04 | Desk hero + stats | Oakline Studio gives its assistant a payment account, not a wallet. 5.00 tUSD8 are held by the contract; the agent key can only call `pay()`. |
| 3 | 0:12 | Invoice inbox | Four invoices arrive. Each one is EIP-712 signed by the sender, so the agent can tell a real vendor from a lookalike. |
| 4 | 0:20 | Case 1 — Acme Studio, 1.20 | Confirmation of Payee: the name matches the verified record **and** the payout wallet is the registered one. Caps, deadline, duplicate, balance — all clear. |
| 5 | 0:32 | Case 1 checks + Paid | The agent settles it in tUSD8. One transaction, no approval needed: it is inside the mandate. |
| 6 | 0:40 | Case 2 — lookalike | Same vendor name, new wallet, lookalike sender domain. The name hash matches; the wallet does not. |
| 7 | 0:50 | Case 2 verdict Refused | Refused before any money moves — and the refusal is written on chain with reason code 6, so it is auditable, not a log line. |
| 8 | 1:02 | Case 3 — 3.50 to the accountant | Above the owner-approval line. The agent stops and asks for the owner's EIP-712 signature over invoice id, payee, amount, deadline and nonce. |
| 9 | 1:12 | Case 3 owner co-sign | The owner's key signs on their device; the agent never sees it. The contract verifies the signature and settles. |
| 10 | 1:22 | Case 4 — replay | The same invoice arrives twice. The id is already settled; the second attempt is refused on chain. |
| 11 | 1:32 | Balance + activity | 1.20 + 1.20 refused + 3.50 paid: 0.30 tUSD8 left in the mandate, 4.70 spent against a 5.00 daily cap. |
| 12 | 1:42 | Contract card / policy | The mandate is plain storage: per-payment 4.00, daily 5.00, approval above 2.00, policy expiry, one agent key, instantly revocable. |
| 13 | 1:52 | Stolen-key question | What if the agent key leaks? It can call two functions, only to verified payees, only inside the caps. It cannot withdraw, add a payee, or raise a limit. `setAgent` revokes it in one transaction. |
| 14 | 2:04 | Explorer — PaymentSettled | Every settlement emits `PaymentSettled` with the invoice id, payee and amount. |
| 15 | 2:14 | Explorer — RefusalRecorded | Refusals emit `RefusalRecorded`. An auditor sees what the agent declined. |
| 16 | 2:24 | Tests | 26 Foundry tests, 13 agent tests, and an anvil rehearsal that runs the same code path: 2 settled, 2 refused, balances reconciled. |
| 17 | 2:34 | End card | Repository, contract address, live desk link. Test tokens only. |

## Voices to avoid

* Do not call it a chatbot or a copilot. It is an account with a mandate.
* Do not claim KYC, bank-grade identity or "fraud detection AI". The security
  property is narrow and stated: the payout wallet cannot change without the
  owner, and the agent cannot exceed the caps.
* Do not show a mainnet address or a real balance. Everything is tUSD8 on
  Aevum Testnet.
