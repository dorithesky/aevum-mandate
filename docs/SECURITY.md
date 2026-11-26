# Security model

Mandate assumes the agent *will* eventually be compromised or wrong, and puts
the money behind rules the agent cannot change.

## Trust boundaries

| Actor | Can | Cannot |
| --- | --- | --- |
| Owner (EOA) | deposit, withdraw, register payees, change caps, pause, revoke the agent, co-sign above-threshold payments | — |
| Agent (hot key, on a server) | call `pay()` and `recordRefusal()` | withdraw, add or disable a payee, change caps, pause, move funds anywhere but a verified payee |
| Merchant | issue invoices signed with their registered key | change the payee wallet, reuse an invoice id |
| Anyone | read state, verify every payment and refusal on the explorer | write |

## Threats and what stops them

**Stolen agent key.** The key can only call `pay()` and `recordRefusal()`. The
payee wallet, amount caps and approval line are owner-set storage. The owner
revokes it with one `setAgent` call; the key then reverts with `NotAgent`.
There is no function that lets the agent send funds to an arbitrary address.

**Invoice fraud / business email compromise.** A lookalike invoice with a
verified vendor's name but a new payout wallet fails code 6 (address mismatch)
before any money moves. Even a perfectly signed invoice from an unverified
merchant fails code 3.

**Tampered amount after approval.** The owner's EIP-712 approval covers
invoice id, beneficiary id, payee, amount, deadline and nonce. Changing any
field invalidates the signature (`REFUSED_INVALID_APPROVAL`), and a used nonce
cannot be replayed.

**Double payment.** `invoiceUsed[invoiceId]` is set on settlement, so the same
invoice cannot be paid twice even if it is delivered again.

**Runaway spending.** Per-payment cap, daily cap (UTC day) and an optional
policy expiry. `remainingToday()` is a view the UI and the agent both use.

**Refusal cover-up.** A refused invoice is recorded on chain with the agent
address and reason code, so an auditor sees refusals alongside payments.

## What this does *not* solve

* **Owner key compromise.** The owner can always withdraw; that is deliberate,
  but it means the owner key is the real treasury key. Production deployments
  should use a multisig or a passkey wallet as `owner` and add a two-step
  ownership transfer with a time delay.
* **Merchant key compromise.** If a merchant's signing key leaks, an attacker
  can issue valid invoices up to the caps. Caps and the approval line bound the
  damage; per-merchant caps would bound it further.
* **Payee registration is manual.** The registry is only as good as the
  verification the owner did before adding a wallet. This demo does not do KYC
  or bank-account attestation; the security property is *"the payout address
  cannot change without the owner"*, not *"this company is who it claims"*.
* **Token-level risks.** tUSD8 is a test token. The contract assumes a standard
  ERC-20 without fee-on-transfer or rebasing behaviour.
* **Privacy.** Amounts, payees and memos hashes are public on chain. Names are
  stored as keccak hashes on chain, but invoice metadata (names, memos) is in
  the invoice JSON and in this repository's demo data.

## Operational notes

* The agent key, owner key and merchant keys in this repository's demo run are
  **testnet-only throwaway keys**. They are kept out of git (`.env`) and hold
  no value. Nothing in the code reads a key from the web layer.
* `setPolicy` rejects an approval threshold above the per-payment cap, so the
  human check can never be unreachable by configuration.
* Policy changes are announced with `PolicyChanged`, and the owner can pause
  the account in one transaction.
* Contract deployment is a single self-contained file; there is no proxy and
  no upgrade path, so the rules cannot be swapped under a payee's feet. A
  future version that needs upgrades should use a timelocked proxy and say so.
