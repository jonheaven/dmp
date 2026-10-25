# ÐMP Security Model

Version: ÐMP 1.0 (pre-launch draft)
Last Updated: 2026-10-23

---

## Overview

ÐMP is an **intent and proof layer**, not an atomic execution layer. This document defines the
threat model honestly, describes what ÐMP can and cannot protect against, and gives mitigation
strategies for each known attack vector.

**The most important thing to understand about ÐMP security**: Dogecoin has no native smart contract
escrow or covenant system. ÐMP records cannot force outcomes — they make violations legible and
auditable. Bad actors CAN circumvent individual protections; ÐMP ensures the community can DETECT
and JUDGE such behavior from chain data alone.

**Hardening note:** The full pre-launch hardening patch (MUST-099–MUST-108) is **integrated** in the v1.0 draft `spec.md` and reflected in examples, vectors, and the reference validator.

---

## 1. Threat Model

### 1.1 Actors

- **Honest seller**: Lists fairly, settles when agreed, pays royalties.
- **Honest buyer**: Bids/offers in good faith, pays when accepting terms.
- **Griefing seller**: Lists to fake demand, never intends to settle.
- **Griefing bidder**: Bids to inflate apparent demand, never intends to pay.
- **Royalty-evading marketplace**: Facilitates trades that skip royalty outputs.
- **Fake settle inscriber**: Inscribes a settle op with a false settlement_txid or wrong amounts.
- **Replay attacker**: Re-broadcasts old ÐMP intents after UTXO state has changed.
- **Spam attacker**: Floods the chain with low-value ÐMP ops to pollute indexer state.
- **Double-list attacker**: Lists the same inscription on multiple venues simultaneously.
- **Double-spend attacker**: Accepts an offer and then sells to a different buyer first.

### 1.2 Trust Assumptions

- Dogecoin L1 is canonical. Block data is authoritative.
- Indexers are assumed honest but may disagree on edge cases — ÐMP spec provides deterministic
  rules to resolve disagreements.
- ÐMP does NOT assume marketplace operators are honest.
- ÐMP does NOT require a trusted third party for any core operation.

---

## 2. What ÐMP Cannot Prevent

Be explicit about this. Anyone building on ÐMP must understand these limitations:

| Risk | Why ÐMP cannot prevent it | ÐMP mitigation |
|------|---------------------------|----------------|
| Seller lists and then sells off-protocol | No atomic lock on inscription UTXO | Auto-invalidate on UTXO spend (MUST-015); provenance_gap flag |
| Marketplace skips royalty or venue fees | The seller's `0x83` signature commits only to the dog input and the seller's net output; the buyer builds every other output | Indexers check fee outputs against the indexed order and set compliance flags (compact-orders.md §8.2); non-payment is visible, never prevented |
| Bidder never pays after accept | No payment lock or escrow | Negotiate PSDT/PSBT for pre-signed settlement; non-payment is auditable |
| Stale listing after off-protocol transfer | Intent is separate from UTXO | UTXO-spend auto-invalidation on indexer |
| Double-list across venues | Inscription UTXO not locked | Single-active-list rule (MUST-013); first settle wins (MUST-036) |
| Fake settle inscription | Anyone can inscribe anything | Indexers verify settlement_txid against confirmed chain data |
| Griefing / spam listings | No cost to inscribe intent | offer_fee anti-spam; 4 KB soft limit (v2 batch lists: 32768 B, compact-orders §16.11); indexer filtering |
| Reorg-based front-running | Chain reorganizations are real | 6-block confirmation depth requirement; provisional state handling |

### 2.1 What is guaranteed vs verified

ÐMP 1.0 compact orders (compact-orders.md) give three different levels of assurance. Keep them apart in
docs, UIs and marketing.

- **Enforced (consensus):** Dogecoin script validation makes it impossible to do otherwise.
- **Verified (indexer):** not enforced on chain, but every conforming indexer computes the same answer
  from chain data and its own node, and reports it.
- **Venue policy:** only as good as the venue or wallet that builds the transaction.

| Property | Level | How | What a conforming indexer records |
|---|---|---|---|
| Listing persistence | Enforced | The order is an inscription. Anyone with a node can rebuild it and its canonical PSDT (§5) | The order record. It stays fillable only while the dog sits at `utxo` |
| Seller payout (`net` → `pay_to`) | Enforced | The seller signs `in[1]` with `SIGHASH_SINGLE\|ANYONECANPAY` (`0x83`), which commits to `out[1]`. Any transaction that uses the signature must carry that exact `out[1]`, or it fails script validation | `seller_paid_ok` |
| Fee terms not swapped by a copier | Verified | `fees` and `pay_to` placement are not covered by the `0x83` signature. They are bound to the order key by reveal authorship or `asig` (§7) | A tampered order is INVALID |
| Dog delivered to the buyer | Verified | The signature does not say where the dog goes. The buyer's own transaction decides, and the buyer's wallet MUST check §8.1 before signing. The indexer applies the §8.1 location rule | Sale if the dog lands with someone other than the order owner. Otherwise cancel-by-move (`cancel_kind:"moved"`), even though the seller was paid |
| Creator royalty | Verified | Declared in `fees`. Paid only if the buyer's venue adds the output | `royalty_ok` (`null` if none owed) |
| Listing venue fee | Verified | Declared in `fees` (`listing_to`) | `listing_fee_ok` |
| Settlement venue fee | Verified, only when tagged | The settlement venue is named only by an optional `dmp2` OP_RETURN on the fill (§8.3) | `settlement_fee_ok`; `null` when the fill has no `dmp2` tag (untagged, or a venue's own OP_RETURN) |
| Fee-noncompliant sale | Verified | A fill that skips a declared fee is still a fill and still a sale | Valid sale: `settle_pending` → `settled` at 6 confirmations, with `fee_split_ok: false` and the failing flag `false`. The reference indexer (dogex) stores these in a `compliance` object on the fill. There is no separate "noncompliant" status |
| Cancel by moving the dog | Enforced | Spending `utxo` destroys the outpoint the signature commits to. The order can never be filled | `cancelled`, `cancel_kind:"moved"` |
| Cancel inscription | Venue policy / indexer | Advisory (§9). The signature stays valid until the dog moves | `cancelled`, `cancel_kind:"inscription"`. A later fill is still recorded, flagged `after_cancel` |
| Expiry | Venue policy / indexer | Advisory (§9) | `expired`. A later fill is still recorded, flagged `after_expiry` |
| Finality | Verified | 6 confirmations; reorgs roll back (§10) | `settled` only at depth 6 |

Indexers derive expected fee amounts from the **order they indexed** (compact-orders.md §4.1), never from
amounts claimed in a `settle` inscription or by a venue API. Section numbers in this table refer to
compact-orders.md.

The only way to make fees consensus-enforced is to have the seller sign every output, which turns a public
listing into an interactive order for one buyer. That variant is described in compact-orders.md §12. It is
informative and not implemented.

---

## 3. Attack Vectors and Mitigations

### 3.1 Fake Settle Attack

**Attack**: A malicious party inscribes a `settle` op claiming a trade happened with a fake
`settlement_txid` or wrong buyer/seller/price claims.

**ÐMP mitigation**:
- MUST-030: `settlement_txid` must exist in confirmed chain state.
- MUST-031: Inscription must have transferred to `buyer` in that tx.
- MUST-032: `seller` must have received at least the seller net (`price` minus the declared fees) in that tx.
- MUST-033: Royalty outputs are checked against the royalty owed and reported as `royalty_ok`. A shortfall
  is a flag, not a failed settle.
- The inscriber identity is irrelevant — only on-chain tx reality matters.

**Residual risk**: An indexer that does NOT fully verify MUST-030–037 against the actual
transaction is vulnerable. Compliant indexers are not.

---

### 3.2 UTXO Spend Race / Double-Sell

**Attack**: Seller accepts an offer from buyer A, then sells the inscription off-protocol to
buyer B before buyer A's PSDT is broadcast.

**ÐMP mitigation**:
- The first confirmed settlement (MUST-036) wins. If buyer B's settlement confirms first,
  buyer A's intended settle would fail MUST-031 (inscription no longer at seller's address).
- If no ÐMP settle exists, `provenance_gap` is set and both parties can observe on-chain
  that the inscription moved without ÐMP settlement.
- PSDT-based flows mitigate this: a signed PSDT pre-commits the inscription UTXO to a
  specific payment. Once the seller signs the PSDT, it cannot be re-directed to another output
  without invalidating the PSDT. See Section 3.6.

**Residual risk**: Without PSDT, ÐMP cannot prevent double-sell — it only makes the outcome
visible and attributable.

---

### 3.3 Stale Listing Replay

**Attack**: Old list op was inscribed, inscription was sold off-protocol, and someone now
attempts to "re-activate" the old listing or confuse indexers about its state.

**ÐMP mitigation**:
- MUST-015: listing auto-invalidates on inscription UTXO spend.
- Since ownership moved, the `seller` address no longer controls the inscription. Any new
  list attempt from the old seller would fail MUST-011 (address mismatch).
- Indexed state is deterministic: the listing is marked `invalidated` permanently.

---

### 3.4 Cancel Authorization Bypass

**Attack**: Malicious party inscribes a `cancel` op for someone else's listing.

**ÐMP mitigation**:
- MUST-041/MUST-044: canceller must be authorized party.
- MUST-041 (UTXO method): the cancel inscription tx must have an input from `canceller` address.
- MUST-042 (sig method): `sig` must verify to `canceller` address.
- For v1.0 ops without `canceller`: UTXO-based authorization is required.

**Residual risk**: For v1.0 cancel ops, the `canceller` address is not explicitly stated.
Indexers must infer it from input addresses and compare to seller/bidder/buyer on the target op.
This is unambiguous for simple single-signer wallets but requires care in multi-sig scenarios.
Recommendation: always include `canceller` in v1.0 ops.

---

### 3.5 Offer Spam

**Attack**: Bot floods chain with low-value offers to pollute indexer/UI state and consume
seller attention.

**ÐMP mitigation**:
- `offer_fee` REQUIRED and > 0. Recommended minimum: 1 DOGE (100000000 koinu).
- Indexers/wallets SHOULD deprioritize sub-threshold offers.
- Collections MAY publish preferred minimums via `default_auction_settings.min_offer_fee`.
- 4 KB soft size limit prevents oversized payloads. A v2 batch `list` is capped at 32768 B instead (compact-orders §16.11).

**Residual risk**: 1 DOGE fee is low. High-volume spam is still economically viable if DOGE
is cheap. Indexers and wallets SHOULD expose configurable fee thresholds.

---

### 3.6 PSDT Stale Execution After Cancel

**Attack**: Seller cancels a listing but the old PSDT (Partially Signed Dogecoin Transaction)
for the inscription UTXO is still floating. A buyer finds or holds the PSDT and broadcasts it.

**ÐMP mitigation**:
- The recommended cancel flow (SPEC Section 14.2):
  1. Seller sends inscription to themselves (self-transfer tx).
  2. Old PSDT is now invalid — its input UTXO is spent.
  3. Old list auto-invalidates (MUST-015).
  4. New list/PSDT issued from new UTXO if desired.
- This cryptographically invalidates the old PSDT, not just the ÐMP record.

**Critical requirement**: Marketplaces MUST implement the self-spend flow for PSDT-based listings.
Inscribing a cancel op WITHOUT the self-spend is insufficient — the PSDT remains executable.

---

### 3.7 Signature Replay

**Attack**: Old signed collection or cancel `sig` is replayed in a different context.

**ÐMP mitigation**:
- Signatures cover the full canonical JSON of the op (SPEC Section 6).
- The canonical JSON includes `inscription_id`, `ts`, `collection_id`, and other context fields.
- Replaying the sig requires having the exact same canonical JSON, which includes unique identifiers.
- Since inscription IDs are globally unique (tied to txid), signature replay across different
  inscriptions is not feasible.

**Residual risk**: Timestamp-only deduplication is weak. Implementations SHOULD use the `nonce`
field on sensitive ops (collection, collection-update, cancel) to further bind the signature to
a unique intent. Nonce does not affect validation but makes identical-JSON attacks harder.

---

### 3.8 Reorg-Based Front-Running

**Attack**: Attacker watches mempool for an accepted offer, mines a competing settle in a
reorg that confirms before the honest settle.

**ÐMP mitigation**:
- 6-block confirmation depth (MUST-030) significantly raises the cost of this attack on
  Dogecoin (~6 minutes at 1 block/minute average).
- Provisional state for sub-6-block settles: UIs MUST show "pending" until confirmation depth met.
- Savepoint-based indexers (wonky-dogeord style) handle reorgs up to ~50 blocks deep.
- First valid settle by canonical ordering wins after reorg resolution.

**Residual risk**: Dogecoin has no checkpoint mechanism beyond the confirmations model. Very deep
reorgs (> 50 blocks) could cause data loss in savepoint-based indexers. Implementations should
have off-chain backup for critical data beyond the savepoint depth.

---

### 3.9 False Royalty Claims

**Attack**: A marketplace builds a settlement tx that pays no royalties but the settle op claims
`royalty_paid` matches the declared `royalty_bps`.

**ÐMP mitigation**:
- MUST-033: indexers compute the royalty owed from the declared fees (compact order `fees`, settle `fees`,
  or the draft listing's `royalty_bps`) and compare it with the actual outputs to the royalty address in
  `settlement_txid`: `actual_royalty_output >= floor(price * royalty_bps / 10000)`. A `royalty_paid` claim
  never substitutes for the outputs.
- A shortfall sets `royalty_ok: false` and `fee_split_ok: false`. The sale still settles (MUST-031/MUST-032);
  the flag makes the skipped royalty auditable.

**Residual risk**: A sale whose own terms declare no royalty owes none. A collection manifest's
`royalty_bps` is informational only (MUST-107): indexers MUST NOT look it up to create a royalty
obligation, and UIs MAY display it next to the sale. A seller can therefore list without a royalty; that
is visible on the order itself.

**Important**: ÐMP cannot force royalty payment. It can only make non-payment auditable. PSDT-based
settlement does **not** change this: the compact-order seller signature (`SIGHASH_SINGLE|ANYONECANPAY`,
`0x83`) commits only to `in[1]` (the dog) and `out[1]` (the seller's net), so a buyer can omit the royalty
output and the fill still verifies. Royalties and venue fees are declared listing policy that indexers
verify from the authoritative order (`royalty_ok`, `listing_fee_ok`, `settlement_fee_ok`,
`fee_split_ok`; compact-orders.md §8.2), never from what a `settle` inscription claims. Consensus-enforced
royalties need the seller to sign every output (compact-orders.md §12, informative and not implemented).
See [§2.1](#21-what-is-guaranteed-vs-verified).

For compact-order fills this section's `settle` checks do not apply: a fixed-price sale is the fill
transaction itself, and no `settle` inscription is read.

---

### 3.10 Collection Manifest Forgery

**Attack**: Attacker creates a fake collection manifest claiming to be the official creator.

**ÐMP mitigation**:
- MUST-051: manifest `sig` MUST verify to `creator_address`.
- An attacker would need to forge a signature from `creator_address` or compromise that private key.
- MUST-050: slug uniqueness by earliest inscription — first valid manifest wins the slug.

**Residual risk**: If the creator's private key is compromised, the attacker can create valid
collection-updates. Creators SHOULD use a dedicated address for collection management, separate
from their trading address.

---

### 3.11 Oversized amounts, wraparound, and bogus settle links

**Risk**: Absurd `price` strings, leading zeros, or intermediate overflow in `price * royalty_bps`
produce wrong royalty checks. Settles that point at the wrong `list_id`/`auction_id` could confuse
indexers about which listing closed.

**ÐMP mitigation (normative in spec)**:
- MUST-008: positive koinu strings are bounded and digit-only (no leading zeros).
- MUST-096–MUST-098: no same-address wash `settle`; `list_id` / `auction_id` must match the same
  `inscription_id` and listing `seller` when those references are used.
- §4.3: royalty floor MUST use safe integer math (bigint / checked multiply).

**Residual risk**: Offer-only settles without `list_id` rely on MUST-030–033; marketplaces SHOULD
still cross-check `bid_id` / accept chain for UX consistency even when not fully normative.

---

### 3.12 Timestamp gaming and offer/settle races

**Risk**: Miners or users set extreme `ts` on intents; offers appear valid in UI but are expired at
settle confirmation.

**ÐMP mitigation**: MUST-102 (±2h vs MTP), MUST-103 (prefer inscription `ts` for comparisons), MUST-108
(MTP at settle vs offer `expiry`). See §3.3 and §13.

---

### 3.13 Partial multi-party cancel

**Risk**: One co-seller cancels a hot listing after bids arrive, locking out other co-sellers.

**ÐMP mitigation**: MUST-104–MUST-105 and optional `co_sellers` on `list`/`auction` (§4.4). Method B
cancel is disallowed for multi-co-seller targets until a multi-`sig` extension exists.

---

## 4. Spam and DoS Considerations

### 4.1 Inscription Spam

ÐMP does not own the Dogecoin mempool. An attacker can flood the chain with ÐMP ops, all of
which are valid inscriptions that consume block space.

**Mitigations**:
- Indexers SHOULD apply per-address rate limits in their UI/API layer.
- Indexers SHOULD enforce minimum `offer_fee` thresholds before surfacing offers.
- The 4 KB soft size limit bounds the cost per inscription to a minimum. A v2 batch `list` may be up to 32768 B (compact-orders §16.11); cost still scales with bytes.
- Wallets SHOULD show fee-policy filtering metadata so users can understand hidden offers.

### 4.2 State Inflation

An attacker with enough DOGE can create millions of low-value listings, bids, and offers, inflating
indexer state.

**Mitigations**:
- **Write budget (MUST-111 / SHOULD-113):** venues SHOULD keep live bid/offer chatter on DogeTag +
  off-chain books so spam does not land as 4 KB envelopes by default.
- Indexers SHOULD archive terminal (settled, expired, cancelled, invalidated) states to cold storage.
- Indexers MAY implement minimum listing price thresholds as local policy (not protocol level).
- The `bid_fee` optional field on bids provides a similar anti-spam vector as `offer_fee`.
  Implementations in high-volume markets SHOULD require `bid_fee` when inscription bids are used.

### 4.3 Economic Spam Modeling

In high-volume ÐMP ecosystems, spam resistance depends on DOGE price and indexer policy enforcement.

**Cost-Benefit Analysis for Attackers**:
- Inscription cost: ~0.001 DOGE (varies with block demand).
- Spam listing: creates visible noise, but indexers can filter by price/fee.
- Spam offers: `offer_fee` required > 0, recommended 1 DOGE minimum.
- Spam bids: optional `bid_fee`, but indexers SHOULD require for high-volume collections.

**Recommended Policy Thresholds**:
- Minimum `offer_fee`: 1 DOGE (100000000 koinu) for general offers.
- Minimum `bid_fee`: 0.1 DOGE (10000000 koinu) for collection-targeted bids.
- Collections MAY set higher `default_auction_settings.min_offer_fee` to deter spam.
- Indexers SHOULD expose configurable fee filters in APIs (e.g., `/offers?min_fee=100000000`).

**Mitigation Effectiveness**:
- At DOGE price $0.10, 1 DOGE fee = $0.10 cost per spam offer.
- High-volume spam (>1000 offers/day) becomes economically unviable without ROI.
- Indexer policies (rate limits, minimum fees) provide additional layers.
- Protocol-level: `nonce` field allows tooling to deduplicate accidental duplicates.

---

## 5. Implementation Security Checklist

### For Indexers

- [ ] Fully verify `settlement_txid` against Dogecoin node RPC (MUST-030–037). Never accept a settle
      on inscription content alone.
- [ ] Enforce the 6-block confirmation depth before marking settlements final.
- [ ] Track inscription ownership via satpoint (not just address) to handle edge cases.
- [ ] Process inputs before outputs in each transaction (UTXO-spend invalidations before new intents).
- [ ] Implement reorg rollback (savepoint or replay). Rollback depth MUST cover > 6 blocks at minimum.
- [ ] Never mutate the immutable audit log — append compensating events for rollbacks.
- [ ] Treat mempool ÐMP ops as provisional. Never persist permanent state from unconfirmed ops.
- [ ] Enforce MUST-011 (address-match) by checking indexer UTXO state, NOT by requiring UTXO spend.
- [ ] Validate cancel authorization (Method A UTXO or Method B sig) — do not accept anonymous cancels.
- [ ] Deprioritize sub-threshold `offer_fee` offers in API responses.

### For Wallets / Marketplaces

- [ ] Always use the self-spend cancel flow when revoking a PSDT-backed listing (Section 14.2 / 3.6).
- [ ] Refresh PSDT when inscription UTXO changes.
- [ ] Never reuse PSDT after UTXO spend invalidation.
- [ ] Show confirmation depth status for pending settlements.
- [ ] Surface provenance_gap warnings clearly — never hide them.
- [ ] For royalty-critical flows, build royalty output into the PSDT before seller signature.
- [ ] Use `nonce` field on collection and cancel ops to prevent identical-JSON attacks.

### For Creators

- [ ] Use a dedicated Dogecoin address for collection management separate from trading address.
- [ ] Keep the collection creator private key secure — it controls all future collection-updates.
- [ ] Set `supply_locked = true` for fixed supply collections to prevent supply manipulation.
- [ ] Publish a preferred `min_offer_fee` via `default_auction_settings` to reduce spam.

---

## 6. Honest Summary of Residual Risk

ÐMP v1.0 addresses the most critical attack vectors with on-chain verifiable protections. The
following residual risks remain inherent to the model:

1. **No atomic escrow**: Settlement can be raced or double-sold without PSDT flows.
2. **Royalty and venue-fee non-enforcement**: Non-payment is auditable but not preventable at protocol
   level. Only the seller's net payout is enforced by signature ([§2.1](#21-what-is-guaranteed-vs-verified)).
3. **Key compromise**: Compromised creator key enables unauthorized collection-updates.
4. **Deep reorg risk**: Reorgs > savepoint depth could require manual recovery.
5. **Spam economics**: Spam resistance depends on DOGE price and policy enforcement by indexers/UIs.

These are not ÐMP failures — they are fundamental constraints of building on Dogecoin L1 without
native smart contracts. ÐMP provides the maximum feasible protection within those constraints.
