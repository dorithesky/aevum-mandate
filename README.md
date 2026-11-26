# Mandate — stablecoin payments your AI agent cannot abuse

**Aevum Builder Challenge #1 · Native AI Assistants / business payments · QDay Aevum Testnet (chain 44005) · tUSD8**

An AI agent that pays vendor invoices is only useful if you can hand it a wallet.
Mandate hands it a *mandate* instead: a smart account that holds your tUSD8 and
lets the agent call exactly one money-moving function, only to payees you
verified, only inside per-payment and daily caps, and only after your own
signature above a threshold. Refusals are written on chain with the same reason
codes as payments, so the audit trail covers what the agent declined.

* **Desk (live, static + on-chain reads):** https://dorithesky.github.io/aevum-mandate/
* **Contract:** <!-- CONTRACT_LINK -->
* **Demo video:** <!-- VIDEO_LINK -->
* **Repository:** https://github.com/dorithesky/aevum-mandate

<!-- DEPLOY_TABLE -->

## The problem

Two things go wrong when an assistant pays bills.

1. **Invoice fraud.** A lookalike invoice arrives with a real vendor's name and a
   new payout wallet. Bank-detail-change fraud is the classic BEC playbook; on
   chain it is one address swap and the money is gone in a block.
2. **Agent risk.** An agent with a key can be prompt-injected by a document, or
   simply wrong. If the key can move funds, the blast radius is the balance.

Mandate answers both with the same object: a payment account whose rules are
public, enforced by the contract, and auditable after the fact.

## What it does

```
 signed invoice (EIP-712)            agent                     MandateAccount (tUSD8)
 ─────────────────────────►  verify signature                            │
                             Confirmation of Payee ◄──────────────────────┤ registry
                             caps · deadline · duplicate · balance        │ policy
                             decision → pay / ask owner / refuse          │
                                     │ pay(intent, ownerSig?) ──────────►│ contract re-runs
                                     │ recordRefusal(id, reason) ───────►│ the same rules
                                     ▼                                   ▼
                              tx hash + explorer link            tUSD8 to verified payee
```

Four demo invoices, one per behaviour:

| Invoice | What happens |
| --- | --- |
| `INV-2026-0412` · 1.20 tUSD8 to Acme Studio LLC | Inside the mandate → the agent pays automatically |
| `INV-2026-0517` · 1.20 tUSD8, same vendor name, **different wallet** | Confirmation of Payee fails → refused, refusal recorded on chain |
| `INV-2026-0620` · 3.50 tUSD8 to the accountant | Above the owner-approval line → the owner signs, then the agent pays |
| `INV-2026-0412` again | The invoice id is already settled → refused on chain |

## Rules the agent cannot change

| Rule | Enforced by | Reason code |
| --- | --- | --- |
| Only verified payees, by name **and** wallet | `MandateAccount.pay` | 3, 5, 6 |
| Per-payment cap | `MandateAccount.pay` | 9 |
| Daily cap (UTC day) | `MandateAccount.pay` | 10 |
| One settlement per invoice id | `MandateAccount.pay` | 7 |
| Owner co-signature above the line (EIP-712 over invoice id, payee, amount, deadline, nonce) | `MandateAccount.pay` | 11, 12 |
| Policy expiry, pause, instant agent revocation | `setPolicy`, `setPaused`, `setAgent` | 1, 2 |
| The agent can never withdraw or add a payee | no such role | — |
| Refusals are auditable | `recordRefusal` emits `RefusalRecorded` | 15, 16, … |

The full table, including the checks only the agent can do (invoice signature,
malformed invoice), is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quick start

```bash
git clone https://github.com/dorithesky/aevum-mandate.git
cd aevum-mandate

# 1. contracts: 26 tests, no network needed (forge-std is vendored)
cd contracts && forge test && cd ..

# 2. agent: 13 unit tests (invoice signatures + one per refusal reason)
pip install -r requirements.txt
python -m pytest agent/tests -q

# 3. full rehearsal on a local chain: deploy, register payees, four invoices
make test-e2e

# 4. the desk with the live agent (uses the deployment in state/deployment.json)
cp .env.example .env      # fill with throwaway testnet keys
make demo                 # http://127.0.0.1:8787
```

`scripts/local_e2e.py` starts anvil with chain id `44005`, deploys a mock
tUSD8, and runs the exact same code path as the testnet demo — so a green run
is a real rehearsal, not a mock.

## Deploy your own

```bash
cp .env.example .env         # owner / agent / merchant keys (testnet only)
make deploy                  # deploys MandateAccount against tUSD8
make setup                   # agent role, policy, verified payees, funding
make invoices                # four EIP-712 signed invoices
make scenario                # run all four through the agent, export web data
```

Environment variables (`.env`, never committed):

| Name | Meaning |
| --- | --- |
| `OWNER_KEY`, `OWNER_ADDRESS` | the human treasury key: policy, withdrawal, approvals |
| `AGENT_KEY`, `AGENT_ADDRESS` | the hot key the assistant runs with; only `pay` and `recordRefusal` |
| `MERCHANT_KEY`, `ACCOUNTING_KEY`, `ATTACKER_KEY` | demo payee / lookalike keys |
| `RPC_URL` | `https://rpc-test.qday.info` |
| `TUSD8` | `0x456569838f1d43009A91ebA4263147Afd7233483` (6 decimals) |

## Contracts and agent API

```solidity
// owner
setAgent(address) setPolicy(perTx, daily, approvalThreshold, expiry)
addBeneficiary(nameHash, wallet, invoiceSigner) setBeneficiaryActive(id, bool)
setPaused(bool) withdraw(to, amount) transferOwnership(address)

// agent
pay(Payment p, bytes approval) returns (uint8)
recordRefusal(bytes32 invoiceId, uint8 reason, uint256 amount, bytes32 payeeNameHash)

// anyone (views)
preview(Payment, bytes) getBeneficiary(id) remainingToday() approvalDigest(...)
```

An invoice is an EIP-712 `Invoice` struct (`Aevum Mandate Invoice`, chain 44005)
signed by the merchant's registered key: id, issuer name, payee, amount, memo,
issued/due/valid-until. The agent turns it into an intent with
`invoiceHash = keccak(id | payee | mandate)` and settles it once.

## Local demo API

The desk talks to two routes when you run `make demo`:

| Route | Purpose |
| --- | --- |
| `GET /api/state` | mandate state, invoices, decisions, on-chain events |
| `POST /api/run/<caseId>` `{"approve": true}` | run the agent; the owner co-signs only when asked |

On the public Pages build there is no backend: the page plays the recorded run
from `web/data/run.json` and reads the live mandate balance straight from Aevum
over RPC, so the numbers are real even without a server.

## Repository layout

```
contracts/            MandateAccount.sol + 26 Foundry tests (forge-std vendored)
agent/mandate/        JSON-RPC client, EIP-712 invoices, policy mirror, CLI
server/app.py         local demo API (stdlib http.server, no framework)
web/                  static desk: recorded run, live ethers reads, replay
invoices/             four signed demo invoices (public signatures only)
docs/                 ARCHITECTURE, SECURITY, EVIDENCE, RUBRIC, DEMO script
scripts/local_e2e.py  anvil rehearsal of the full flow
scripts/make_video.py screenshot → captioned demo video
```

## Design notes

* **No custody by the agent.** Funds live in the account contract. The agent's
  key can only call `pay()` to a registered wallet.
* **Two bindings for Confirmation of Payee.** The name hash must match the
  registry *and* the payout wallet must be the registered one; the merchant's
  EIP-712 signature binds the invoice body to the key you verified at onboarding.
* **Approval is a signature, not a button.** The owner signs the payment fields;
  an agent that inflates the amount invalidates its own approval.
* **Refusals are first-class.** `RefusalRecorded` carries the same reason codes
  as the agent's UI, so "we blocked this" is verifiable, not a log line.
* **Session-key semantics without an SDK.** Caps + expiry + one-call revocation
  give the agent a scoped, expiring capability. Natural next step: bind the
  agent key to an ERC-8004 identity record on Aevum so the operator is
  attestable, and move the owner to a passkey/multisig wallet.

Limitations are listed in [`docs/SECURITY.md`](docs/SECURITY.md): owner-key
compromise, merchant-key compromise, and the fact that payee verification is
only as good as the owner's onboarding check.

## Tests

```
forge test                       26 passed
pytest agent/tests               13 passed
python scripts/local_e2e.py      deploy → 2 settled, 2 refused, balances reconciled
```

## License

MIT. Third-party components and their licenses: [`NOTICE.md`](NOTICE.md).
Testnet only — no token is issued or promised, and the keys in this repository's
demo run hold no value.
