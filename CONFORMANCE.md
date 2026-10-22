# ÐMP v2 conformance

An implementation is **ÐMP v2 conformant** for a role when it meets every item for that role below.
Item numbers refer to [spec-v2.md](spec-v2.md). The vectors are the tie-breaker. If your output
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
- [ ] All of `vectors/dmp_v1_psdt_vectors.json` matches if you index v1 lists with an embedded
      `psdt` (§2 v1 hardening, §15).
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
- [ ] It never signs a v1 PSDT with the dog at input 0.

## Buyer wallet / venue

- [ ] The fill spends `utxo` at `in[1]` with the seller's scriptSig and reproduces `out[1]` exactly.
- [ ] The dog lands, by §8.1, on an output the buyer controls. Check this before signing.
- [ ] Declared fees are paid. Outputs are at or above dust and the fee rate is at or above the §8.4
      guidance.
- [ ] At most one OP_RETURN.
- [ ] It does not serve `cancelled`, `expired` or `postage_unsafe` orders.

## Reporting

State the spec commit, the vector files and their `ALL MATCH` output, and the roles you claim.
A regtest run showing a canonical fill and an `out[0]` fill indexed identically by two independent
indexers is strong evidence, but it is not required.
