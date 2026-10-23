# Implementing ÐMP 1.0

This is a short guide for indexer, wallet and venue developers. [compact-orders.md](compact-orders.md)
(formerly `spec-v2.md`) is normative, and nothing here overrides it. If you already ship draft (pre-1.0)
lists, start with [MIGRATION-from-draft.md](MIGRATION-from-draft.md).

ÐMP 1.0 compact orders carry the wire marker `"v":"2"`. That is a marker, not a protocol version: there
is no ÐMP 2.

## What you build

| You are | You must implement | Spec |
|---|---|---|
| **Indexer** | Parse compact `list`/`cancel` (`"v":"2"`) with duplicate-key rejection. Rebuild the canonical PSDT from your own node and verify `sig`. Authorize with reveal authorship or `asig`. Apply newer-`ts`-wins ordering. Track the dog with ord FIFO. Classify spends with the layout-agnostic fill rule, and handle expiry, settlement depth and reorgs. | §4–§10 |
| **Seller wallet** | Sign `0x83` on `in[1]`/`out[1]` of the canonical template and emit the JSON order. `psdt` is optional. Inscribe with the seller key, or add `asig`. | §4, §5, §7 |
| **Buyer wallet / venue** | Build a fill: `in[1]` = `utxo` with the seller's scriptSig, `out[1]` = the signed output, any layout that puts the dog on the buyer's output. Pay declared fees. | §8.2, §8.4 |

Fees are declared only in the order's `fees` object (§4, §4.1). The flat draft fields (`royalty_address`,
`market_fee_bps`, …) are not 1.0; see the mapping in [collaborative-fees.md §9](collaborative-fees.md#9-draft-pre-10-fee-fields).
Only the seller's net payout is enforced by the signature. Royalties and venue fees are verified and
flagged, never enforced: [what is guaranteed vs verified](security.md#21-what-is-guaranteed-vs-verified).

## The five rules people get wrong

1. **The location rule is ord FIFO** (§8.1). Each sat's absolute position is the sum of the
   earlier input values plus its offset. Walk the outputs in order, skipping zero-value
   outputs. A position at or past the total output value is lost to fee. A UTXO can hold several
   inscriptions at different offsets. For a multi-part reveal, the ID is the first part's
   `txid i0` and the location is the completing reveal's `:0:0`. This matches what wonky-ord and
   dogesoft do for Doginals.
2. **Fill validation is layout-agnostic** (§8.2). Only the seller's `SINGLE|ACP` binding is fixed:
   `in[1]` spends `utxo` and `out[1]` equals the signed output. Where the dog lands decides the
   outcome. On an output owned by anyone other than the order key, it is a sale. Back to the order
   key, or lost to fee, it is cancel-by-move. The canonical layout puts the dog on `out[2]`. The
   diggydoge layout puts it on `out[0]` at offset 1,000,000. Both are sales.
3. **Validity never depends on an outside service.** Every validity decision uses chain data from
   your own node. External owner lookups (another indexer's API) are advisory and are for display
   only. Your answer MUST be identical after a reindex or a reorg.
4. **One OP_RETURN.** Standard relay allows one. The `dmp2` venue tag is optional. When a
   dogesoft-style `{"ds":…}` OP_RETURN is present, it wins and `settlement_fee_ok` is `null`
   (§8.3). Only the first OP_RETURN is read.
5. **Cover era 1.** Many dogs were inscribed before the Doginals era-2 floor. An index that starts
   later cannot place them, and will mark live orders `invalid`. Index from the era-1 floor, or
   report the dog as unknown instead of guessing.

## Reference and vectors

| File | Use |
|---|---|
| `reference/dmp_v2_reconstruct.py` | Independent reconstructor, written from the spec. Needs Python 3.10+ and `ecdsa`. |
| `vectors/dmp_v2_vectors.json` | Orders, PSDT bytes, sighash, invalid cases, cancel `asig`, ordering. `… vectors <file>` |
| `vectors/dmp_v2_state_vectors.json` | Location, multi-part genesis, fill layouts, reveal authorship, state, `ts`, reorgs. `… state <file>` |
| `vectors/dmp_v1_psdt_vectors.json` | Draft-list (pre-1.0) embedded-PSDT hardening, using the real mainnet lists. `… v1 <file>` |
| `schemas/list-v2.schema.json`, `schemas/cancel-v2.schema.json` | JSON shape only. Signatures and state are not checked. |
| `EXAMPLES/v2/` | Valid orders and cancels taken from the vectors. |

```bash
python3 -m pip install ecdsa
python3 reference/dmp_v2_reconstruct.py vectors vectors/dmp_v2_vectors.json
python3 reference/dmp_v2_reconstruct.py state   vectors/dmp_v2_state_vectors.json
python3 reference/dmp_v2_reconstruct.py v1      vectors/dmp_v1_psdt_vectors.json
```

Each command prints `ALL MATCH` and exits 0. The checklist for claiming conformance is in
[CONFORMANCE.md](CONFORMANCE.md).

## Draft lists on mainnet

These are all the `p:"dmp"` list ops on Dogecoin mainnet before ÐMP 1.0 compact orders. They are test
listings in the draft (pre-1.0) format. ÐMP 1.0 indexers SHOULD ignore them; an indexer that still
indexes draft lists MUST classify them as below. Classification is by shape, never by ID
(compact-orders §15). (This section was formerly headed "v1 mainnet lists".)

| list inscription | dog | classification |
|---|---|---|
| `bd75ee392df8240102e13fe4b89b23f38ec9d8700a8ff1508e0079de490cc2d4i0` | `315fdeb6f85f3a26b970181683596a425633d2282bd61bccbbfebb8c50c580edi0` | INVALID `postage_unsafe`: a valid `0x83` sig on the dog at input 0. A fill can never deliver the dog. |
| `54f111c33c3d380698055ec2528310a0f294e940015d3fdb0da7f8a411e66236i0` | `169ff29701a18a21cec4895704d20a38635efc05ea9ac2c1a88914251cbfc3a2i0` | INVALID `postage_unsafe`, for the same reason |
| `ee6fb2d882f42278843d58329a680728f62ce358f3ffc2d72cd53e2b69dc0a42i0` | `12547783533403bc81065897dfd143b75b255e2181da1e30a994ca44492e92f4i0` | valid draft hash-only list (venue-dependent). The outcome follows the dog's location. |
| `65992ab53114f0c5843561ce62d7158428f161734652beb0864ba3cb934bcd6ci0` | `d7a4727452e748fa3b874cea2f6853b6aa5b1676313225bd02b4f93f00429ffdi0` | valid draft hash-only list (venue-dependent). The outcome follows the dog's location. |

A buyer who signs a "fill" of a `postage_unsafe` list pays the seller and receives nothing. Venues
MUST NOT serve these lists. A seller retires one by moving the dog.
