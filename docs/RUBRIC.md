# How Mandate answers the judging criteria

The challenge scores 100 points across seven areas. This is where each one is
answered, so a judge can check rather than hunt.

## 1. User experience and presentation — 15

* One screen: balance, today's spend against the cap, invoices, the agent's
  reasoning and the on-chain trail. No wallet needed to read it.
* Plain-language pass/fail for every rule (`web/app.js` → `renderPanel`), with
  the exact amount, the cap and the wallet involved.
* Status feedback is a state, not a toast: `Paid`, `Refused`, `Awaiting owner`,
  each with its transaction link.
* Responsive layout (single column under 900px) so a judge can open it on a
  phone.
* The narrative: *"Your assistant pays invoices. Inside limits it cannot
  rewrite."* — the product is the limit, not the chatbot.

## 2. A clear, well-structured demo — 10

* `docs/DEMO.md` is the shot-by-shot script: four invoices, one per case —
  a clean payment, a lookalike invoice, an above-threshold payment that needs
  the owner, and a replay.
* Every claim in the video is a transaction with a hash and an explorer link
  (`docs/EVIDENCE.md`, generated from the chain).
* `scripts/local_e2e.py` reproduces the whole flow on anvil with the same code
  path, so the demo is not a one-off session. The script also replays each
  invoice's decision in the UI (`Replay decision`).

## 3. Documentation — 10

* `README.md`: problem, architecture diagram, addresses, environment variables,
  step-by-step reproduction, API examples, constraints, roadmap.
* `docs/ARCHITECTURE.md`: components, reason-code table, one payment end to end.
* `docs/SECURITY.md`: trust boundaries and an explicit "what this does not
  solve".
* `docs/EVIDENCE.md`: generated transaction table.

## 4. Innovation and originality — 20

* Prompt injection is answered structurally: invoice text is data, and the only
  thing that can move money is `pay()` against a verified wallet inside the caps.
  The demo includes an invoice whose memo literally says "ignore previous
  instructions"; it is refused like any other unverified wallet.
* The usual "AI agent with a wallet" gives the agent a key and trusts it. Here
  the agent key can call exactly two functions, and **refusals are written on
  chain** with the same reason codes as settlements — an audit trail of what
  the agent declined, which is what an accountant actually needs.
* Confirmation of Payee is enforced *on chain* against a name hash and a payout
  wallet, then re-checked with the merchant's EIP-712 invoice signature — two
  independent bindings between a name, an address and an issuer.
* The owner's approval is a signature over the payment fields, not an off-chain
  "approve" flag, so an agent cannot inflate the amount after approval.
* The mandate doubles as a scoped session: per-payment cap, daily cap, expiry
  and instant revocation (`setAgent`), i.e. session-key semantics without
  asking the agent to run a smart account SDK.

## 5. Technical quality and platform integration — 15

* Solidity 0.8.24 targeted at Shanghai (Aevum's EVM version), no proxies, no
  external imports in the contract.
* 26 Foundry tests, 13 pytest tests, 1 local end-to-end script; all green.
* EIP-1559 transactions with gas estimation, retries on transient RPC errors,
  receipt waiting with a timeout (`agent/mandate/chain.py`).
* Real tUSD8 on Aevum Testnet: deploys, payments, refusals and approvals are
  transactions, not a fork.
* Read-only browser integration via ethers v6 against `rpc-test.qday.info`, so
  the published page shows live state without a backend.

## 6. Real-world utility and market potential — 15

* The buyer is a small business that already receives invoices by email and
  pays vendors in stablecoins; the pain is real and the workflow is unchanged
  except for the approval line.
* Vendor onboarding is one transaction per payee; the daily cap maps to a
  treasury policy a finance lead would recognise.
* Path to scale: one account per business unit, a payee directory shared across
  accounts, and QDay's ERC-8004 agent identity to bind an agent key to a
  verifiable operator record (roadmap in the README).
* Business model: a per-settlement fee or a subscription per mandate account,
  paid in the same stablecoin; the buyer already holds the float.

## 7. Safety, trust and controls — 15

* Least privilege: the agent cannot withdraw, add payees, change caps, pause or
  transfer ownership. One transaction revokes it.
* Spend caps and session expiry are enforced by the contract, so a prompt
  injection in an invoice can at worst spend within today's cap.
* Approval is a typed signature over `(invoiceId, beneficiaryId, payee, amount,
  validUntil, nonce)`; changing the amount invalidates it, and the nonce cannot
  be replayed.
* Each invoice settles once; duplicates are refused on chain.
* Audit: `PaymentSettled`, `RefusalRecorded`, `PolicyChanged`, `AgentChanged`,
  `BeneficiaryAdded` — all public and indexed.
* Sovereignty: the owner can withdraw everything at any time, and there is no
  admin path that touches payee funds.
