<!-- markdownlint-disable MD024 -->
# ÐMP — Doginals Marketplace Protocol Specification

Version: v1.0 (Draft)
Status: Pre-launch draft
Last Updated: 2026-10-21
Chain: Dogecoin (and compatible Dogecoin-fork chains)
**Canonical public spec:** [github.com/jonheaven/dmp-spec](https://github.com/jonheaven/dmp-spec)

ÐMP is an open Doginals marketplace protocol. Implementations SHOULD treat it as a precise target for
independent testing until battle-tested on mainnet.

### Naming (informative)

- **Display name (user-facing):** **ÐMP** (Doginals Marketplace Protocol).
- **Path:** `spec/protocols/dmp/` (studio copy). Public canonical: **[jonheaven/dmp-spec](https://github.com/jonheaven/dmp-spec)**.
- **On-chain marker:** `p: "dmp"`.
- **Carrier:** Doginals push-only `ord` envelope (same as community Doginals). The experimental `dog` marker is **not** required for ÐMP (reserved for the GDR / eternal.dog lab).
- **Stable assets:** Schema filenames and `$id` URLs remain unchanged for compatibility.

---

## Table of Contents

1. Introduction
   - Design Goals
   - Wire philosophy (Satoshi + Casey)
   - Size Guidelines
   - Write budget (L1 surface at scale)
   - Chain is the story
   - Not Dunes / not BRC-20
   - Versioning
2. Terminology
3. Envelope Format
   - 3.1 Top-level fields
   - 3.2 Conventions
   - 3.3 Timestamp sanity
   - 3.4 Fill template (PSDT)
4. Operations Reference
   - 4.1 list
   - 4.2 bid
   - 4.3 settle
   - 4.4 cancel
   - 4.5 collection
   - 4.6 collection-update
   - 4.7 vote
   - 4.8 auction
   - 4.9 offer
   - 4.10 seller responses (counteroffer, accept, decline)
   - 4.11 transfer 
   - 4.12 Auction and Offer Negotiation Flow
   - 4.13 Minimal JSON Schema Snippets
   - 4.14 DogeTag Offers (OP_RETURN signaling extension)
5. Creator-Signed Manifests
6. Signature Canonicalization
7. Listing State Machine
8. Ownership Verification Model
9. Fixed vs Dynamic Collections
10. Update Mechanism and Immutability Policy
11. DAO Voting Hook
12. Why ÐMP (and why centralized marketplaces are inferior)
13. Indexer Verification Rules
14. Security Considerations
15. Edge Cases
16. Full JSON Examples
17. Launch Draft Summary

---

## 1. Introduction

The Doginals Marketplace Protocol (ÐMP) is an open, on-chain standard for Dogecoin **NFT / Doginal**
marketplace actions. ÐMP Intents are permanent receipts for market behavior: list, bid, auction, offer,
counteroffer, accept, decline, settle, cancel, transfer, and collection governance.

Authoritative ÐMP JSON is carried in a Doginal inscription envelope (`p: "dmp"`). That is the durable
record format — **not** the required wire for every market click. High-churn buy interest, live books, and
optional sale receipts use OP_RETURN paths (DogeTag, DOTC) and off-band PSDT bytes; see **Write budget**.

ÐMP is an **intent and proof layer**, not an atomic execution layer. Listings declare seller intent; settlements
prove that a valid on-chain transfer occurred. Indexers verify proof against real transaction data. No protocol
mechanism prevents a listing from going stale or a bad actor from skipping settlement — ÐMP makes all of that
auditable and legible, not impossible. See SECURITY.md for the full threat model.

### Design Goals

- The **fill template is the contract** (seller-signed PSDT). The inscription is a pointer + proof, not a marketplace app ABI.
- Trustless verification from chain data only.
- Portable provenance and full sales history.
- Additive fields: unknown keys MUST be ignored.
- UTXO-native ownership verification.
- Honest provenance gap detection — never hide breaks.

### Wire philosophy (Satoshi + Casey)

Dogecoin already expresses “this UTXO moves if I get this output” as
`SIGHASH_SINGLE | ANYONECANPAY`. ÐMP does not re-encode that in twenty JSON keys.

- **Do not inscribe implied facts.** On Dogecoin mainnet, `currency` is DOGE, `chain` is `dogecoin`,
  and a `list` with one seller output is a fixed-price list. Those fields MAY be omitted; if present
  they MUST match the defaults below.
- **Do not compact-rename the remaining keys** (`lm` for `listing_marketplace`). Fewer fields first.
  A later optional compact body MAY use `"c"` (compression / tagged map). Parsers MUST ignore unknown
  top-level keys.
- **Money, not labels.** `listing_fee_address` (with `market_fee_bps`) is how a listing venue is paid.
  `listing_marketplace` is an optional human tag (domain/slug). Indexers MUST NOT treat the tag as a
  payee.
- **Keep every op.** `list`, `bid`, `auction`, `offer`, `counteroffer`, `accept`, `decline`, `cancel`,
  `settle`, `transfer`, `collection`, `collection-update`, `vote` remain. This reboot thins the
  *envelope*, it does not remove the marketplace.

### Size Guidelines

Bodies SHOULD stay under **4 KB** (soft spam cap). The dominant bytes in a `list` are almost never
the metadata keys: Dogecoin listing PSDTs embed `nonWitnessUtxo` (the **full previous transaction**
of the dog UTXO). A reveal-sized parent makes a multi-KB `psdt` even when JSON keys are short.

- Implementations SHOULD reject ÐMP inscriptions larger than 4 KB.
- Sellers SHOULD move the dog to a **skinny child UTXO** (simple self-transfer) before listing if they
  intend to embed `psdt` on-chain.
- Future versions MAY add an optional compact `"c"` body. Parsers MUST fall back to raw JSON.

### Write budget (L1 surface at scale)

Dogecoin Doginals live in **scriptSig** (`OP_FALSE OP_IF "ord" …`), not Bitcoin witness. There is **no
witness discount**. Envelope bytes compete with ordinary tx weight and inflate historical chain data.
Treating every bid, offer, decline, or page view as a fat inscription is the BRC-20 / old DRC-20 failure
mode. ÐMP MUST NOT require that model.

**NFT scale ≠ token scale.** Fungible inscription tokens scale with *activity* (every mint/transfer is
another envelope). Collections scale with *pieces*, then with *sales*. A 10k collection is already 10k
unique UTXOs; listing does not spend the dog; selling does (ownership moved). Millions of users mostly
**look**. On-chain writes are durable lists, a fraction of negotiations, cancels, and settlements.

**MUST-111:** A complete ÐMP market **MUST NOT** require an inscription envelope for every bid, offer,
counteroffer, accept, decline, cancel, or page view. Indexers and venues that only surface envelope ops
remain conformant when they also index DogeTag / DOTC / payment txs; they MUST NOT claim that missing
chatty envelopes make the protocol incomplete.

**MUST-112:** Fixed-price sale truth is the **fill transaction**: the dog moves and the locked
`SIGHASH_SINGLE | ANYONECANPAY` output is paid. That transaction is the settle. A ÐMP `settle`
inscription MUST NOT change the status of a fixed-price list. Auctions have no single locked fill;
an auction `settle` inscription is only a pointer, and it MUST NOT change status unless the named
transaction already moved the dog and paid the seller. A DOTC `OP_RETURN` (`dotc|1|…`) on the fill
tx MAY label the sale. It is not required.

**SHOULD-113 (write budget):** Venues and wallets SHOULD prefer the cheapest conforming path:

| Write | Fat envelope (`dmp` inscription)? | Preferred default at scale |
| --- | --- | --- |
| Collection genesis / `collection-update` | Yes (rare) | Inscription |
| List / auction terms | Sometimes | Compact inscription; prefer `psdt_hash` over embedded `psdt` when the parent tx is fat |
| Full PSDT bytes | No (default) | Off-band / venue cache; embed only for portable Buy Now after skinny child UTXO |
| Bid / offer / decline chatter | No | [DogeTag](dogetag-offers.md) (~40-byte `OP_RETURN`) and/or venue off-chain book |
| Durable negotiated `offer` / `accept` | Optional | Inscription when parties want provenance-grade negotiation |
| Cancel | Cheap signal | Prefer spend/invalidation or compact signal; inscription `cancel` remains valid |
| Sale (money + dog move) | No | The fill transaction. That is the settle |
| `settle` inscription | No | Ignored for fixed-price. Auctions only, and only as a pointer at a fill that already paid |
| DOTC receipt | No | Optional `OP_RETURN` on the fill tx |

**Hybrid remains valid:** raw transfers without ÐMP still work; provenance shows a gap (honest UX).
Hash-only `list` (`psdt_hash`, PSDT off-band) is valid per §3.4. Full inscription ops stay first-class
when parties choose them; the write budget constrains *defaults*, not capability.

### Chain is the story

Dogecoin already records who holds the dog, who was paid, and how much. ÐMP does not inscribe that
history a second time. The indexer builds the sale from the fill. An inscription is only for a fact
the chain cannot see.

| Fact | Where it lives |
| --- | --- |
| Who owns the dog | The dog's UTXO |
| Fixed-price contract | The PSDT. Embed it, or inscribe `psdt_hash` and keep the bytes off-band |
| Which dog, price, seller — PSDT embedded | The signed outpoint and the locked output. `inscription_id`, `price`, and `seller` MAY be omitted. If present they MUST match the lock |
| Which dog, price, seller — hash-only | The list JSON. The bytes are not on chain, so the intent has to say them |
| Creator royalty | Once, on the collection inscription. Not on every list or sale |
| Bid / offer chatter | [DogeTag](dogetag-offers.md) `OP_RETURN`, or a venue book |
| Cancel | Spend the dog to yourself. The old PSDT's input is gone (MUST-015). A `cancel` inscription is a label |
| Sale | The fill transaction. Not a `settle` inscription |
| Receipt label | Optional DOTC `OP_RETURN` on the fill tx (≤ 80 bytes) |

**Do not shorten keys.** `price` versus `pr` saves less than a postage output. The bytes that cost
are `nonWitnessUtxo` inside an embedded PSDT, and every inscription that did not need to exist.
Omit fields the indexer can already see. Do not add a compact dialect.

### Not Dunes / not BRC-20

ÐMP is **not** a fungible token protocol. Dunes / ÐogeTreats move interchangeable
units via compact integer edicts in `OP_RETURN`. They have no notion of “this specific Doginal, this
price, this PSDT, this royalty output.” Inventing marketplace fields inside a dunestone would be a
**new** metaprotocol — Dunes parsers would cenotaph or ignore them. Keep Dunes for fungibles; keep ÐMP
for unique pieces. Do not answer L1-scale critiques by pretending Runes-style edicts replace NFT intents.

### Versioning

- v1.0 is the launch draft.
- `v`, when present, MUST be `"1.0"`. When absent, indexers MUST treat the op as `"1.0"`.
- After public launch, breaking wire changes MUST be a new `v`.

---

## 2. Terminology

- **Inscription**: Dogenals payload stored on-chain via OP_FALSE OP_IF "ord" script in the first input's
  scriptSig, spread across one or more chained transactions.
- **Inscription ID**: `<txid>i<vout>` where txid is the 64-char lowercase hex transaction ID of the first
  transaction in the inscription chain, and vout is the u32 output index where the inscription sat lands
  (typically 0 for standard single-output inscriptions).
- **ÐMP Intent**: inscription whose JSON includes `p = "dmp"`.
- **Op**: operation type in `op`.
- **Manifest**: collection op with creator signature and criteria.
- **UTXO**: unspent transaction output controlling inscription ownership.
- **Satpoint**: `<outpoint>:<offset>` — the precise sat-level location of an inscription within a UTXO.
- **Koinu**: smallest DOGE unit. 1 DOGE = 100,000,000 koinu.
- **Provenance gap**: state where an inscription's ownership changed without a valid ÐMP settlement/transfer path.
- **Canonical ordering**: tie-breaking order for simultaneous ops: `block_height ASC`, `tx_index_in_block ASC`,
  `output_index ASC`.

---

## 3. Envelope Format

### 3.1 Top-Level Fields

Every ÐMP Intent MUST include:

- `p`: `"dmp"` (ASCII). Any other value, including a styled form, is not a ÐMP intent.
- `op`: operation identifier

`v` MAY be omitted (defaults to `"1.0"`).

### 3.2 Conventions

- Amounts are decimal integer strings in koinu (e.g., `"100000000"` for 1 DOGE). Where this spec requires a
  **positive** amount, the string MUST match `^[1-9][0-9]*$` (no leading zeros). Implementations MUST reject
  values that do not fit in **unsigned 64-bit** arithmetic (`≤ 2^64 − 1`) to avoid silent overflow in indexers
  (MUST-008).
- Timestamps are Unix epoch seconds (integer).
- **Defaults (MUST-109):** If omitted: `v` = `"1.0"`; `currency` = `"DOGE"`; `chain` = `"dogecoin"`;
  `listing_type` on `op:"list"` = `"fixed_price"`. If any of these is present, it MUST equal the default
  (except `listing_type`, which MAY be `"auction"`).
- `psdt`, when present, MUST be standard base64 (no whitespace) encoding of PSDT bytes.
- `psdt_hash`, when present, MUST be 64-char lowercase hex SHA-256 of the **raw PSDT bytes** (not the
  base64 string). If both `psdt` and `psdt_hash` are present, the hash MUST match (MUST-110).
- Unknown fields MUST be ignored by indexers.
- JSON payload MUST be valid UTF-8.
- The `chain` field, when present, MUST equal `"dogecoin"` for mainnet Dogenals. Indexers SHOULD reject ops
  with `chain` set to any other value when operating on Dogecoin mainnet.
- The `nonce` field (optional, any string) MAY be included on any op to aid deduplication in tooling. It has
  no semantic effect on validation.
- The `sig_msg` field (optional), when present, is the hex-encoded UTF-8 bytes of the canonical JSON that was
  hashed for signing (BEFORE applying the Dogecoin signed-message prefix). This is a convenience field for
  inspection. Indexers MUST NOT accept `sig_msg` as a substitute for canonical recomputation — they MUST
  recompute the canonical payload independently and verify `sig` against it.

### 3.3 Timestamp sanity

- Timestamps in this protocol are Unix epoch **seconds** (integers), usually in field `ts` on each op.
- **MUST-102**: For any op that includes `ts`, indexers MUST reject the op as INVALID if `ts` is outside
  **±7200 seconds (2 hours)** of the **median time past (MTP)** of the block that **confirms** the
  inscription, using the same MTP definition as Dogecoin consensus (BIP113-style). Lightweight indexers
  that only store block header `nTime` MAY use `nTime` instead of MTP for this check **only if** they
  document that deviation; they SHOULD still apply the same ±7200s window.
- **MUST-103**: When comparing `ts` values for protocol logic (e.g. offer/bid expiry vs another op, or
  `settle` timing vs `auction` `expiry`), implementations MUST use the **`ts` field encoded in the relevant
  inscription JSON**, not the containing block’s timestamp, **except** where this spec explicitly requires
  comparing to **MTP(block)** of a confirming block (e.g. MUST-102, MUST-108). This reduces miner skew for
  relative ordering inscribed by users.

### 3.4 Fill template (PSDT)

A **PSDT** is a Partially Signed Dogecoin Transaction (BIP174 PSBT bytes on Dogecoin). For a fixed-price
list the seller signs the dog with `SIGHASH_SINGLE | ANYONECANPAY` and locks the same-index output
to themselves at `price` (or the residual seller amount when collaborative fees apply — see
[collaborative-fees.md](collaborative-fees.md)). The portable shape is dog at input 1, payment at output 1.

**Portable Buy Now** (any venue, no listing-server): the `list` body SHOULD include `psdt`.

**Hash-only list:** `psdt_hash` without `psdt` is a valid intent. Chain-alone fill is then **impossible**
until a party publishes the matching PSDT out of band. Indexers MAY cache PSDT bytes keyed by hash when
they see them. This is for fat parent transactions, not for hiding the contract.

Dogecoin is legacy P2PKH: listing PSDTs carry `nonWitnessUtxo` (the entire previous tx). Extra buyer
**coins** (payment + fee inputs) belong on the **buy** PSDT, not the list. Extra **outputs** (royalty,
listing fee) are cheap. Extra **inputs** are expensive.

**Postage-safe fill (MUST).** A Doginal on a postage coin is sat offset 0. `SIGHASH_SINGLE` locks the
output at the same index as the signed input. If the dog is input 0 and output 0 pays a price larger
than the postage, the inscribed sat lands in the seller's payment and the seller keeps the dog.
Indexers and wallets MUST NOT fill that shape. The portable list signs the **dog at input 1** and locks
**output 1** to the seller. The buyer replaces input 0 with a coin that covers output 0 plus output 1,
so the dog sat starts on the buyer's output. Fee inputs come **after** the dog. A `settle` inscription
is not part of this fill.

---

## 4. Operations Reference

### 4.1 list

Declares seller intent to sell an inscription.

#### Schema

```json
{
  "p": "dmp",
  "op": "list",
  "inscription_id": "<txid>i<vout>",
  "price": "<koinu>",
  "seller": "<Dogecoin address>",
  "psdt": "<base64 PSDT>"
}
```

Optional (only when they change behavior): `v`, `ts`, `expiry`, `royalty_address`, `royalty_bps`,
`market_fee_bps`, `listing_fee_address`, `listing_fee_share_bps`, `listing_marketplace` (tag only),
`collection_id`, `psdt_hash`, `listing_type` / `auction_mode` / `min_bid_increment` for auctions,
`co_sellers`, `nonce`.

#### Notes

- When `psdt` is embedded, `inscription_id`, `price`, and `seller` MAY be omitted. The indexer reads the dog from the signed outpoint, and the price and seller from the locked output. If any of the three is present, it MUST match that lock. A hash-only list (`psdt_hash`, no `psdt`) MUST still include all three.
- `listing_type` is optional (default `fixed_price`). Allowed values: `fixed_price`, `auction`.
- `listing_marketplace` is a human tag. Pay the listing venue with `listing_fee_address` + `market_fee_bps`.
- `auction_mode` is used when `listing_type` is `"auction"`.
- Allowed `auction_mode` values: `time_based`, `seller_can_accept_early`, `no_early_accept`.
- `seller_can_accept_early` allows seller to settle a valid bid before expiry.
- `no_early_accept` forbids any early acceptance; settlement can occur only after expiry.
- A `list` op is a new inscription — it does NOT spend the inscription UTXO being listed. Ownership is
  verified by address-match: `seller` MUST equal the current UTXO owner of `inscription_id` in indexer
  state at the block height of the list inscription. See Section 8.
- **Optional `co_sellers`**: array of Dogecoin addresses. When non-empty, the listing is treated as
  **multi-party** for cancel authorization (MUST-104, MUST-105). When absent or empty, only `seller` is
  required for cancel (subject to Section 8.4).

#### Inline Example (auction list)

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "list",
  "inscription_id": "aaaabbbbccccddddeeeeffff0000111122223333444455556666777788889999i0",
  "price": "100000000",
  "currency": "DOGE",
  "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
  "listing_type": "auction",
  "auction_mode": "seller_can_accept_early",
  "min_bid_increment": "50000000",
  "expiry": 1800000000,
  "chain": "dogecoin",
  "ts": 1700001000
}
```

### 4.2 bid

Expresses purchase intent against a listing or auction target.

#### Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "bid",
  "inscription_id": "<txid>i<vout>",
  "list_id": "<list inscription_id>",
  "collection_id": "<collection inscription_id>",
  "price": "<koinu>",
  "currency": "DOGE",
  "bidder": "<Dogecoin address>",
  "bid_fee": "<koinu>",
  "fee_recipient": "<Dogecoin address>",
  "expiry": 1800000000,
  "psdt": "<base64 PSDT>",
  "chain": "dogecoin",
  "nonce": "<optional string>",
  "ts": 1700000000
}
```

#### Notes

- Either `inscription_id` or `collection_id` MUST be present.
- `list_id` is optional. When present, the bid is explicitly linked to a specific active listing.
  Indexers SHOULD verify the referenced listing is active. When absent, the bid is treated as a
  general intent against `inscription_id` or `collection_id`.
- `bid_fee` is optional in the current draft. Implementations MAY require it for spam resistance.
- If `bid_fee` is present, `fee_recipient` MUST be present.
- Expired bids (where `ts` of bid + expiry window has passed at confirmation time) are INVALID and
  MUST NOT be eligible for settlement.

#### Inline Example

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "bid",
  "inscription_id": "aaaabbbbccccddddeeeeffff0000111122223333444455556666777788889999i0",
  "price": "1200000000",
  "currency": "DOGE",
  "bidder": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
  "bid_fee": "100000000",
  "fee_recipient": "D9p4Lk9xvbQ2Dyh4S8vCb9Ly8cY3h8pP1M",
  "expiry": 1700010000,
  "chain": "dogecoin",
  "ts": 1700000500
}
```

### 4.3 settle

Not used for fixed-price. The fill transaction is the settle (MUST-112). Indexers MUST ignore
`op:"settle"` on a fixed-price list.

Auctions have no single locked PSDT. An auction `settle` inscription points at the transaction the
seller accepted. It changes status only when that transaction already moved the dog and paid the
seller. A `settle` that does not is ignored. It MUST NOT leave the auction pending.

#### Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "settle",
  "inscription_id": "<txid>i<vout>",
  "list_id": "<list inscription_id>",
  "bid_id": "<bid or offer inscription_id>",
  "auction_id": "<auction inscription_id>",
  "seller": "<Dogecoin address>",
  "buyer": "<Dogecoin address>",
  "price": "<koinu>",
  "royalty_paid": "<koinu>",
  "royalty_address": "<Dogecoin address>",
  "platform_fee": "<koinu>",
  "platform_fee_recipient": "<Dogecoin address>",
  "settlement_txid": "<txid>",
  "chain": "dogecoin",
  "ts": 1700000000
}
```

#### Notes (v1.0 additions)

- `platform_fee` and `platform_fee_recipient` are optional v1.0 fields. When present, indexers SHOULD
  verify these outputs exist in `settlement_txid`.
- **Double-settle prevention**: Only the first valid `settle` op (by canonical ordering) for a given
  `list_id` or `auction_id` is accepted. Subsequent settle ops referencing the same already-settled
  listing are INVALID (idempotent rejection).
- **Confirmation depth**: Indexers MUST NOT treat settlement as confirmed until `settlement_txid`
  has at least 6 confirmed blocks (Dogecoin ~1 min/block). UIs SHOULD display "pending" for
  sub-threshold settlements. Indexers MAY configure a different depth; 6 is the recommended minimum.
- **Royalty verification**: `royalty_paid` MUST be >= `floor(price * royalty_bps / 10000)`. Indexers
  MUST verify this against actual outputs in `settlement_txid`. Implementers MUST compute
  `floor(price * royalty_bps / 10000)` using **big integers** or a safe order of operations so
  `price * royalty_bps` does not overflow 64-bit intermediates before the floor.
- **No self-sale (`settle`)**: `buyer` MUST NOT equal `seller` (exact string equality on addresses). Use
  `transfer` for non-sale moves; wash-style same-address “sales” are INVALID.
- **Reference consistency**: If `list_id` is present, the referenced `list` op’s `inscription_id` MUST equal
  this settle’s `inscription_id`. If `auction_id` is present, the referenced `auction` op’s `inscription_id`
  MUST equal this settle’s `inscription_id`.
- **Listing seller match (when `list_id` or `auction_id` is present)**: `seller` on this settle MUST equal the
  `seller` field on that `list` or `auction` op (the listing being closed). (Offer-driven settles that omit
  both MAY rely on MUST-031/MUST-032 only; see §15.3.)
- **`bid_id` and offers**: `bid_id` MAY reference a `bid`, an `offer`, an `accept`, or (when resolving
  negotiation) a `counteroffer` per MUST-099–MUST-101. (The patch draft called this `offer_id`; v1.0 wire uses
  **`bid_id`** for all of these.)
- **Zero royalty (MUST-107)**: When **effective** royalty bps is zero (listing, auction, or collection basis
  per MUST-107 in §13.4), `royalty_paid` MUST be absent or **`"0"`**.

#### Inline Example

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "settle",
  "inscription_id": "aaaabbbbccccddddeeeeffff0000111122223333444455556666777788889999i0",
  "list_id": "f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1i0",
  "bid_id": "c0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffi0",
  "seller": "D9p4Lk9xvbQ2Dyh4S8vCb9Ly8cY3h8pP1M",
  "buyer": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
  "price": "1250000000",
  "royalty_paid": "62500000",
  "royalty_address": "DNHLLgALJhMxWqnBxJYqkRDH7MjVtPrCrK",
  "settlement_txid": "9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8e",
  "chain": "dogecoin",
  "ts": 1700000900
}
```

### 4.4 cancel

Cancels a list, bid, auction, offer, or counteroffer intent.

#### Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "cancel",
  "cancel_id": "<target op inscription_id>",
  "cancel_type": "list",
  "canceller": "<Dogecoin address>",
  "reason": "seller_request",
  "sig": "<hex signature>",
  "chain": "dogecoin",
  "ts": 1700000000
}
```

Allowed `cancel_type` values: `list`, `bid`, `auction`, `offer`, `counteroffer`.

#### Cancel `reason` (MUST-106)

- `reason` is **REQUIRED** on `cancel`.
- **MUST-106**: `reason` MUST be exactly one of: `seller_request`, `expired`, `buyer_breach`,
  `admin_emergency`, `other`.
- Indexers SHOULD surface `reason` in APIs for transparency. Legacy inscriptions using older free-form
  strings (e.g. `price_change`) SHOULD be treated as `seller_request` for display only; **new** inscriptions
  MUST use the enum.
- **Compatibility**: indexers MAY accept `cancel` ops with **missing** `reason` as **non-conforming** legacy
  data (flag in API) but MUST NOT treat them as satisfying MUST-106 for strict v1.0 validation unless
  operators define an explicit legacy cutoff height.

#### Cancel Authorization Model

Cancels MUST be authorized. Two valid methods:

**Method A — UTXO-based (RECOMMENDED)**: The transaction containing the cancel inscription MUST have at
least one input UTXO controlled by the `canceller` address, proving the same party who created the intent
is cancelling it.

**Method B — Signature-based**: The `sig` field contains a Dogecoin signed-message signature (see Section
6 for canonicalization) over the canonical cancel JSON. The recovered signer MUST equal `canceller`.

In both methods, `canceller` MUST equal the authorized party for the target op:
- `list` / `auction` cancel: `canceller` MUST equal `seller` on target op.
- `bid` cancel: `canceller` MUST equal `bidder` on target op.
- `offer` cancel: `canceller` MUST equal `buyer` on target op.
- `counteroffer` cancel: `canceller` MUST equal `seller` on target op.

**v1.0 cancel ops** (without `canceller`): Indexers MUST still validate cancel authorization.
For v1.0 cancel ops, Method A UTXO-based authorization is the required verification path. The cancel
inscription tx input addresses are compared to the authorized party address on the target op.

**UTXO spend auto-invalidation** remains independent of cancel: if the inscription UTXO is spent, the
listing auto-invalidates (MUST-015) regardless of whether a cancel op exists.

#### Multi-co-seller listings and auctions (MUST-104, MUST-105)

When a `list` or `auction` includes a non-empty **`co_sellers`** array:

- **MUST-104 (Method A)**: The transaction that contains the `cancel` inscription MUST include, as inputs,
  at least one UTXO spendable by **`seller`** and at least one UTXO spendable by **each** address in
  `co_sellers` (address-match against standard script types the indexer supports). **Method B (`sig` alone)
  is INVALID** for cancels targeting such a list/auction unless a future multi-signature extension defines an
  aggregate proof.
- **MUST-105**: If **any** of the following is true at the cancel inscription’s confirmation height —
  an **active** `bid` with `list_id` / `auction_id` referencing this list or auction, or an **active**
  `offer` whose optional `list_id` / `auction_id` matches — then **every** address in the set
  `{seller} ∪ co_sellers` MUST satisfy the input requirement in MUST-104 (no partial co-seller cancel
  after negotiation has started on that listing context).

When `co_sellers` is absent or empty, cancel authorization follows Section 8.4 only.

#### Inline Example

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "cancel",
  "cancel_id": "c0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffi0",
  "cancel_type": "offer",
  "canceller": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
  "reason": "seller_request",
  "chain": "dogecoin",
  "ts": 1700000750
}
```

### 4.5 collection

Defines authoritative collection metadata and membership rules.

#### parent_inscription_id (optional, v1.0)

- **Optional** top-level string: a valid [inscription_id](#2-terminology) of a **parent** inscription
  (for example, a **parent** collection the creator points to for provenance or brand hierarchy).
- **MUST** appear only on a **root** `collection` op (the `collection` inscription that establishes the
  `slug` per this protocol). **MUST NOT** be added, removed, or changed via
  [`collection-update`](#46-collection-update) (including inside `patch`).
- When the same *collection* inscription *also* carries a [DRC-721](../dogerelics/README.md) native
  `parent` key in the *ord* inscription trailer, indexers that implement DRC-721 **MUST** enforce
  [MUST-057](#136-collection): the value **MUST** match the same `parent` as the 36 B wire
  (same ÐMP string id) or the op is **inconsistent** (reject or flag, per policy).
- This ÐMP field is **application metadata** for marketplaces. The on-chain *strong* parent/child
  link remains DogeRelics + UTXO rules in [DogeRelics §3](../dogerelics/README.md#3-parent-and-utxo-validation).
  A collection without a native ÐMP `parent_inscription_id` and without a DRC-721 `parent` tag is still
  a valid ÐMP `collection` when all other `collection` rules pass.

**Relationship to DRC-721 (informative):** DRC-721 and ÐMP **compose**; they are not two encodings of
the same job. See [drc721-and-dmp.md](../../comparisons/drc721-and-dmp.md). In particular:

- Native envelope **tag 3** / DRC-721 `parent` on a **child** is piece provenance. **Verified** only if
  the child’s first reveal **spends** the parent UTXO ([DogeRelics §3](../dogerelics/README.md#3-parent-and-utxo-validation)).
- `criteria.mode: "parent"` is a **membership rule** for this collection (who is a member), not that UTXO proof.
- `parent_inscription_id` on this op is a **parent collection** pointer (hierarchy), not “this piece’s parent.”

#### Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "collection",
  "slug": "doge-punks",
  "name": "Doge Punks",
  "creator_address": "<Dogecoin address>",
  "royalty_address": "<Dogecoin address>",
  "royalty_bps": "500",
  "type": "fixed",
  "supply": "10000",
  "supply_locked": true,
  "allow_burn": false,
  "criteria": {
    "mode": "explicit",
    "inscription_ids": ["<txid>i0"]
  },
  "signed_list": {
    "inscription_ids": ["<txid>i0"],
    "sig": "<hex>",
    "sig_msg": "<hex>"
  },
  "default_auction_settings": {
    "enabled": true,
    "auction_mode": "time_based",
    "min_bid_increment": "100000000",
    "min_offer_fee": "100000000"
  },
  "requires_vote": false,
  "parent_inscription_id": "<optional parent inscription_id, root collection only, v1.0>",
  "sig": "<hex>",
  "sig_msg": "<hex>",
  "chain": "dogecoin",
  "ts": 1700000000
}
```

`parent_inscription_id` in this schema block is optional. When present, it **MUST** follow the
[parent_inscription_id (optional, v1.0)](#parent_inscription_id-optional) rules above.

#### default_auction_settings

- Optional collection-level defaults used by wallets/marketplaces as policy hints, not binding overrides.
- `auction_mode` allowed: `time_based`, `seller_can_accept_early`, `no_early_accept`.
- `min_offer_fee` is expressed in koinu and is advisory policy for spam filtering.

#### Inline Example

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "collection",
  "slug": "doge-punks",
  "name": "Doge Punks",
  "creator_address": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
  "royalty_address": "DNHLLgALJhMxWqnBxJYqkRDH7MjVtPrCrK",
  "royalty_bps": "500",
  "type": "fixed",
  "supply": "3",
  "supply_locked": true,
  "allow_burn": false,
  "criteria": {
    "mode": "explicit",
    "inscription_ids": [
      "c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4i0",
      "d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5i0",
      "e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6i0"
    ]
  },
  "signed_list": {
    "inscription_ids": [
      "c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4i0",
      "d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5i0",
      "e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6i0"
    ],
    "sig": "<hex>",
    "sig_msg": "<hex>"
  },
  "requires_vote": false,
  "sig": "<hex>",
  "sig_msg": "<hex>",
  "chain": "dogecoin",
  "ts": 1700000000
}
```

### 4.6 collection-update

Append-only patch update for collection state. The `patch` object **MUST NOT** add, remove, or change
`parent_inscription_id` (or any not-yet-manifested `collection` top-level key reserved for the root
operation). Parent provenance is fixed on the [root `collection` op](#45-collection) only.

#### Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "collection-update",
  "collection_id": "<root collection inscription_id>",
  "supersedes": "<current head inscription_id>",
  "update_of": "<root collection inscription_id>",
  "patch": {
    "description": "Updated metadata",
    "default_auction_settings": {
      "auction_mode": "no_early_accept",
      "min_bid_increment": "200000000"
    }
  },
  "vote_proof": {
    "vote_inscription_id": "<vote inscription_id>",
    "vote_result": "approved",
    "vote_sig": "<hex>"
  },
  "sig": "<hex>",
  "sig_msg": "<hex>",
  "chain": "dogecoin",
  "ts": 1700000000
}
```

#### Conflict resolution for simultaneous updates

When two `collection-update` ops referencing the same `supersedes` head are inscribed at the same block
height, the canonical ordering rule applies: `tx_index_in_block ASC`. The earlier-indexed tx wins.
The later op is treated as an orphaned branch and MUST be rejected by indexers.

#### Inline Example

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "collection-update",
  "collection_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2i0",
  "supersedes": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2i0",
  "update_of": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2i0",
  "patch": {
    "description": "Updated collection metadata and auction defaults",
    "default_auction_settings": {
      "auction_mode": "no_early_accept",
      "min_bid_increment": "200000000"
    }
  },
  "sig": "<hex>",
  "sig_msg": "<hex>",
  "chain": "dogecoin",
  "ts": 1701000000
}
```

### 4.7 vote

DAO governance receipt used when a collection has `requires_vote = true`.

#### Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "vote",
  "collection_id": "<collection inscription_id>",
  "proposal": "Update royalty and auction defaults",
  "vote_type": "collection-update",
  "result": "approved",
  "votes_for": "7500",
  "votes_against": "1200",
  "votes_abstain": "300",
  "quorum_bps": "500",
  "vote_start": 1700000000,
  "vote_end": 1700086400,
  "sig": "<hex>",
  "sig_msg": "<hex>",
  "chain": "dogecoin",
  "ts": 1700086400
}
```

#### Inline Example

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "vote",
  "collection_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2i0",
  "proposal": "Reduce royalty and update auction defaults",
  "vote_type": "collection-update",
  "result": "approved",
  "votes_for": "7500",
  "votes_against": "1200",
  "votes_abstain": "300",
  "quorum_bps": "500",
  "vote_start": 1700000000,
  "vote_end": 1700086400,
  "sig": "<hex>",
  "sig_msg": "<hex>",
  "chain": "dogecoin",
  "ts": 1700086400
}
```

### 4.8 auction

Auction-native intent. Use this op when auction behavior should be explicit and independently queryable,
even without a list op.

#### Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "auction",
  "inscription_id": "<txid>i<vout>",
  "seller": "<Dogecoin address>",
  "reserve_price": "<koinu>",
  "start_price": "<koinu>",
  "currency": "DOGE",
  "auction_mode": "time_based",
  "min_bid_increment": "<koinu>",
  "start_ts": 1700000000,
  "expiry": 1700007200,
  "collection_id": "<collection inscription_id>",
  "chain": "dogecoin",
  "nonce": "<optional string>",
  "ts": 1700000000
}
```

#### Field Rules

- `auction_mode` is REQUIRED.
- `expiry` is REQUIRED and MUST be > `start_ts`.
- `min_bid_increment` is REQUIRED and MUST be > 0.
- `seller` MUST equal the current UTXO owner of `inscription_id` in indexer state at this block height
  (same address-match rule as `list`, see Section 8).
- `auction_mode` values:
  - `time_based`: highest valid non-expired bid wins at/after expiry.
  - `seller_can_accept_early`: seller may settle any valid bid before expiry.
  - `no_early_accept`: settlement before expiry is INVALID.
- **Optional `co_sellers`**: same semantics as `list` (MUST-104, MUST-105).

#### Inline Example

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "auction",
  "inscription_id": "1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffffi0",
  "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
  "reserve_price": "500000000",
  "start_price": "100000000",
  "currency": "DOGE",
  "auction_mode": "no_early_accept",
  "min_bid_increment": "50000000",
  "start_ts": 1700000000,
  "expiry": 1700007200,
  "collection_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2i0",
  "chain": "dogecoin",
  "ts": 1700000001
}
```

### 4.9 offer

Private push-style offer targeted to a specific inscription or collection.

#### Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "offer",
  "offer_target_type": "inscription",
  "inscription_id": "<txid>i<vout>",
  "collection_id": "<collection inscription_id>",
  "target_seller": "<Dogecoin address>",
  "buyer": "<Dogecoin address>",
  "price": "<koinu>",
  "currency": "DOGE",
  "offer_fee": "<koinu>",
  "fee_recipient": "<Dogecoin address>",
  "expiry": 1700007200,
  "list_id": "<optional list inscription_id bound to this offer>",
  "auction_id": "<optional auction inscription_id bound to this offer>",
  "psdt": "<base64 PSDT>",
  "chain": "dogecoin",
  "nonce": "<optional string>",
  "ts": 1700000000
}
```

#### Field Rules

- `offer_target_type` REQUIRED: `"inscription"` or `"collection"`.
- If `offer_target_type` is `"inscription"`, `inscription_id` is REQUIRED.
- If `offer_target_type` is `"collection"`, `collection_id` is REQUIRED.
- `target_seller` is optional. If present, only that seller can accept.
- `offer_fee` is REQUIRED and MUST be > 0.
- `fee_recipient` is REQUIRED.
- `fee_recipient` SHOULD equal `target_seller` when `target_seller` is present.
- **Optional `list_id` / `auction_id`**: when present, the offer is explicitly bound to that listing or
  auction; indexers MUST enforce MUST-100 on `settle` when both the offer reference and settle reference
  are present.
- Expired offers MUST NOT be eligible for acceptance or settlement.

#### Offer Fee Anti-Spam Mechanism

- Minimum recommended `offer_fee`: `"100000000"` koinu (1 DOGE).
- Indexers and wallets SHOULD deprioritize or hide offers whose `offer_fee` is below the minimum.
- Collections MAY publish preferred minimums via `default_auction_settings.min_offer_fee`.
- `bid_fee` remains optional in the current draft, but wallets/indexers MAY apply similar policy to bids.

#### Inline Example

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "offer",
  "offer_target_type": "inscription",
  "inscription_id": "aaaabbbbccccddddeeeeffff0000111122223333444455556666777788889999i0",
  "target_seller": "D9p4Lk9xvbQ2Dyh4S8vCb9Ly8cY3h8pP1M",
  "buyer": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
  "price": "1250000000",
  "currency": "DOGE",
  "offer_fee": "100000000",
  "fee_recipient": "D9p4Lk9xvbQ2Dyh4S8vCb9Ly8cY3h8pP1M",
  "expiry": 1700010000,
  "chain": "dogecoin",
  "ts": 1700000400
}
```

### 4.10 Seller Responses (counteroffer, accept, decline)

#### 4.10.1 counteroffer Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "counteroffer",
  "offer_id": "<offer inscription_id>",
  "seller": "<Dogecoin address>",
  "counter_price": "<koinu>",
  "currency": "DOGE",
  "expiry": 1700013600,
  "psdt": "<base64 PSDT>",
  "chain": "dogecoin",
  "ts": 1700000600
}
```

#### 4.10.2 accept Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "accept",
  "target_op": "offer",
  "target_id": "<offer or counteroffer inscription_id>",
  "seller": "<Dogecoin address>",
  "accept_reason": "accepted_best_private_offer",
  "chain": "dogecoin",
  "ts": 1700000800
}
```

#### 4.10.3 decline Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "decline",
  "target_op": "offer",
  "target_id": "<offer or counteroffer inscription_id>",
  "seller": "<Dogecoin address>",
  "decline_reason": "price_too_low",
  "chain": "dogecoin",
  "ts": 1700000700
}
```

#### Seller Response Rules

- `counteroffer` MUST reference an existing active offer.
- `accept` MUST reference an active offer or counteroffer.
- `decline` MUST reference an active offer or counteroffer.
- Only the controlling seller of the target inscription may issue counteroffer/accept/decline.
  Controlling seller = current UTXO owner of the targeted inscription (see Section 8).
- An accepted target is terminal for negotiation state and MUST be marked closed.
- Accepted and declined branches MUST NOT be accepted again.
- Expired offers and counteroffers MUST NOT be accepted, declined, or countered.

#### Inline Examples

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "counteroffer",
  "offer_id": "c0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffi0",
  "seller": "D9p4Lk9xvbQ2Dyh4S8vCb9Ly8cY3h8pP1M",
  "counter_price": "1500000000",
  "currency": "DOGE",
  "expiry": 1700013600,
  "chain": "dogecoin",
  "ts": 1700000600
}
```

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "accept",
  "target_op": "offer",
  "target_id": "c0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffi0",
  "seller": "D9p4Lk9xvbQ2Dyh4S8vCb9Ly8cY3h8pP1M",
  "accept_reason": "accepted_best_private_offer",
  "chain": "dogecoin",
  "ts": 1700000800
}
```

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "decline",
  "target_op": "offer",
  "target_id": "c0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffi0",
  "seller": "D9p4Lk9xvbQ2Dyh4S8vCb9Ly8cY3h8pP1M",
  "decline_reason": "price_too_low",
  "chain": "dogecoin",
  "ts": 1700000700
}
```

### 4.11 transfer 

Explicit non-sale ownership transfer for provenance continuity. Use this op to document gifts, airdrops,
migrations, and other ownership changes that are not marketplace sales. A valid `transfer` op clears an
existing provenance gap from the given `transfer_txid` forward.

**This op does not require a prior listing.** It is the ÐMP bridge for off-protocol moves that the owner
wants to document on-chain retroactively or prospectively.

#### Schema

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "transfer",
  "inscription_id": "<txid>i<vout>",
  "from_address": "<Dogecoin address>",
  "to_address": "<Dogecoin address>",
  "transfer_type": "gift",
  "note": "<optional human-readable note, max 140 chars>",
  "transfer_txid": "<confirmed txid of the actual UTXO move>",
  "chain": "dogecoin",
  "ts": 1700000000
}
```

#### Field Rules

- `inscription_id` REQUIRED.
- `from_address` REQUIRED. MUST equal the previous UTXO owner of `inscription_id` before `transfer_txid`.
- `to_address` REQUIRED. MUST equal the new UTXO owner of `inscription_id` after `transfer_txid`.
- `transfer_type` REQUIRED. Allowed values: `gift`, `airdrop`, `migration`, `burn`, `other`.
- `transfer_txid` REQUIRED. Indexers MUST verify `inscription_id` moved from `from_address` to
  `to_address` in this confirmed transaction.
- `note` is optional, for human-readable context (collections, lore). Max 140 characters.
- A `transfer` op is itself a new inscription — it is NOT the same as the transfer transaction.
  It may be inscribed before or after the move, but `transfer_txid` MUST be confirmed before indexers
  accept the provenance gap closure.
- A transfer gap closure requires 6 confirmed blocks on `transfer_txid` (same rule as settle).

#### Provenance Gap Closure Rule

When a valid `transfer` op is indexed:
1. If `provenance_gap = true` for `inscription_id` due to the spending of the UTXO in `transfer_txid`,
   indexers MUST set `provenance_gap = false` and record the restoration event.
2. Subsequent ownership is tracked from `to_address` forward.
3. A `transfer` op that does NOT match confirmed on-chain reality for `transfer_txid` MUST be rejected.

#### Inline Example

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "transfer",
  "inscription_id": "aaaabbbbccccddddeeeeffff0000111122223333444455556666777788889999i0",
  "from_address": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
  "to_address": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
  "transfer_type": "gift",
  "note": "Gifted to community winner of Doge Punks raffle #001",
  "transfer_txid": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
  "chain": "dogecoin",
  "ts": 1700001200
}
```

### 4.12 Auction and Offer Negotiation Flow

```text
flowchart TD
  A[List or Auction Created] --> B{Buyer Path}
  B -->|Public| C[Bid]
  B -->|Private| D[Offer]
  D --> E[Counteroffer]
  D --> F[Decline]
  E --> G[Accept]
  D --> G
  C --> H{auction_mode}
  H -->|time_based| I[Settle at/after expiry]
  H -->|seller_can_accept_early| J[Seller settles before expiry]
  H -->|no_early_accept| K[Settle only at/after expiry]
  G --> L[Settle]
  I --> L
  J --> L
  K --> L
  L --> M[Provenance updated, listing closed]
```

### 4.13 Minimal JSON Schema Snippets (Per Operation)

These snippets define interoperable minimum validation shape. Interpret alongside MUST rules in Section 13.

#### 4.13.1 list

```json
{
  "type": "object",
  "required": ["p", "v", "op", "inscription_id", "price", "seller"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "const": "list" },
    "inscription_id": { "type": "string", "pattern": "^[0-9a-f]{64}i[0-9]+$" },
    "price": { "type": "string", "pattern": "^[1-9][0-9]*$" },
    "seller": { "type": "string", "minLength": 20 }
  }
}
```

#### 4.13.2 bid

```json
{
  "type": "object",
  "required": ["p", "v", "op", "price", "bidder"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "const": "bid" },
    "inscription_id": { "type": "string", "pattern": "^[0-9a-f]{64}i[0-9]+$" },
    "collection_id": { "type": "string", "pattern": "^[0-9a-f]{64}i[0-9]+$" },
    "price": { "type": "string", "pattern": "^[1-9][0-9]*$" }
  },
  "anyOf": [
    { "required": ["inscription_id"] },
    { "required": ["collection_id"] }
  ]
}
```

#### 4.13.3 settle

```json
{
  "type": "object",
  "required": ["p", "v", "op", "inscription_id", "seller", "buyer", "price", "settlement_txid"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "const": "settle" },
    "inscription_id": { "type": "string", "pattern": "^[0-9a-f]{64}i[0-9]+$" },
    "price": { "type": "string", "pattern": "^[1-9][0-9]*$" },
    "settlement_txid": { "type": "string", "pattern": "^[0-9a-f]{64}$" }
  }
}
```

#### 4.13.4 cancel

```json
{
  "type": "object",
  "required": ["p", "v", "op", "cancel_id", "cancel_type", "reason"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "const": "cancel" },
    "cancel_id": { "type": "string", "pattern": "^[0-9a-f]{64}i[0-9]+$" },
    "cancel_type": { "enum": ["list", "bid", "auction", "offer", "counteroffer"] },
    "reason": {
      "enum": ["seller_request", "expired", "buyer_breach", "admin_emergency", "other"]
    },
    "canceller": { "type": "string", "minLength": 20 },
    "sig": { "type": "string" },
    "chain": { "const": "dogecoin" },
    "ts": { "type": "integer" }
  }
}
```

#### 4.13.5 collection

```json
{
  "type": "object",
  "required": ["p", "v", "op", "slug", "creator_address", "type"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "const": "collection" },
    "slug": { "type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[a-z0-9-]+$" },
    "type": { "enum": ["fixed", "dynamic"] },
    "creator_address": { "type": "string", "minLength": 20 },
    "royalty_bps": { "type": "string", "pattern": "^([0-9]|[1-9][0-9]{1,2}|1000)$" },
    "parent_inscription_id": { "type": "string", "pattern": "^[0-9a-f]{64}i[0-9]+$" }
  }
}
```

#### 4.13.6 collection-update

```json
{
  "type": "object",
  "required": ["p", "v", "op", "collection_id", "supersedes", "update_of", "patch"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "const": "collection-update" },
    "collection_id": { "type": "string", "pattern": "^[0-9a-f]{64}i[0-9]+$" },
    "patch": { "type": "object" }
  }
}
```

#### 4.13.7 vote

```json
{
  "type": "object",
  "required": ["p", "v", "op", "collection_id", "result", "vote_start", "vote_end"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "const": "vote" },
    "result": { "enum": ["approved", "rejected"] },
    "vote_start": { "type": "integer" },
    "vote_end": { "type": "integer" }
  }
}
```

#### 4.13.8 auction

```json
{
  "type": "object",
  "required": ["p", "v", "op", "inscription_id", "seller", "auction_mode", "min_bid_increment", "start_ts", "expiry"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "const": "auction" },
    "auction_mode": { "enum": ["time_based", "seller_can_accept_early", "no_early_accept"] },
    "min_bid_increment": { "type": "string", "pattern": "^[1-9][0-9]*$" },
    "expiry": { "type": "integer" },
    "start_ts": { "type": "integer" }
  }
}
```

#### 4.13.9 offer

```json
{
  "type": "object",
  "required": ["p", "v", "op", "offer_target_type", "buyer", "price", "offer_fee", "fee_recipient"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "const": "offer" },
    "offer_target_type": { "enum": ["inscription", "collection"] },
    "offer_fee": { "type": "string", "pattern": "^[1-9][0-9]*$" },
    "fee_recipient": { "type": "string", "minLength": 20 }
  },
  "allOf": [
    {
      "if": { "properties": { "offer_target_type": { "const": "inscription" } } },
      "then": { "required": ["inscription_id"] }
    },
    {
      "if": { "properties": { "offer_target_type": { "const": "collection" } } },
      "then": { "required": ["collection_id"] }
    }
  ]
}
```

#### 4.13.10 counteroffer

```json
{
  "type": "object",
  "required": ["p", "v", "op", "offer_id", "seller", "counter_price"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "const": "counteroffer" },
    "offer_id": { "type": "string", "pattern": "^[0-9a-f]{64}i[0-9]+$" },
    "counter_price": { "type": "string", "pattern": "^[1-9][0-9]*$" }
  }
}
```

#### 4.13.11 accept / decline

```json
{
  "type": "object",
  "required": ["p", "v", "op", "target_op", "target_id", "seller"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "enum": ["accept", "decline"] },
    "target_op": { "enum": ["offer", "counteroffer"] },
    "target_id": { "type": "string", "pattern": "^[0-9a-f]{64}i[0-9]+$" }
  }
}
```

#### 4.13.12 transfer

```json
{
  "type": "object",
  "required": ["p", "v", "op", "inscription_id", "from_address", "to_address", "transfer_type", "transfer_txid"],
  "properties": {
    "p": { "const": "dmp" },
    "v": { "const": "1.0" },
    "op": { "const": "transfer" },
    "inscription_id": { "type": "string", "pattern": "^[0-9a-f]{64}i[0-9]+$" },
    "transfer_type": { "enum": ["gift", "airdrop", "migration", "burn", "other"] },
    "transfer_txid": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
    "note": { "type": "string", "maxLength": 140 }
  }
}
```

### 4.14 DogeTag Offers (OP_RETURN signaling extension)

ÐMP DogeTag Offers are a lightweight **signal** for buy interest. They are the **preferred default** for
chatty bids/offers at scale (see **Write budget** / MUST-111). They do **not** replace a provenance-grade
ÐMP `offer` when parties choose the inscription path. The normative extension is
[dogetag-offers.md](dogetag-offers.md).

Rules:

- A DogeTag Offer **MUST NOT** be treated as escrow or settlement.
- A full ÐMP `offer` **MAY** reference a DogeTag signal via `tag_txid`.
- Wallets and indexers **SHOULD** surface DogeTags as buy-interest pings with recipient attention amounts.
- When an inscription `offer`, `accept`, or `settle` is present, those ops remain authoritative for that
  negotiation. Venues **SHOULD** keep the live book on DogeTag + off-chain state and reserve envelopes for
  durable list/auction terms and optional sale receipts (DOTC or one `settle` per sale).
- Marketplaces **MUST NOT** require every bid war click to be an inscription to call themselves ÐMP-complete.

---

## 5. Creator-Signed Manifests

Collection and collection-update signatures follow deterministic canonical JSON signing.

1. Remove `sig` and `sig_msg` from the JSON object.
2. Sort all object keys lexicographically at every nesting level.
3. Serialize to canonical JSON (no insignificant whitespace, UTF-8).
4. Apply Dogecoin signed-message prefix and double-SHA256 hash.
5. Verify recovered signer equals `creator_address`.

For `explicit` and `creator_signed` membership modes, `signed_list.sig` SHOULD also be verified when
determining whether inscriptions are members of collections.

---

## 6. Signature Canonicalization

The following canonicalization process MUST be used for all `sig` fields:

1. Start from the full JSON object.
2. Remove signature transport fields: `sig` and `sig_msg`.
3. Serialize canonical JSON:
   - Lexicographically sorted object keys at every level.
   - No insignificant whitespace.
   - UTF-8 encoding.
   - Numbers as JSON numbers; koinu amounts as strings per spec.
4. Build Dogecoin signed-message payload:
   `"\x19Dogecoin Signed Message:\n"` + CompactSize(byte_length) + canonical_json_bytes
5. Double-SHA256 the prefixed payload.
6. Verify signature recovery against expected signer address.

`sig_msg`, when present, contains the hex-encoded result of step 3 (canonical JSON bytes before prefixing).
This is a convenience field for inspection only. Indexers MUST always recompute step 3 independently and
MUST NOT accept `sig_msg` as a substitute for canonical recomputation.

Implementations MUST reject signatures produced from non-canonical serialization.

---

## 7. Listing State Machine

Every `list` and `auction` op transitions through the following states. Indexers MUST track these states
deterministically:

```text
ACTIVE states:
  listed          - list op confirmed, inscription UTXO still owned by seller
  auction_live    - auction op confirmed, within start_ts..expiry window, no settlement

TERMINAL states:
  settled         - fill transaction confirmed (>= 6 blocks). An auction settle op only counts when it points at that tx
  cancelled       - valid cancel op confirmed
  invalidated     - inscription UTXO spent without paying the list
  expired         - listing_type=fixed_price and expiry timestamp passed with no fill
  expired_no_sale - auction_mode=time_based and expiry passed with no valid settle

PENDING states (provisional, not confirmed):
  pending_settle  - fill tx seen, awaiting 6 confirmations. A settle inscription cannot enter this state on a fixed-price list
  pending_cancel  - cancel op in mempool
```

Applying **MUST-112:** for a fixed-price list, the settlement is the transaction that spends the listed dog and pays the seller at least the locked amount (the residual, when collaborative fees are on the list). Indexers MUST enter `pending_settle` on that spend and `settled` once it has 6 confirmations. A `settle` inscription does not enter this path. A spend that does not pay the list (gift, self-move, cancel-by-spend) is `invalidated`. Auctions still name the winning fill with a `settle` inscription, and only after that fill is already on chain.

### State Transition Rules

- `listed` → `pending_settle`: fixed-price spend pays the seller and moves the dog to a different address.
- `pending_settle` → `settled`: that fill tx has >= 6 confirmations and still assigns the dog to the buyer.
- `listed` → `settled`: the same fill is already deep enough at index time.
- `listed` → `cancelled`: valid cancel op with authorization.
- `listed` → `invalidated`: inscription UTXO spent without paying the list.
- `listed` → `expired`: `expiry` timestamp reached, no settle.
- `listed` → `listed` (re-list): new list op with same inscription_id supersedes the current listing.
  Only one ACTIVE list per inscription at any time; latest by canonical ordering wins.
- `auction_live` → `settled`: valid settle op after valid bid, respecting auction_mode.
- `auction_live` → `expired_no_sale`: expiry passed, no bids or all bids below reserve.
- `auction_live` → `cancelled`: valid cancel before any valid bid is received.
- `auction_live` → `invalidated`: inscription UTXO spent.

### Handling Active Bids on Re-list

When a new `list` op supersedes an existing active listing, all active bids against the previous listing
are AUTOMATICALLY INVALIDATED by the supersession (they reference a listing that is no longer active).
Active bids against `inscription_id` without a `list_id` backref remain visible but MUST be treated as
general intent — they do not force the seller to honor old terms.

---

## 8. Ownership Verification Model

Dogenals inscriptions are stored in the first input's `script_sig` of the inscription transaction. Ownership
is tracked by the indexer via satpoint-to-inscription mapping. The current owner of an inscription is the
address controlling the UTXO at the current satpoint of that inscription.

### 8.1 Seller Authorization for list and auction

MUST-011 (revised): The `seller` field MUST equal the address currently controlling the `inscription_id`
UTXO in the indexer's confirmed state at the block height of the list/auction inscription.

A `list` or `auction` op does NOT spend the inscription UTXO. It is a new inscription in its own
transaction. Ownership verification is done by address comparison against indexer state, not UTXO spend.

### 8.2 Auto-invalidation

When the inscription UTXO (the satpoint for `inscription_id`) is spent:
1. All active `list` and `auction` ops for that inscription MUST be marked `invalidated`.
2. If the spend has no valid ÐMP `settle` or `transfer` op in the same canonical context,
   `provenance_gap` is set to `true`.
3. On reorg, these invalidations are rolled back along with the spending block.

### 8.3 Controlling Seller for Negotiation Responses

The "controlling seller" for counteroffer/accept/decline is the current UTXO owner of the
target inscription at the block height of the response op. Indexers MUST verify this
dynamically — if ownership changed between the original listing and the response, the
response is INVALID (only the current owner can respond).

### 8.4 Cancel Authorization

See Section 4.4. Method A UTXO-based authorization: the cancel inscription tx MUST have at least
one input from the `canceller` address. Method B signature-based: `sig` field MUST verify to
`canceller` address via canonical signed-message process.

### 8.5 Multi-co-seller cancels

Listings and auctions MAY include **`co_sellers`** (Section 4.1 / 4.8). When they do, **MUST-104** and
**MUST-105** in Section 4.4 govern cancel transactions. Single-seller listings ignore this section.

---

## 9. Fixed vs Dynamic Collections

- `fixed` collections: bounded supply of member inscriptions.
- `dynamic` collections: unbounded or rule-evaluated expansion.

Allowed `criteria.mode` values:

| Collection type | Allowed modes                    |
|-----------------|----------------------------------|
| `fixed`         | `explicit`, `parent`, `range`    |
| `dynamic`       | `creator_signed`, `rule_based`   |

`criteria.mode` is **membership**, not DRC-721 verification:

- `explicit` — members are the listed `inscription_ids` (with `signed_list` when required).
- `parent` — members are inscriptions whose **native parent** (envelope tag 3 and/or DRC-721 `parent`)
  is **this collection inscription**. Indexers MUST document whether membership requires a **verified**
  parent UTXO spend or accepts **claimed** tags. Tag-only children MUST NOT be labeled spec-verified DRC-721.
- `range` — members fall in an indexer-documented inscription id / number range.

This is distinct from optional root `parent_inscription_id` (a parent *collection*). Builder map:
[drc721-and-dmp.md](../../comparisons/drc721-and-dmp.md).

Slug format MUST match `^[a-z0-9-]+$` with max 64 characters. Slugs are unique per chain; earliest
confirmed inscription by canonical ordering wins.

---

## 10. Update Mechanism and Immutability Policy

`collection-update` is append-only through the `supersedes` chain.

**Permanently immutable fields** (MUST NOT change in any update):

- `slug`
- `chain`
- `type` (fixed CANNOT become dynamic)
- `parent_inscription_id` when set on the root `collection` (MUST NOT be altered or removed via
  `collection-update`; the field is only legal on the root [§4.5 `collection`](#45-collection) op)

**Conditionally immutable**:

- `supply` when `supply_locked = true`

**Mutable via collection-update**:

- `description`, `name`, `default_auction_settings`, `royalty_address`, `royalty_bps`
  (subject to vote if `requires_vote = true`)

---

## 11. DAO Voting Hook

If `requires_vote = true` on the collection, `collection-update` MUST include a valid `vote_proof`.
The referenced `vote` inscription MUST:
- Reference the same `collection_id`.
- Have `result = "approved"`.
- Have `vote_end` before the `collection-update` timestamp.
- Have a valid `sig` verifying to the collection's DAO authority.

---

## 12. Why ÐMP (and why centralized marketplaces are inferior)

ÐMP gives marketplaces eBay-like behavior without centralized trust:

- public listings and auctions
- private offers and seller negotiation workflow
- configurable auction modes
- shared settlement truth, competing frontend execution
- cross-marketplace royalty auditing

While any indexer can reconstruct raw ownership from chain data, only a standardized protocol like ÐMP
enables independent reconstruction of **market state** (active listings, bids, resolved auctions,
negotiation outcomes, royalty flows) with consistent rules across implementations.

### 12.1 Fee Model: Fully Marketplace-Controlled

- ÐMP does not collect platform fees.
- Marketplaces include their own fee outputs in the settlement transaction.
- `platform_fee` / `platform_fee_recipient` in `settle` makes these visible on-chain.
- The marketplace that closes the deal keeps its fee.

### 12.2 Intent vs. Execution — What ÐMP Does Not Guarantee

ÐMP is an **intent and proof layer**. It does NOT:
- Provide atomic execution or escrow (Dogecoin has no native smart contract escrow).
- Prevent a seller from listing on multiple venues simultaneously.
- Prevent a settlement from being broadcast before a cancel is confirmed.
- Force royalty payment (but DOES make non-payment visible and auditable).

What ÐMP DOES:
- Creates permanent on-chain records of intent.
- Enables any indexer to verify settlement proof against real transaction outputs.
- Makes all violations auditable — bad actors can be identified.
- Enables UI to surface trust signals ("ÐMP Verified" vs. "Provenance Broken").

See SECURITY.md for the full threat model and mitigation strategies.

---

## 13. Indexer Verification Rules

Any op failing a MUST rule is invalid.

### 13.1 Universal

- MUST-001: `p` MUST be `"dmp"`. Indexers MUST NOT treat any other marker as ÐMP.
- MUST-002: `v`, when present, is a recognized version. Indexers accept `"1.0"`. When `v` is absent, treat as `"1.0"`.
- MUST-003: `op` is recognized.
- MUST-004: valid UTF-8 JSON.
- MUST-005: unknown fields ignored (not errors).
- MUST-006: `chain` field, if present, MUST equal `"dogecoin"` on Dogecoin mainnet.
- MUST-007: canonical ordering tie-breaker: `block_height ASC`, `tx_index_in_block ASC`, `output_index ASC`.
- MUST-008: every koinu amount field where a **positive** integer is required MUST match `^[1-9][0-9]*$` and
  MUST parse to an integer **≤ 2^64 − 1**. Indexers MUST reject oversize strings, leading zeros, or non-digit
  characters as INVALID.
- MUST-102: `ts` sanity vs MTP (or documented `nTime` fallback) — Section 3.3.
- MUST-103: use each op’s own JSON `ts` for relative comparisons unless this spec names MTP(block) — Section 3.3.
- MUST-109: omitted `currency` / `chain` / list `listing_type` default to `"DOGE"` / `"dogecoin"` / `"fixed_price"` (Section 3.2). Present values MUST match those defaults except `listing_type` MAY be `"auction"`.
- MUST-110: if both `psdt` and `psdt_hash` are present, `psdt_hash` MUST be SHA-256 of the decoded PSDT bytes (Section 3.4).
- MUST-111: a complete ÐMP market MUST NOT require an inscription for every bid/offer/decline/cancel/page view (Write budget).
- MUST-112: fixed-price sale truth is the fill tx. A `settle` inscription MUST NOT change that list. Auction `settle` is a pointer and only counts when the named tx already paid (Write budget, Chain is the story).
- SHOULD-113: prefer DogeTag / off-band PSDT / DOTC / `psdt_hash` per the Write budget table; envelopes for durable collection + list/auction + optional per-sale receipt.

### 13.2 list

- MUST-010: the listed dog exists in indexer state. With an embedded `psdt` and no `inscription_id`, that dog is the single inscription on the signed outpoint.
- MUST-011: `seller` equals the current UTXO owner of the listed dog at the list inscription's block
  height (address-match model — NOT UTXO spend). See Section 8.1. When `seller` is omitted, the owner is the seller, and the locked output MUST pay that address.
- MUST-012: `price` is a valid positive integer string. When `price` is omitted on an embedded PSDT with no royalty or market fee, the locked output value is the price.
- MUST-013: only one ACTIVE list per inscription at any time; by canonical ordering, the latest list op
  supersedes any prior active listing.
- MUST-014: expired listings (past `expiry`) are inactive.
- MUST-015: auto-invalidate on inscription UTXO spend without valid settle/transfer path.
- MUST-016: if `listing_type` is `"auction"`, `auction_mode` MUST be a valid value.

### 13.3 bid

- MUST-020: `inscription_id` or `collection_id` MUST be present.
- MUST-021: referenced target exists in indexer state.
- MUST-022: `price` is a valid positive integer string.
- MUST-023: if `expiry` is present, expired bids MUST be treated as inactive and ineligible for settlement.
- MUST-024: if `bid_fee` is present, `fee_recipient` MUST be present.
- MUST-025: if `list_id` is present, the referenced listing MUST be active at the bid's block height.

### 13.4 settle

- MUST-030: `settlement_txid` exists in confirmed chain state with >= 6 blocks of confirmation depth
  (indexers MAY configure higher; MUST NOT accept < 1 confirmation as final).
- MUST-031: `inscription_id` transferred to `buyer` in `settlement_txid`.
- MUST-032: `seller` receives at least `price` koinu in `settlement_txid`.
- MUST-033: if `royalty_paid` is present, the actual royalty output in `settlement_txid` MUST be >=
  `floor(price * royalty_bps / 10000)`. Zero tolerance — claimed amounts MUST be present in the tx.
- MUST-034: if linked auction is `no_early_accept`, the **`ts` field on the settle inscription JSON**
  MUST be >= auction `expiry` (use inscription `ts`, not block time; MUST-103).
- MUST-035: if linked auction is `seller_can_accept_early`, settle MAY occur before expiry.
- MUST-036: **double-settle prevention**: the first valid settle by canonical ordering for a given
  `list_id` or `auction_id` wins. Subsequent settle ops for the same settled listing are INVALID.
- MUST-037: if `platform_fee` is present, `platform_fee_recipient` MUST be present and the
  corresponding output MUST exist in `settlement_txid`.
- MUST-096: `buyer` MUST NOT equal `seller` on `settle`.
- MUST-097: if `list_id` is present, the referenced `list` op’s `inscription_id` MUST equal the settle’s
  `inscription_id`; if `auction_id` is present, the referenced `auction` op’s `inscription_id` MUST equal the
  settle’s `inscription_id`.
- MUST-098: if `list_id` or `auction_id` is present, the settle’s `seller` MUST equal the `seller` on that
  referenced `list` or `auction` op.
- MUST-099: If `bid_id` references an `offer` inscription, that offer MUST exist, MUST NOT be expired for
  settlement per MUST-108, its `inscription_id` (when `offer_target_type` is `"inscription"`) MUST equal
  the settle’s `inscription_id`, and it MUST be in an **eligible** negotiation state (active or already
  `accept`ed chain leading to this settle).
- MUST-100: If `settle` references **`list_id` or `auction_id`** and **`bid_id`** resolves to an `offer` that
  includes optional **`list_id` / `auction_id`**, those fields MUST match the settle’s `list_id` /
  `auction_id` respectively (both sides present and equal, or both absent on the offer for that field).
- MUST-101: If `bid_id` resolves to an `offer`, settle `buyer` MUST equal that offer’s `buyer`. If `bid_id`
  resolves to an `accept`, settle `buyer` MUST equal the `buyer` on the **root `offer`** reached by following
  `target_id` from the accept through any `counteroffer` chain back to the originating `offer`.
- MUST-107: If the effective royalty basis is zero — the referenced `list` or `auction` has `royalty_bps`
  **`"0"`**, or the applicable **collection** manifest sets `royalty_bps` to **`"0"`** and no non-zero listing
  override exists — then `royalty_paid` MUST be absent or **`"0"`**; any positive claim is INVALID.

### 13.5 cancel

- MUST-040: `cancel_id` exists and references a non-terminal intent.
- MUST-041: canceller is authorized for target op (see Section 8.4 and Section 4.4).
- MUST-042: if `sig` is present, the signature MUST verify against `canceller` via canonical process.
- MUST-043: cancel is idempotent on already-terminal intents (settled, already-cancelled, expired).
- MUST-044: **`canceller` MUST be present** when using **Method B** (`sig`); for **v1.0** **Method A**
  (UTXO-only) cancels, `canceller` MAY be omitted when authorization is proven from inscription tx inputs
  (§4.4). If `canceller` is present, it MUST name the party authorized to cancel the target op.
- MUST-104: Multi-`co_sellers` list/auction cancel input requirements — Section 4.4.
- MUST-105: Full co-seller participation after active bid/offer on listing — Section 4.4.
- MUST-106: `reason` REQUIRED and MUST be one of `seller_request`, `expired`, `buyer_breach`,
  `admin_emergency`, `other` — Section 4.4.

### 13.6 collection

- MUST-050: `slug` unique per chain; earliest by canonical ordering wins slug registration.
- MUST-051: manifest `sig` MUST verify to `creator_address`.
- MUST-052: `explicit` mode requires valid `signed_list.sig` verifying to `creator_address`.
- MUST-053: `fixed` + `explicit` supply MUST equal `criteria.inscription_ids` list count when
  `supply_locked = true`.
- MUST-054: `royalty_bps` MUST be integer string in range `"0"` through `"1000"` (0%–10%).
- MUST-055: `default_auction_settings.auction_mode`, if present, MUST be a valid auction mode value.
- MUST-056: `slug` MUST match `^[a-z0-9-]+$` with max 64 characters.
- MUST-057: if `parent_inscription_id` is present, it MUST match the inscription_id pattern, MUST refer
  to an inscription the indexer can resolve, and (when the same *collection* inscription is indexed with
  DRC-721) MUST match a native DRC-721 `parent` tag in the *ord* trailer if one exists (same 36 B id); if
  DRC-721 `parent` and `parent_inscription_id` disagree, the op is **inconsistent** (MUST be rejected or
  flagged, per policy).
- MUST-058: `parent_inscription_id` MUST be omitted from `collection-update` `patch` and from any
  non-root `collection` use; only the root [§4.5 `collection`](#45-collection) op may carry the field.

### 13.7 collection-update

- MUST-060: `collection_id` exists in indexer state.
- MUST-061: `supersedes` MUST equal the current head inscription_id of the collection update chain.
  Competing updates to the same head are resolved by canonical ordering.
- MUST-062: `sig` MUST verify to the `creator_address` of the root collection.
- MUST-063: immutable fields (`slug`, `chain`, `type`, and `parent_inscription_id` on the root when set) MUST
  NOT be changed in `patch`.
- MUST-064: if `requires_vote = true` on collection, `vote_proof` MUST be present and valid.
- MUST-065: `patch` MUST NOT contain `parent_inscription_id` (see [§4.6](#46-collection-update)).

### 13.8 vote

- MUST-070: references existing `collection_id` in indexer state.
- MUST-071: `sig` MUST verify to the collection's DAO authority address.
- MUST-072: `vote_end` > `vote_start`.
- MUST-073: `result` is `"approved"` or `"rejected"`.

### 13.9 auction

- MUST-074: `auction_mode` is required and valid.
- MUST-075: `expiry` is required and > `start_ts`.
- MUST-076: `seller` MUST equal the current UTXO owner of `inscription_id` at this block height.
- MUST-077: `min_bid_increment` is required and > 0.

### 13.10 offer and seller responses

- MUST-080: `offer_target_type` required and valid.
- MUST-081: `inscription` target requires `inscription_id`; `collection` target requires `collection_id`.
- MUST-082: `offer_fee` required, positive integer string, > 0.
- MUST-083: `fee_recipient` required for offer.
- MUST-084: `counteroffer` references active, non-expired offer.
- MUST-085: `accept` references active, non-expired offer or counteroffer.
- MUST-086: `decline` references active, non-expired offer or counteroffer.
- MUST-087: only controlling seller (current UTXO owner) can counteroffer/accept/decline.
- MUST-088: accepted or declined negotiation MUST NOT be accepted again (terminal state).
- MUST-108: For settlement via an `offer` referenced through `bid_id`, let **MTP** be the median time past of
  the block confirming the **`settle` inscription**. The offer’s **`expiry`** MUST satisfy **`expiry` ≥ MTP**
  (offer not expired at settle confirmation). The same rule applies to the effective offer after resolving
  an `accept` / `counteroffer` chain to the root `offer`’s `expiry`.

### 13.11 transfer

- MUST-090: `inscription_id` exists in indexer state.
- MUST-091: `transfer_txid` confirmed with >= 6 blocks.
- MUST-092: `inscription_id` moved from `from_address` to `to_address` in `transfer_txid`.
- MUST-093: `from_address` MUST equal the previous UTXO owner of `inscription_id` before
  `transfer_txid`.
- MUST-094: if a `provenance_gap` exists for this inscription from `transfer_txid`, a valid `transfer`
  op MUST close it.
- MUST-095: `transfer_type` MUST be one of `gift`, `airdrop`, `migration`, `burn`, `other`.

### 13.12 Validation Priority Order

When multiple MUST rules fail, implementations SHOULD report the first failing rule in this priority:

1. Universal envelope rules (MUST-001 through MUST-008, MUST-102, MUST-103, MUST-109, MUST-110, MUST-111, MUST-112)
2. Ownership and UTXO-control rules (MUST-011, MUST-013, MUST-015, MUST-076)
3. Operation shape and required-field rules (MUST-010, MUST-020, MUST-040, MUST-050, MUST-060,
   MUST-070, MUST-074, MUST-080–083, MUST-090)
4. Negotiation lifecycle rules (MUST-084–088, MUST-100)
5. Settlement integrity rules (MUST-030–037, MUST-096–099, MUST-101, MUST-107, MUST-108)
6. Cancel rules (MUST-040–044, MUST-104–106)
7. Collection governance and immutability rules (MUST-051–058, MUST-061–065)

---

## 14. Security Considerations

See SECURITY.md for the full threat model, attack vectors, and mitigations.

Key highlights:

### 14.1 Reorg Safety

- Indexers MUST support rollback of all ÐMP state transitions.
- Savepoint-based rollback (as implemented in wonky-dogeord style indexers) is acceptable.
  Recommended savepoint interval: every 10 blocks, min 5 savepoints deep (~50 block reorg depth).
- Rollback-plus-replay is the alternative model. Both MUST produce identical final state.
- All provenance_gap events and listing state transitions MUST be revertible.
- If a confirmed `settlement_txid` or `transfer_txid` later **leaves the best chain** (reorg), indexers MUST
  downgrade any `settle` / `transfer` op that depended on it from FINAL to INVALID or PENDING, re-open affected
  listing/negotiation state per replay, and MUST NOT keep a “settled” flag driven only by the orphaned tx.

### 14.2 PSDT Stale Invalidation on Cancel

When cancelling a listing advertised with a PSDT:

1. Seller moves inscription to new UTXO via self-transfer transaction.
2. Existing PSDT tied to old inscription UTXO is now invalid (input spent).
3. Previous list op auto-invalidates via MUST-015.
4. Seller inscribes new list op from new UTXO with fresh PSDT if desired.

This sequence prevents stale PSDTs from being executable after cancellation.

### 14.3 Mempool Handling

- Mempool-based ÐMP ops are PROVISIONAL and MUST be clearly marked as such.
- Indexers MUST NOT apply permanent state changes from unconfirmed ops.
- UI SHOULD show mempool ops as "pending" — not "active" or "settled".
- On replacement or reorg, mempool ops MUST be fully retracted.

---

## 15. Edge Cases

- **Conflicting collection slugs**: earliest inscription by canonical ordering wins.
- **Auction expiry race (time_based)**: bid confirmed at block after expiry is still valid — expiry is
  evaluated at confirmation time, not mempool admission time.
- **Forbidden early settlement (no_early_accept)**: settle before expiry is INVALID regardless of payment
  correctness.
- **Simultaneous competing settle ops**: first valid settle by canonical ordering wins (MUST-036).
- **Re-list with active bids**: new list supersedes old; prior bids against `list_id` are invalidated.
- **Offer/bid expiry**: use **MUST-108** (MTP at settle confirmation vs offer `expiry`) and **MUST-103**
  (prefer inscription JSON `ts` for op-to-op comparisons, not miner block time).
- **Royalty underpayment**: a settle that claims royalties but pays less than
  `floor(price * royalty_bps / 10000)` is INVALID per MUST-033.
- **Zero-price settle**: a settle with `price = "0"` is a valid settlement only if the listing price was
  also `"0"`. Indexers MUST reject settles where `price` does not match verified on-chain payment amount.

### 15.1 Auction Timing Edge Cases

**Example A**: late bid near expiry (time_based)
- expiry = 1700007200; bid confirms at block time 1700007203.
- Bid is VALID — expiry is checked at confirmation time, not broadcast time.
- Indexers SHOULD mark pre-confirmation UI state as provisional.

**Example B**: forbidden early settlement (no_early_accept)
- settle op block timestamp 1700007100, expiry 1700007200.
- MUST-034 fails; settle is INVALID regardless of payment correctness.

**Example C**: allowed early settlement (seller_can_accept_early)
- settle op block timestamp 1700007100, expiry 1700007200.
- Valid if MUST-030–033, MUST-035 all pass.

### 15.2 Provenance Gap Edge Cases

**Example D**: off-protocol transfer
- Inscription UTXO spent without valid ÐMP op.
- `provenance_gap = true` from that txid forward.

**Example E**: gap closure via transfer op
- `transfer` op inscribed with matching `transfer_txid`.
- Indexers verify and set `provenance_gap = false` for that inscription.

**Example F**: mempool/reorg gap reversal
- Provisional provenance_gap detected in mempool.
- Replacement/reorg removes triggering spend.
- Indexer MUST remove provisional gap event and recompute from canonical chain state.

### 15.3 Settlement reference edge cases

- **Mismatched `list_id` / `auction_id`**: a settle whose `list_id` or `auction_id` points at a different
  `inscription_id` than the settle body is INVALID (MUST-097).
- **Same-address buyer and seller**: INVALID (MUST-096); use `op: "transfer"` to document non-sale moves.
- **Offer / accept path without `list_id`**: some private sales settle from an `offer` → `accept` chain without
  a concurrent `list`. MUST-097/MUST-098 do not apply when **both** `list_id` and `auction_id` are absent;
  MUST-030–033 and MUST-031/MUST-032 remain authoritative for on-chain reality.
- **Integer overflow in royalty math**: `price * royalty_bps` MUST NOT be computed in a type that wraps;
  use bigint or `checked_mul` (see §4.3 notes).
- **`bid_id` → `offer` linkage**: MUST-099–MUST-101; optional offer fields `list_id` / `auction_id` enable
  MUST-100 cross-checks against settle.
- **Zero listing royalty**: MUST-107 when `royalty_bps` is `"0"` on the referenced list/auction.

### 15.4 Cancel and timestamp edge cases

- **`reason` enum**: MUST-106; legacy strings MAY be displayed as `seller_request` but MUST NOT be minted anew.
- **`ts` drift**: MUST-102 rejects ops whose `ts` is far from the confirming block’s MTP (clock abuse / spam).
- **Multi-`co_sellers`**: partial cancel without all required inputs is INVALID after MUST-104/MUST-105.

---

## 16. Full JSON Examples

See EXAMPLES directory for canonical operation payloads, including:

- bid-op.json
- auction-op.json
- offer-op.json
- counteroffer-op.json
- accept-op.json
- decline-op.json
- collection-with-parent-inscription.json (v1.0: optional `parent_inscription_id` on root `collection`)

---

## 17. Launch Draft Summary

ÐMP v1.0 is the first Dogenals marketplace launch draft. It includes:

- Marketplace intents for `list`, `bid`, `auction`, `offer`, seller responses, `settle`, `cancel`, and `transfer`.
- Collection manifests and `collection-update` rules.
- Optional root `collection.parent_inscription_id`, aligned with DRC-721 native `parent` / UTXO validation.
- Creator signatures, canonical ordering, provenance gap handling, and settlement verification.
- **Write budget (MUST-111 / MUST-112 / SHOULD-113):** one collection inscription for royalty, one list
  for the PSDT or its hash, DogeTag for bids, the fill tx as the settle. No `settle` inscription on a
  fixed-price sale. Dogecoin envelopes are scriptSig (no witness discount).
- ÐMP DogeTag Offers by reference as a lightweight OP_RETURN signaling extension.
- Explicit split from Dunes/Treats (fungible edicts ≠ unique Doginal marketplace intents).

This specification is pre-launch. No prior ÐMP mint or deployment constrains this launch draft.
