# ÐMP — Doginals Marketplace Protocol

**This repository is the canonical public specification for ÐMP (`p: "dmp"`).**

ÐMP records Doginal marketplace intent on-chain: listings, cancels, fills and more. Any indexer
with a full node can verify that intent against UTXO movement, so no venue's API is the source of
truth.

**ÐMP 1.0** has not launched yet. Its fixed-price format is the **compact signed order**. A compact `list` inscription carries
the seller's `SIGHASH_SINGLE|ANYONECANPAY` signature and the order terms. Every indexer rebuilds
the same seller PSDT byte for byte from its own node, and any wallet can fill the order.

| | |
| ---: | --- |
| **Version** | ÐMP 1.0 = compact signed orders ([compact-orders.md](compact-orders.md), wire `"v":"2"`) + the ops in [spec.md](spec.md) (wire `"v":"1.0"`). There is no ÐMP 2; `"2"` is only the compact-order wire marker |
| **Status** | Pre-launch draft, tested on regtest. The earlier `list` format with an embedded `psdt`/`psdt_hash` is a **draft (pre-1.0)** format: do not create it; indexers should ignore it |
| **Durable payload** | JSON in a Dogecoin inscription with `"p": "dmp"` |
| **Fill** | One transaction, with the seller's signature on `in[1]`/`out[1]` and the dog on any buyer output. The fill is the settlement |
| **Chain** | Dogecoin |
| **License** | [MIT](LICENSE) |

ÐMP is **not** a token standard. It governs how unique Doginals are listed and traded. Fungibles
stay on Ðunes and Treats.

## Authors

Jon Heaven — GitHub [@jonheaven](https://github.com/jonheaven) · X [@jontype](https://x.com/jontype)

If you ship this in a wallet, marketplace or indexer, emit `"p": "dmp"` only and keep the op
shapes identical, so every indexer sees one order book.

## Start here

| You are… | Read |
| --- | --- |
| **Building an indexer, wallet or venue** | **[IMPLEMENTERS.md](IMPLEMENTERS.md)**, then [compact-orders.md](compact-orders.md) |
| **Already shipped draft (pre-1.0) lists** | **[MIGRATION-from-draft.md](MIGRATION-from-draft.md)** |
| **Claiming conformance** | [CONFORMANCE.md](CONFORMANCE.md) and [vectors/](vectors/) |
| **Need JSON today** | [EXAMPLES/v2/](EXAMPLES/v2/) and [schemas/](schemas/) |
| **Other ops (auctions, offers, collections, …)** | [spec.md](spec.md) and [implementation-guide.md](implementation-guide.md) |

## Compact orders in one screen

```json
{"p":"dmp","v":"2","op":"list","chain":"dogecoin",
 "inscription_id":"<txid>i0","utxo":"<txid>:<vout>","price":"1000000000",
 "pay_to":"<seller address>","pubkey":"<66 hex>","sig":"<DER hex>83",
 "fees":{"royalty_bps":"500","royalty_to":"<address>","market_bps":"200","listing_to":"<address>"},
 "ts":1792632460,"expiry":1792718860}
```

- **Template.** `in[0]` is the buyer's placeholder, `in[1]` is the dog (`utxo`), `out[0]` is 100000
  koinu to `pay_to`, and `out[1]` is the seller's net. The seller signs `in[1]` with `0x83`.
- **Validity.** The order is valid only if the signature verifies against the rebuilt template and
  the order key authorized the inscription (reveal signed by it, or an `asig`). Duplicate keys are
  rejected. A newer `ts` wins.
- **Fill.** The fill spends `in[1]` and keeps `out[1]`, with any layout for the rest. It is a sale
  when the dog lands, by ord FIFO sat flow, with someone other than the seller. Any other spend of
  the dog is cancel-by-move.
- **Cancel.** `{"p":"dmp","v":"2","op":"cancel","list_id":"<list id>"}` is advisory. Moving the dog
  is authoritative.
- **Settled** at 6 confirmations. Reorgs roll the state back.

```bash
python3 -m pip install ecdsa
python3 reference/dmp_v2_reconstruct.py vectors vectors/dmp_v2_vectors.json
python3 reference/dmp_v2_reconstruct.py state   vectors/dmp_v2_state_vectors.json
python3 reference/dmp_v2_reconstruct.py v1      vectors/dmp_v1_psdt_vectors.json   # draft-list hardening
```

---

## Other ÐMP 1.0 operations (spec.md)

| Operation | Purpose |
| --- | --- |
| `list` | Fixed-price listing. Use the compact order ([compact-orders.md](compact-orders.md)); the spec.md form with `psdt`/`psdt_hash` is the draft (pre-1.0) format |
| `bid` | Buyer declares intent to purchase |
| `settle` | Records completed transfer + payment verification |
| `cancel` | Revokes any active intent (list, bid, offer, counteroffer) |
| `auction` | Creates an auction with configurable modes |
| `offer` | Private push-style offer from buyer to seller |
| `counteroffer` | Seller responds with alternate terms |
| `accept` | Accepts an offer or counteroffer |
| `decline` | Declines an offer or counteroffer |
| `transfer` | Explicit non-sale ownership transfer (gifts, airdrops) |
| `collection` | Creator-signed collection manifest |
| `collection-update` | Append-only metadata update for a collection |
| `vote` | DAO governance signal |

---

## Documentation

| Document | Description |
| --- | --- |
| [compact-orders.md](compact-orders.md) | ÐMP 1.0 compact signed orders (normative; formerly `spec-v2.md`, which now redirects) |
| [IMPLEMENTERS.md](IMPLEMENTERS.md) | Implementer guide, reference, vectors, draft lists on mainnet |
| [MIGRATION-from-draft.md](MIGRATION-from-draft.md) | What a draft (pre-1.0) implementation must change (formerly `MIGRATION-v1-to-v2.md`) |
| [CONFORMANCE.md](CONFORMANCE.md) | Conformance checklist |
| [spec.md](spec.md) | ÐMP 1.0 protocol specification (all other ops) |
| [dogetag-offers.md](dogetag-offers.md) | Lightweight OP_RETURN offer signaling extension |
| [implementation-guide.md](implementation-guide.md) | How to build a compliant indexer |
| [security.md](security.md) | Threat model and mitigations |
| [adoption-roadmap.md](adoption-roadmap.md) | Phased adoption strategy |
| [philosophy-and-design.md](philosophy-and-design.md) | Design principles and philosophy |
| [collaborative-fees.md](collaborative-fees.md) | Multi-venue rake + royalty settlement physics |
| [changelog.md](changelog.md) | Version history |
| [contributing.md](contributing.md) | How to contribute |
| [testing.md](testing.md) | Testing approach and scenarios |
| [EXAMPLES/](EXAMPLES/) | JSON operation examples (incl. `collection-with-parent-inscription.json` for ÐMP 1.0) |
| [schemas/](schemas/) | JSON Schema validation files |
| [vectors/](vectors/) | Conformance vectors |
| [reference/](reference/) | Python spec.md validator and compact-order reconstructor |

---

## spec.md reference validator

```bash
python reference/dmp_reference.py validate EXAMPLES/list-op.json
python reference/dmp_reference.py test-vectors
```

---

## Repo layout

```text
compact-orders.md       ÐMP 1.0 compact orders (normative)
spec.md                 ÐMP 1.0 other ops (normative)
IMPLEMENTERS.md         implementer guide
MIGRATION-from-draft.md draft (pre-1.0) → 1.0 changes
spec-v2.md, MIGRATION-v1-to-v2.md   redirects to the files above
CONFORMANCE.md          conformance checklist
implementation-guide.md indexer / marketplace behavior
security.md             threat model
EXAMPLES/               JSON operation examples
schemas/                JSON Schema files
vectors/                conformance vectors
reference/              spec.md validator, compact-order reconstructor
```
