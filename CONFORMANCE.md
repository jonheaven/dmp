# ÐMP 1.0 conformance (compact orders)

An implementation is **ÐMP 1.0 conformant** for a role when it meets every item for that role below.
Item numbers refer to [compact-orders.md](compact-orders.md) (formerly `spec-v2.md`; same numbering). The vectors are the tie-breaker. If your output
differs from a vector, you are wrong or the vector is, and either way please open an issue.

## Indexer

- [ ] All of `vectors/dmp_v2_vectors.json` matches: canonical PSDT bytes, sighash, net and every
      `invalid` reason class (§4–§6, §5.4).
- [ ] All of `vectors/dmp_v2_state_vectors.json` matches (§6.1, §7.1, §8.1, §8.2, §9, §10):
  - location: offsets (including a non-zero offset such as 1,000,000), several inscriptions in one
    UTXO, zero-value outputs skipped, sats lost to fee, last sat
  - genesis: single-part and multi-part reveals
  - fill layouts: canonical `out[2]`, diggydoge `out[0]`, dog back to the seller, dog lost to fee,
    altered `out[1]`, dog not on `in[1]`
  - reveal authorship, newer-`ts`-wins, ts window, cancel, expiry, settlement depth, reorgs
- [ ] All of `vectors/dmp_v1_psdt_vectors.json` matches if you still index draft (pre-1.0) lists
      with an embedded `psdt` (§2 draft-list hardening, §15).
- [ ] Duplicate keys at any depth are rejected (§4.2).
- [ ] Validity uses only your own node's chain data. External owner lookups never change a state.
      The same chain gives the same state after a reindex from scratch and after any reorg (§10).
- [ ] The index covers inscriptions from the era-1 floor, or reports dogs it cannot place as unknown.
- [ ] A fill is accepted in any output layout, and the sale is decided by where the dog lands (§8.2).
- [ ] The first OP_RETURN is classified as `dmp2`, `json:<key>`, `other` or none, and a
      non-`dmp2` OP_RETURN never invalidates a fill (§8.3).

## Seller wallet

- [ ] It signs only `in[1]` with `0x83`, low-S, strict DER over the §5.1 template. An emitted
      `psdt` matches the §5.3 rebuild byte for byte.
- [ ] The order JSON validates against `schemas/list-v2.schema.json`, with no duplicate keys,
      `ts` within ±7200 s of the inscribing block's time, and net ≥ 100000 koinu (≥ 1 DOGE recommended, §8.4).
- [ ] It inscribes with the order key, or includes a valid `asig` (§7).
- [ ] It never creates a draft (pre-1.0) list, and never signs a PSDT with the dog at input 0.

## Buyer wallet / venue

- [ ] The fill spends `utxo` at `in[1]` with the seller's scriptSig and reproduces `out[1]` exactly.
- [ ] The dog lands, by §8.1, on an output the buyer controls. Check this before signing.
- [ ] Declared fees are paid. Outputs are at or above dust and the fee rate is at or above the §8.4
      guidance.
- [ ] At most one OP_RETURN.
- [ ] It does not serve `cancelled`, `expired` or `postage_unsafe` orders.

## Conformance levels

A claim names a level and the **exact dmp-spec commit** (full 40-hex SHA) it was tested against, for
example `ÐMP 1.0 indexer-conformant @ dmp-spec 0123abc…` (full SHA). "ÐMP compatible" with no level and no
commit is not a conformance claim. A claim stays tied to that commit; re-test when you move to a newer one.

| Level | Requires |
|---|---|
| **Indexer** | every Indexer item above |
| **Wallet** | every Seller wallet item; plus every Buyer wallet item if the wallet builds fills |
| **Marketplace** | every Buyer wallet / venue item, and fee compliance reported as it is: shows `fee_split_ok` and the per-fee flags from an indexer (never from a `settle` claim), and never presents royalties or venue fees as enforced ([security.md §2.1](security.md#21-what-is-guaranteed-vs-verified)) |
| **Interop-tested** | Indexer level, plus a passing agreement test (below) against an independently written indexer |

## Interop agreement test

Two indexers written independently (different codebases), each with its own Dogecoin node on the same
regtest network. At each checkpoint, both dump every order's `{status, cancel_kind, buyer,
settlement_txid, compliance flags, dog location}` as canonical JSON (sorted keys). The two dumps MUST be
identical.

1. **List.** Inscribe three or more compact orders, at least one with `fees` and one with an `asig`.
   Both report `listed` and the same canonical PSDT SHA-256.
2. **Fill.** Fill one order in the canonical layout with every fee paid, and one in the `out[0]` layout
   with a fee omitted. Compare below 6 confirmations (`settle_pending`) and at 6 (`settled`), including
   `fee_split_ok: true` on the first and `false` on the second.
3. **Cancel.** Cancel one order by inscription and one by moving the dog. Expect `cancelled` with
   `cancel_kind` `inscription` and `moved`.
4. **Reorg.** Before a fill reaches 6 confirmations, `invalidateblock` its block. Compare once both
   indexers reach the new tip: the order is back to `listed`, with buyer and flags cleared. Then mine a
   longer branch in which the seller moves the dog instead (a conflicting spend of `utxo`) and compare
   again: `cancelled`, `cancel_kind` `moved`.

Report both implementations' commits, the spec commit, the block hash at each checkpoint and the
(empty) diff of the dumps.

## Reporting

State the level, the spec commit, the vector files and their `ALL MATCH` output, and the roles you
claim. For **Interop-tested**, attach the agreement-test report.
