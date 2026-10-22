# Launch Draft Summary

ÐMP v1.0 is the Doginals Marketplace Protocol launch draft. The spec has not launched on-chain and does not
carry compatibility obligations from earlier internal drafts.

## Included

- Marketplace intents: `list`, `bid`, `auction`, `offer`, `counteroffer`, `accept`, `decline`, `cancel`, and `settle`.
- Provenance operations: `transfer`, `collection`, and `collection-update`.
- Creator-signed manifests and deterministic canonical JSON signatures.
- UTXO-native ownership verification by address-match against indexed inscription state.
- Settlement verification against real Dogecoin transaction outputs.
- Optional `parent_inscription_id` on root `collection`, aligned with DRC-721 native parent tags.
- ÐMP DogeTag Offers as the Era 2 OP_RETURN signaling extension.

Future changes after public launch should be tracked here with clear versioning and migration guidance.

## Draft updates (pre-launch)

### 2026-10-21 — v2 compact signed orders (draft, regtest-tested)

New `"v":"2"` `list`/`cancel` ([spec-v2.md](spec-v2.md)). No venue hosts the PSDT any more.

- The order carries the seller's SIGHASH_SINGLE|ANYONECANPAY signature, pubkey, outpoint, price, `pay_to` and fee terms. Every indexer rebuilds the same canonical PSDT from its own node.
- Authorization: either the reveal is signed by the order key, or the op carries `asig`, a Dogecoin signed-message signature over the canonical op (fee terms, `listing_to`, `expiry` included). With `asig`, any inscriber may publish the order.
- Fee terms are declared; compliance flags never invalidate a sale. Cancel-by-move is authoritative; a signed cancel is advisory. `expiry` uses block nTime.
- v1: embedded PSDT signatures MUST verify against the P2PKH dog prevout. A v1 `list` cannot supersede an active v2 order.
- Conformance vectors: `vectors/dmp_v2_vectors.json`. Independent reference: `reference/dmp_v2_reconstruct.py`.

### 2026-10-21 — The fill is the settle

A fixed-price `settle` inscription does not change listing status (MUST-112). The fill transaction is
the sale: dog moved, locked output paid. Auction `settle` is only a pointer at a fill that already paid.

- Embedded `psdt`: `inscription_id`, `price`, and `seller` MAY be omitted. If present they MUST match the lock.
- Hash-only lists still carry those three fields.
- Cancel is the self-spend. Royalty stays on the collection inscription.
- Do not shorten JSON keys. Omit fields the indexer can already see.

### 2026-10-20 — Postage-safe fill, sale tx settles, marker is only `dmp`

- Portable list signs the dog at **input 1** and locks **output 1**. Do not fill a postage dog signed at input 0 against a price-sized output 0.
- Fixed-price settlement is the spend that pays the list and moves the dog. A `settle` inscription is optional. Auctions still use an explicit settle op. Superseded 2026-10-21: that inscription does not change a fixed-price list.
- `p` MUST be ASCII `"dmp"`. A styled marker is not ÐMP. Nothing was inscribed that way.

### 2026-10-14 — Canonical wire marker `p:"dmp"` + Doginals naming

- Emitters MUST set `p` to ASCII `"dmp"`.
- Expansion is **Doginals Marketplace Protocol** (not “Dogenals”).
- Branding in docs/UI remains **ÐMP**.
- `dog` marker is out of scope for ÐMP — reserved for GDR / eternal.dog lab.

### 2026-09-03 — L1 write budget (UTXO-maxi hardening)

Answer to “inscription ÐMP won’t scale to millions of users”: that critique only lands if every bid is a
fat envelope (BRC-20 / old DRC-20 mode). NFT markets scale with pieces + sales, not fungible transfer chatter.
Dogecoin envelopes are **scriptSig** (no witness discount).

- **MUST-111**: complete market MUST NOT require an inscription per bid/offer/decline/cancel/page view.
- **MUST-112**: sale truth is payment + dog-move tx; `settle` / DOTC are optional receipts. Superseded 2026-10-21: a fixed-price `settle` inscription does not change status.
- **SHOULD-113**: write-budget table — DogeTag / off-band PSDT / `psdt_hash` / DOTC for chatter; envelopes for
  durable collection + list/auction + optional one receipt per sale.
- Explicit **Not Dunes**: fungible edicts cannot bind unique Doginal + PSDT + royalty terms.
- README / §4.14 / DogeTag / adoption roadmap aligned: live book off envelopes by default.

### 2026-08-30 — Satoshi + Casey wire reboot

The fill template is the contract (`SIGHASH_SINGLE | ANYONECANPAY` seller PSDT). The inscription is a pointer
and ownership proof. **Every op stays** (`list`, `bid`, `auction`, `offer`, negotiation, `cancel`, `settle`,
collections). This is not a protocol shrink.

- Implied fields MAY be omitted: `currency` = DOGE, `chain` = `dogecoin`, `v` = `1.0`, `listing_type` =
  `fixed_price` (MUST-109).
- `listing_fee_address` + `market_fee_bps` are how a listing venue is paid. `listing_marketplace` is a tag.
- `psdt` SHOULD be on-chain for portable Buy Now. `psdt_hash` is allowed when the parent tx is fat (MUST-110).
  Hash-only lists are not chain-alone fillable.
- Do not compact-rename remaining keys (`lm`). Fat bytes are `nonWitnessUtxo` on Dogecoin P2PKH, not JSON labels.
- `list` still does **not** spend the listed dog. The example comment that said otherwise was wrong.

### 2026-08-05 — Collaborative marketplace fees

- [collaborative-fees.md](collaborative-fees.md): multi-venue rake (listing + settlement) + royalty split physics.
- list schema: `market_fee_bps`, `listing_fee_address`, `listing_fee_share_bps`, `listing_marketplace`.
- Ecosystem: `dogenals/docs/OPERATOR_COLLECTIVE_PLAN.md`.

**Hardening status:** The full pre-launch hardening patch (MUST-099 through MUST-108, `bid_id` / `expiry` / `co_sellers` / `list_id`–`auction_id` alignment) is **live** in `spec.md`, `security.md`, examples, and `vectors/conformance.json` for this draft.

### 2026-05-08 — Verification hardening (editorial / v1.0 draft)

- **MUST-008**: global rules for positive koinu strings (no leading zeros; ≤ 2^64 − 1).
- **Settle**: **MUST-096** (buyer ≠ seller), **MUST-097** (`list_id` / `auction_id` inscription match),
  **MUST-098** (listing `seller` match when those refs present); §4.3 notes on safe royalty multiplication.
- **MUST-099–MUST-101**: `bid_id` → `offer` / `accept` resolution, optional offer `list_id`/`auction_id`
  linkage vs settle, buyer must match root offer buyer.
- **MUST-102–MUST-103**: §3.3 timestamp sanity (±2h vs MTP; use inscription `ts` for comparisons per rules).
- **MUST-104–MUST-106**: optional **`co_sellers`** on `list`/`auction`; cancel input rules after bids/offers;
  **`reason`** enum on `cancel` with legacy note.
- **MUST-107**: zero royalty ⇒ `royalty_paid` zero/absent (list/auction/collection basis).
- **MUST-108**: offer `expiry` vs MTP at settle confirmation.
- **Reorgs**: explicit requirement to downgrade settles/transfers if `settlement_txid` / `transfer_txid` drops
  from the best chain.
- **§15.3–§15.4**: settlement reference, cancel, and timestamp edge cases.
- **§10**: removed duplicate immutable-field bullet.
- **Design record**: [`specs/dmp-hardening-patch.md`](../../specs/dmp-hardening-patch.md) (integrated; normative
  text is in this spec).
