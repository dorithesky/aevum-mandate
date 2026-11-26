# Third-party components

Mandate is MIT licensed. It uses the following third-party work; each keeps
its own license and copyright.

| Component | Version | License | Use |
| --- | --- | --- | --- |
| [forge-std](https://github.com/foundry-rs/foundry/tree/master/crates/forge-std) | v1.9.4 | MIT OR Apache-2.0 | Solidity test helpers (`contracts/lib/forge-std`) |
| [eth-account](https://github.com/ethereum/eth-account) | 0.14 | MIT | signing transactions and EIP-712 invoices |
| [eth-abi](https://github.com/ethereum/eth-abi) | 6.0 | MIT | ABI encoding for the contract calls |
| [eth-utils](https://github.com/ethereum/eth-utils) | 6.0 | MIT | keccak, address checksums |
| [requests](https://github.com/psf/requests) | 2.34 | Apache-2.0 | JSON-RPC transport |

No source code was copied from the QDay Aevum starter kit. Its published
network constants (chain id 44005, RPC URL, tUSD8 address and token behaviour)
were used as documented by QDay and are cited in the README.
