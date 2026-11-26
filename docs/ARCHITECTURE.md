# Architecture

Mandate is three small pieces: a payment account contract, an agent that reads
invoices, and a web desk that shows both sides. No backend custody, no private
key in the browser, no off-chain database of truth.

```
                    ┌──────────────────────────────────────────────┐
  signed invoice    │  Agent (Python)                              │
  (EIP-712,         │  1. verify merchant signature                │
   tUSD8 amount) ──►│  2. Confirmation of Payee vs the registry     │
                    │  3. caps, deadline, duplicate, balance        │
                    │  4. decide: pay / ask owner / refuse          │
                    └───────────────┬──────────────────────────────┘
                                    │ pay(intent, ownerSig?)
                                    │ recordRefusal(invoiceId, reason)
                                    ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │ MandateAccount.sol  (chain 44005)                                  │
   │  · holds the owner's tUSD8 (ERC-20, the agent cannot withdraw)     │
   │  · verified-payee registry: nameHash + wallet + invoice signer     │
   │  · per-payment cap, daily cap, policy expiry, pause                │
   │  · one settlement per invoice id                                   │
   │  · above the approval line: owner's EIP-712 signature required     │
   │  · emits PaymentSettled / RefusalRecorded                          │
   └────────────────────────────────────────────────────────────────────┘
                                    │ tUSD8 transfer
                                    ▼
                              verified payee wallet
```

## Why the rules are on chain

The agent is the component most likely to be wrong: a prompt injection in an
invoice PDF, a hallucinated amount, a leaked key. Off-chain checks are still
needed for a good explanation, but they are advisory. `pay()` re-runs every
rule that protects money, so the worst a compromised agent can do is spend
inside the mandate it was given — and every refusal it claims is a transaction
anyone can audit.

## Decisions and their reasons

The contract and the agent share one reason code table so a refusal looks the
same in the UI, in the agent log and on chain.

| Code | Meaning | Checked by |
| --- | --- | --- |
| 1 | Mandate paused | contract |
| 2 | Policy or invoice expired | contract |
| 3 | Payee not in the registry | agent, contract |
| 4 | Payee disabled | agent, contract |
| 5 | Payee name hash mismatch | agent, contract |
| 6 | Payout wallet mismatch | agent, contract |
| 7 | Invoice id already settled | agent, contract |
| 8 | Zero amount | contract |
| 9 | Above per-payment cap | agent, contract |
| 10 | Above remaining daily cap | agent, contract |
| 11 | Owner approval required | agent, contract |
| 12 | Owner signature invalid or replayed | contract |
| 13 | Mandate underfunded | agent, contract |
| 15 | Invoice signature invalid | agent |
| 16 | Invoice settlement window closed | agent, contract |
| 17 | Malformed invoice | agent |

## One payment, end to end

1. The merchant signs an `Invoice` struct with EIP-712
   (`Aevum Mandate Invoice`, chain 44005): id, issuer name, payee wallet,
   amount, memo, issued/due/valid-until timestamps.
2. The agent loads the invoice and builds the *intent*:
   `invoiceHash = keccak(id | payee | mandate)`, `payeeNameHash`, amount in
   6-decimal units, memo hash, deadline, nonce.
3. `evaluate()` mirrors the contract checks and returns a decision plus the
   human-readable detail for every rule.
4. `pay(intent, approval)` is called by the agent key. If the amount is above
   `approvalThreshold`, `approval` carries the owner's EIP-712 signature over
   `(invoiceId, beneficiaryId, payee, amount, validUntil, nonce)`.
5. On success the contract transfers tUSD8 to the registered payout wallet and
   emits `PaymentSettled`. On refusal the agent calls `recordRefusal` with the
   same invoice id and reason code (a refusal is not a payment attempt, so it
   is not a revert — it is a permanent audit record).

## Components

| Path | Role |
| --- | --- |
| `contracts/src/MandateAccount.sol` | the account, registry, policy and settlement |
| `contracts/test/MandateAccount.t.sol` | 26 Foundry tests, one behaviour each |
| `agent/mandate/chain.py` | JSON-RPC, EIP-1559 signing, ABI helpers (no web3) |
| `agent/mandate/contract.py` | typed wrapper over the contract + events |
| `agent/mandate/invoices.py` | EIP-712 invoices and the preflight mirror |
| `agent/mandate/cli.py` | deploy, setup, issue invoices, run the agent |
| `server/app.py` | local demo API (`/api/state`, `/api/run/<case>`) |
| `web/` | static desk: recorded run by default, live chain reads over JSON-RPC |

## Test strategy

* `forge test` — contract behaviour, including signature replay over an edited
  amount, cap arithmetic, daily reset, owner-only functions.
* `pytest agent/tests` — invoice signature round-trip, tamper detection, and
  one test per refusal reason in the agent mirror.
* `scripts/local_e2e.py` — starts anvil with chain id 44005, deploys a mock
  tUSD8, then runs deploy → setup → issue → four invoice decisions and checks
  the resulting balances. This is the same code path used on the testnet, so a
  green run is a real rehearsal.
