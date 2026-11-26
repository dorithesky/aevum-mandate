# DoraHacks submission text (copy-ready)

**Name:** Mandate
**Brief description (≤ 200 chars):** A stablecoin invoice desk on QDay Aevum: an AI agent settles vendor invoices only inside on-chain limits — verified payees, spend caps, owner co-signature, refusals recorded on chain.

**Track:** Native AI Assistants (business payments). Also fits Confirmation of Payee.
**GitHub:** https://github.com/dorithesky/aevum-mandate
**Demo video:** https://dorithesky.github.io/aevum-mandate/demo/out/mandate-demo.mp4
**Website:** https://dorithesky.github.io/aevum-mandate/
**Tags:** tUSD8, Aevum Testnet, AI agent, stablecoin payments, confirmation of payee, smart account, spending limits

## Long description

### The problem

Two failures cost small businesses money when an assistant pays invoices.

1. **Invoice fraud.** A lookalike invoice arrives with a real vendor's name and a
   new payout wallet. On chain the money leaves in one block and cannot be recalled.
2. **Agent risk.** An agent with a wallet key can be prompt-injected by a
   document, or simply wrong. If the key can move funds, the blast radius is the
   whole balance.

### How it works

Mandate gives the assistant a *mandate* instead of a wallet: a smart account
that holds the company's tUSD8 and enforces the payment policy on chain.

* The owner registers each payee with a **name hash**, the **payout wallet** and
  the **key that signs that merchant's invoices** (EIP-712).
* When an invoice arrives, the agent verifies the merchant's signature, runs
  **Confirmation of Payee** against the registry, checks the per-payment cap,
  today's remaining cap, the settlement window, duplicate invoice ids and the
  balance — and explains every check before spending anything.
* `pay()` re-runs the same rules on chain. Above the owner-approval line, the
  owner's EIP-712 signature over `(invoiceId, beneficiaryId, payee, amount,
  validUntil, nonce)` is required, so an agent cannot inflate an amount after
  approval.
* A refused invoice is recorded with `recordRefusal(id, reason)` — refusals are
  as auditable as payments, with the same reason codes the UI shows.

### Key features

* Verified-payee registry with dual binding: name hash **and** payout wallet,
  plus the merchant's invoice signing key.
* Per-payment cap, daily cap, policy expiry, pause, and instant agent revocation
  (`setAgent`) — the agent key can only ever call `pay()` and `recordRefusal()`.
* One settlement per invoice id; replaying an invoice is refused on chain.
* Owner co-signature above a threshold, verified by the contract, with nonce
  protection against replay on a changed amount.
* An audit trail of refusals (`RefusalRecorded`) alongside settlements
  (`PaymentSettled`).
* A desk UI that needs no wallet to read: live balance from Aevum RPC, the
  agent's reasoning per invoice, and every transaction linked.

### Tech stack

Solidity 0.8.24 (Shanghai) · Foundry (26 tests) · Python agent (JSON-RPC +
EIP-1559, eth-account, no web3) · stdlib HTTP demo API · static desk with
ethers v6 · GitHub Pages · tUSD8 on QDay Aevum Testnet (chain 44005).

### What is live on Aevum

<!-- Fill from docs/EVIDENCE.md after the testnet run: mandate address, deploy
tx, four invoice transactions (2 settled, 2 refused), balances. -->

### Known constraints and roadmap

* Payee verification is only as good as the owner's onboarding check; no KYC.
* Owner key is the treasury key — production should use a multisig/passkey owner
  and a timelocked ownership transfer.
* Next: bind the agent key to an **ERC-8004** identity record on Aevum so the
  operator is attestable, add per-payee caps, and turn the approve step into a
  push notification on the owner's phone.
* Business model: a per-settlement fee or a per-account subscription in the same
  stablecoin; the buyer already holds the float.
