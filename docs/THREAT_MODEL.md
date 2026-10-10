# Threat model and limitations

Version 2 adds `results/real_manifest.json` and a separate 60-record UCI prediction chain. The source is pinned to bytes observed from the official download. This supports reproducible integrity checks rather than independent authentication of utility measurements. Local EVM tests anchor both experiments with their respective manifests. The checkpoint, writer and privacy assumptions below apply to both.

| Asset or risk | Implemented control | Remaining boundary |
|---|---|---|
| Prediction edited after recording | SHA-256 payload digest | An attacker can recompute an unanchored history |
| Reordered or removed records | Index, previous hash and expected head checks | Checkpoint must be trusted outside the rewritten data |
| Unapproved contract writer | Owner-managed writer allowlist | Owner-key compromise defeats this policy |
| Existing anchor overwritten | Unique identifier enforced by contract | New identifiers may contain false assertions |
| Model/data substitution | Model, data and manifest digests | Digests prove correspondence, not dataset quality or ownership |
| Private telemetry exposure | Only digests stored by contract | Low-entropy unhashed disclosures and access-control governance need separate design |
| False sensor values | Residual alerts and synthetic tests | Detection is imperfect; neither ML nor a ledger makes inputs true |

The local hash chain is not itself a blockchain. Its checkpoint resides in the same delivered file and is therefore not an independent trust root. Browser session attestations update an in-memory checkpoint and are lost on reload unless exported. Restoring the original ledger restores the latest valid in-session snapshot, not a network consensus state.

The Solidity tests run on an ephemeral local EVM with owner-managed writer permissions. Extension to a shared network requires identity federation, key recovery, storage policies, independent review and monitoring. Deterministic Ganache accounts are disposable local test identities.

The supplied scripts use no production wallet private keys. Do not paste production keys into the demo. Production use requires an independently reviewed threat model and authorization/governance design.
