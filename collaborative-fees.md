# ÐMP Collaborative Marketplace Fees

Version: v0.1 (Draft extension)  
Status: Greenfield — additive to ÐMP v1.0  
Last Updated: 2026-08-30  
Chain: Dogecoin  

**Parent:** [spec.md](./spec.md)  
**Ecosystem plan:** operator collective plan (not in this repo)

---

## 1. Motivation

Creators need long-term royalties. Marketplaces need a reason to support a **shared order book** instead of siloing liquidity. Dogecoin cannot covenant-force fees, but settlement **can** pay multiple outputs. This extension standardizes:

1. **Creator royalty** (already on list/collection).  
2. **Listing venue fee** — marketplace that published the list.  
3. **Settlement venue fee** — marketplace that completed the buy.  

Compliant venues pay **all three** when terms are present. Indexers (dogex) verify. Non-compliant sales remain possible but are labeled gaps.

---

## 2. Terminology

| Term | Meaning |
|------|---------|
| **PSDT** | Partially Signed Dogecoin Transaction (wire: same class as PSBT) |
| **sale_price** | Gross price in koinu for the listed inscription (`list.price`) |
| **listing venue** | Operator that created / hosts the list intent |
| **settlement venue** | Operator that builds the buy PSDT / closes the sale |
| **market_fee_bps** | Total marketplace fee bps of `sale_price` (both venues combined) |
| **listing_fee_share_bps** | Portion of market fee to listing venue (default **5000** = 50%) |

Royalty is **independent** of market fee: royalty is computed from `sale_price` (or collection policy), not from residual after fees, unless a future version says otherwise.

---

## 3. Additive list fields

Optional on `op: "list"` (and auction lists). Unknown fields remain ignored by older indexers (`additionalProperties`).

| Field | Type | Description |
|-------|------|-------------|
| `royalty_address` | string | Creator pay-to (MAY inherit from collection) |
| `royalty_bps` | string/int | 0–1000 (10% max recommended) |
| `market_fee_bps` | string/int | Total marketplace fee bps (e.g. `"200"` = 2%) |
| `listing_fee_address` | string | Dogecoin address for listing venue |
| `listing_fee_share_bps` | string/int | Share of market fee to listing venue (default `5000`) |
| `listing_marketplace` | string | Optional **label** (`dogecoin.dog`, slug, domain). Not a payee. |

### Normative defaults

- If `market_fee_bps` absent → **0** market fee (royalty still applies if set).  
- If `listing_fee_share_bps` absent and market fee > 0 → **5000**.  
- If `market_fee_bps` > 0 and `listing_fee_address` absent → list is **valid** but settlement cannot pay listing venue; indexers SHOULD flag `listing_fee_unspecified`.  
- `listing_marketplace` MUST NOT be treated as a fee address.  
- `market_fee_bps` + `royalty_bps` MUST leave seller residual ≥ dust policy (implementation min 0.01 DOGE recommended).
- Classic OpenOrdex fills (seller output = full `price`) are valid when `market_fee_bps` is 0 or omitted. Do not inscribe a 2% rake unless the seller PSDT locks the residual.

### Example

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "list",
  "inscription_id": "aaaabbbbccccddddeeeeffff0000111122223333444455556666777788889999i0",
  "price": "10000000000",
  "seller": "DSellerAddressxxxxxxxxxxxxxxxxxxxx",
  "royalty_address": "DCreatorAddressxxxxxxxxxxxxxxxxxxx",
  "royalty_bps": "500",
  "market_fee_bps": "200",
  "listing_fee_address": "DListingVenueFeeAddressxxxxxxxxxxx",
  "listing_fee_share_bps": "5000",
  "listing_marketplace": "dogenals.com",
  "psdt": "cHNidP8B..."
}
```

---

## 4. Settlement money path

Given `sale_price` (koinu):

```
royalty_koinu     = floor(sale_price * royalty_bps / 10000)   if royalty_address set
market_koinu      = floor(sale_price * market_fee_bps / 10000)
listing_fee_koinu = floor(market_koinu * listing_fee_share_bps / 10000)
settle_fee_koinu  = market_koinu - listing_fee_koinu
seller_koinu      = sale_price - royalty_koinu - market_koinu
```

**Buyer PSDT / settle tx** (after seller inscription input) SHOULD include outputs:

1. Inscription to buyer (or protocol-equivalent).  
2. `seller_koinu` → seller.  
3. `royalty_koinu` → royalty_address (if > 0).  
4. `listing_fee_koinu` → listing_fee_address (if > 0 and address set).  
5. `settle_fee_koinu` → settlement venue fee address (if > 0).  
6. Change / miner fee per wallet policy.

Settlement venue supplies `settlement_fee_address` at **buy prepare** time (not on list).

---

## 5. Indexer verification (dogex MUST)

When validating a settle (or completed buy tx against an active list):

| Check | Flag |
|-------|------|
| Inscription moved seller → buyer | ownership path |
| Seller received ≥ `seller_koinu` (policy: exact or ≥) | `seller_paid_ok` |
| Royalty address received ≥ `royalty_koinu` | `royalty_ok` (or N/A) |
| Listing fee address received ≥ `listing_fee_koinu` | `listing_fee_ok` |
| Settlement fee address received ≥ `settle_fee_koinu` | `settlement_fee_ok` |
| All required fee legs OK | `fee_split_ok` |

**MUST NOT** reject the UTXO ownership update if fees missing — only mark compliance flags. UI and aggregators filter on `fee_split_ok && royalty_ok`.

---

## 6. Settle op (optional claim fields)

Settle MAY include (additive):

- `royalty_paid`, `royalty_address` (existing)  
- `listing_fee_paid`, `listing_fee_address`  
- `settlement_fee_paid`, `settlement_fee_address`  
- `market_fee_bps`, `listing_fee_share_bps`  

Indexers verify claims against the settlement tx; mismatch → `Failed` or `Interrupted`.

---

## 7. Non-goals

- Covenant-enforced fees on raw transfers.  
- Requiring both venues to run the same backend.  
- Privatizing dogex protocol rules behind paid APIs (hosting may be paid; reindex remains free).

---

## 8. Operator collective note

Collaborative fees make multi-venue ÐMP **economically rational**. Hosted index/API credits are a **separate** product layer (command.dog / gateway). See OPERATOR_COLLECTIVE_PLAN.md.
