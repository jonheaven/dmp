# ÐMP Collaborative Marketplace Fees

Version: ÐMP 1.0 (pre-launch draft), informative companion to [compact-orders.md](compact-orders.md)  
Status: Pre-launch draft. The **normative** fee schema and math are in compact-orders.md §4 and §4.1  
Last Updated: 2026-10-23  
Chain: Dogecoin  

**Parent:** [compact-orders.md](compact-orders.md) (fees, fill, compliance flags) · [spec.md](spec.md) (other ops)  
**Guarantees:** [security.md §2.1](security.md#21-what-is-guaranteed-vs-verified)  
**Ecosystem plan:** operator collective plan (not in this repo)

> **Read this first.** In ÐMP 1.0 the fee terms of a fixed-price listing are the compact order's
> `fees` object (compact-orders.md §4). This document explains the economics of that object. The flat
> fields this document used to define (`royalty_address`, `market_fee_bps`, `listing_fee_address`, …)
> are the **draft (pre-1.0)** format. They are kept in [§9](#9-draft-pre-10-fee-fields) only so indexers
> that still read draft lists can map them. Do not emit them in new listings.

---

## 1. Motivation

Creators need long-term royalties. Marketplaces need a reason to support a **shared order book** instead
of siloing liquidity. ÐMP separates **where an item is listed** from **where it is sold**, and lets both
venues get paid:

1. **Creator royalty**, paid to `fees.royalty_to`.
2. **Listing venue fee**, paid to the marketplace that published the order (`fees.listing_to`).
3. **Settlement venue fee**, paid to the marketplace that built the buyer's fill.

Dogecoin cannot covenant-force these payments. The seller's `SIGHASH_SINGLE|ANYONECANPAY` signature
commits only to the dog input and the seller's own net output (compact-orders.md §5.2), so the buyer's
transaction decides whether fee outputs exist. Compliant venues pay **all three** when the order declares
them. Indexers verify each one against the authoritative order and record compliance flags. A sale that
skips a fee is still a valid sale. It is flagged, not rejected (compact-orders.md §8.2).

---

## 2. Terminology

| Term | Meaning |
|------|---------|
| **PSDT** | Partially Signed Dogecoin Transaction (wire: same class as PSBT) |
| **price** | Gross price in koinu the buyer pays for the dog (compact order `price`) |
| **net** | What the seller signs for on `out[1]`: `price − royalty − market` |
| **listing venue** | Operator that created or hosts the order. Paid at `fees.listing_to` |
| **settlement venue** | Operator that builds the buyer's fill. Identified per fill, not on the order (§5) |
| **`fees.market_bps`** | Total marketplace fee, bps of `price`, both venues combined |
| **`fees.listing_share_bps`** | Part of the market fee that goes to the listing venue (default `"5000"` = 50%) |

Royalty is **independent** of the market fee. Both are computed from `price`, not from a residual.

---

## 3. Fee terms on the order (ÐMP 1.0)

The `fees` object of a compact `list` order (compact-orders.md §4) is the only 1.0 way to declare fees:

| Key | Type | Rule (compact-orders.md §4) |
|-----|------|------|
| `fees.royalty_bps` | string | decimal `0..2500`. REQUIRED with `royalty_to` when > 0 |
| `fees.royalty_to` | string | creator address |
| `fees.market_bps` | string | decimal `0..2000` |
| `fees.listing_to` | string | listing-venue address. Absent ⇒ the whole market fee goes to the settlement venue |
| `fees.listing_share_bps` | string | decimal `0..10000`, default `"5000"` |

- Caps are **rejections**, not clamps: `royalty_bps > 2500` or `market_bps > 2000` makes the order INVALID.
- `fees` absent means no fees. Royalty is owed only when the order itself declares it.
- `net` MUST be ≥ 100000 koinu, otherwise the order is INVALID. Sellers SHOULD keep `net ≥ 1 DOGE`.
- `fees` is not covered by the seller's `0x83` signature. It is bound to the order key by reveal
  authorship or `asig` (compact-orders.md §7), so nobody can copy a live order and swap the payees.
- There is no 1.0 venue *label* field. The listing venue is identified by its payout address.

### Example

```json
{"p":"dmp","v":"2","op":"list","chain":"dogecoin",
 "inscription_id":"<txid>i0","utxo":"<txid>:<vout>","price":"10000000000",
 "pay_to":"<seller address>","pubkey":"<66 hex>","sig":"<DER hex>83",
 "fees":{"royalty_bps":"500","royalty_to":"<creator address>","market_bps":"200","listing_to":"<listing venue address>"},
 "ts":1792632460}
```

`listing_share_bps` is omitted because it is the default (`"5000"`). Real signed orders are in
[EXAMPLES/v2/](EXAMPLES/v2/) and `vectors/dmp_v2_vectors.json`.

---

## 4. Money path

The split is compact-orders.md §4.1 (integer math, floor), repeated here for reading convenience.
If the two ever differ, compact-orders.md wins.

```
royalty    = royalty_to ? floor(price · royalty_bps / 10000) : 0
market     = floor(price · market_bps / 10000)
listing    = (listing_to and market > 0) ? floor(market · listing_share_bps / 10000) : 0
settlement = market − listing
net        = price − royalty − market          (the amount the seller signs)
```

### Worked examples

Order: `royalty_bps "500"`, `market_bps "200"`, `listing_share_bps` default `"5000"`.

| | price 100 DOGE, `listing_to` set | price 1.23456789 DOGE, `listing_to` set | price 100 DOGE, no `listing_to` |
|---|---:|---:|---:|
| `price` | 10,000,000,000 | 123,456,789 | 10,000,000,000 |
| `royalty` (5%) | 500,000,000 (5 DOGE) | 6,172,839 | 500,000,000 |
| `market` (2%) | 200,000,000 (2 DOGE) | 2,469,135 | 200,000,000 |
| `listing` (50% of market) | 100,000,000 (1 DOGE) | 1,234,567 | 0 |
| `settlement` | 100,000,000 (1 DOGE) | 1,234,568 | 200,000,000 |
| `net` (seller signs) | 9,300,000,000 (93 DOGE) | 114,814,815 | 9,300,000,000 |

All amounts in koinu. Flooring always leaves the remainder with the next party down: the odd koinu of
`market` goes to the settlement venue, and the fractions dropped from `royalty` and `market` stay in
`net`. Venues SHOULD keep every fee output ≥ 0.01 DOGE or merge it into change
(compact-orders.md §8.4).

---

## 5. Building the fill

The seller's signature fixes `in[1]` (the dog) and `out[1]` (`net` → `pay_to`). The buyer's venue adds
everything else. The canonical layout (compact-orders.md §8.2):

```
in[0]  buyer coin, value ≥ net
in[1]  dog (seller sig, 0x83)
in[2…] buyer payment / fee coins
out[0] buyer change = value(in[0]) − net
out[1] signed: net → pay_to
out[2] dog → buyer
out[3…] royalty → royalty_to, listing → listing_to, settlement → settlement venue,
        optional OP_RETURN, buyer change
```

The settlement venue is not named on the order. A venue that wants `settlement_fee_ok` checked tags its
fill with the optional `dmp2` OP_RETURN naming its own script (compact-orders.md §8.3). A fill that
carries a different OP_RETURN instead (for example dogesoft's `{"ds":…}`) is still valid, and its
settlement fee is reported as `null` (not checked).

---

## 6. Indexer verification

Indexers derive the expected amounts from the **authoritative order they indexed**, never from claims in
a `settle` inscription or from a venue API. The flags are compact-orders.md §8.2:

| Flag | Meaning |
|------|---------|
| `seller_paid_ok` | the fill rule holds: `in[1]` spends `utxo` and `out[1]` equals the signed output |
| `royalty_ok` | `null` if no royalty is owed, else (paid to `royalty_to`, excluding `out[1]`) ≥ `royalty` |
| `listing_fee_ok` | same for `listing_to` / `listing` |
| `settlement_fee_ok` | `null` unless the fill has a `dmp2` tag and `settlement > 0`; then (paid to the tagged script) ≥ `settlement` |
| `fee_split_ok` | `seller_paid_ok` and no flag is `false` |

Flags **never** invalidate a sale or the ownership update. The reference indexer (dogex) records them as a
`compliance` object on the fill (the `dmp.settle_pending` event and the listing record). A UI or
aggregator that wants to show only fee-compliant sales filters on `fee_split_ok`.

---

## 7. Non-goals

- Covenant-enforced fees. (An interactive, buyer-bound variant that pins every output is described in
  compact-orders.md §12. It is informative and not implemented.)
- Requiring both venues to run the same backend.
- Privatizing ÐMP protocol rules behind paid APIs (hosting may be paid; reindexing stays free).

---

## 8. Operator collective note

Collaborative fees make multi-venue ÐMP **economically rational**: the venue that finds the buyer does
not have to be the venue that published the listing, and both get paid. Hosted index/API credits are a
**separate** product layer (command.dog / gateway). See the operator collective plan (not in this repo).

---

## 9. Draft (pre-1.0) fee fields

Before compact orders, fee terms were flat optional fields on the spec.md §4.1 `list` op. That `list`
format is now the **draft (pre-1.0)** format: wallets and venues MUST NOT create it, and ÐMP 1.0 indexers
SHOULD ignore it (compact-orders.md §2, §15). This section exists only for indexers that still read draft
lists, such as the four test listings on mainnet.

### 9.1 Field mapping

| Draft field (flat, on `list`) | ÐMP 1.0 field (in `fees`) | Differences |
|---|---|---|
| `royalty_address` | `fees.royalty_to` | Draft MAY inherit from the collection manifest. 1.0 has no inheritance: royalty is owed only if the order declares it |
| `royalty_bps` (string or int, `0–1000` recommended) | `fees.royalty_bps` (string, `0..2500`) | Draft cap was a recommendation (and MUST-054's `0–1000` for collection manifests). 1.0 cap is 2500 and a value above it is a rejection |
| `market_fee_bps` (string or int) | `fees.market_bps` (string, `0..2000`) | Draft schema bounded only the integer form at 2000. 1.0 rejects > 2000 in any form |
| `listing_fee_address` | `fees.listing_to` | Draft: absent with a market fee ⇒ list valid, flag `listing_fee_unspecified`, listing share left unpaid. 1.0: absent ⇒ `listing = 0` and the whole market fee goes to the settlement venue |
| `listing_fee_share_bps` (default `5000`) | `fees.listing_share_bps` (string, default `"5000"`) | same meaning |
| `listing_marketplace` (label, not a payee) | none | no 1.0 equivalent. Unknown fields are ignored |
| settlement fee address at buy-prepare time, settle-op claim fields | `dmp2` OP_RETURN venue tag on the fill | 1.0 never reads settlement terms from a `settle` inscription |
| seller check "≥ `seller_koinu`" | `out[1]` equals the signed output exactly | 1.0 fill rule, compact-orders.md §8.2 |

### 9.2 Precedence

- A compact order (`"v":"2"`) is read only through its `fees` object. Draft fee keys that appear
  anywhere in a compact order body are unknown fields and are ignored. **Compact-order fields always win.**
- Draft fee fields are read only from a draft `list` op, and only by an indexer that still indexes draft
  lists. Those indexers use the draft math in §9.3 and the draft-list hardening (compact-orders.md §2, §15).

### 9.3 Draft money path (historical)

```
royalty_koinu     = floor(sale_price * royalty_bps / 10000)   if royalty_address set
market_koinu      = floor(sale_price * market_fee_bps / 10000)
listing_fee_koinu = floor(market_koinu * listing_fee_share_bps / 10000)
settle_fee_koinu  = market_koinu - listing_fee_koinu
seller_koinu      = sale_price - royalty_koinu - market_koinu
```

This matches §4 except when `listing_fee_address` is absent (see the table above).
