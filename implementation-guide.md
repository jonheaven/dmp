# Doginals Marketplace Protocol (ÐMP) Implementation Guide

For indexers, wallets, marketplaces, and AI agents implementing ÐMP v1.0 and v1.0.

Read SPEC.md first. This guide focuses on implementation behavior and compliance outcomes.

---

## 1. Indexer Architecture

A ÐMP indexer must:

1. Consume Dogecoin blocks in order via RPC (`getblock`, `getrawtransaction`).
2. For each transaction, parse all Dogenals inscriptions from `script_sig` of the first input.
3. Filter `p = "dmp"` (styled alias `"Ð:MP"` MUST be accepted) and supported `v` (`"1.0"`, or omit → `"1.0"`).
4. **Process inputs before outputs** in every transaction: apply UTXO-spend invalidations before
   ingesting new ÐMP intents from outputs in the same tx.
5. Validate op-specific MUST rules from SPEC.md Section 13.
6. Persist state transitions deterministically.
7. Support rollback for reorgs (savepoint or replay model).

### 1.1 Block Processing Order

```text
for each block (ascending by height):
  for each tx in block (ascending by tx_index):
    step 1: process inputs
      - for each input: check if spent UTXO carries a known inscription
      - if yes: mark all active list/auction ops for that inscription as "invalidated"
               unless a valid ÐMP settle/transfer exists in the SAME block for this spend
      - update provenance_gap accordingly
    step 2: process outputs / new inscriptions
      - parse ÐMP ops from script_sig of new inscription txs
      - apply MUST rules
      - persist new intents and state transitions
```

---

## 2. Supported Ops by Version

| Op | v1.0 | v1.0 |
|----|------|------|
| list | ✓ | ✓ |
| bid | ✓ | ✓ (+ list_id field) |
| settle | ✓ | ✓ (+ platform_fee fields) |
| cancel | ✓ | ✓ (+ canceller required) |
| collection | ✓ | ✓ |
| collection-update | ✓ | ✓ |
| vote | ✓ | ✓ |
| auction | ✓ | ✓ |
| offer | ✓ | ✓ |
| counteroffer | ✓ | ✓ |
| accept | ✓ | ✓ |
| decline | ✓ | ✓ |
| transfer | — | ✓ (new) |

---

## 3. Ownership Verification

**Critical**: ÐMP list and auction ops are new inscriptions — they do NOT spend the listed
inscription's UTXO. Ownership is verified by address-match:

```text
function verify_seller_authorization(op, block_height):
  current_owner = get_inscription_utxo_owner(op.inscription_id, block_height)
  return current_owner == op.seller
```

Where `get_inscription_utxo_owner` looks up the inscription's current satpoint in the indexer's
UTXO state and resolves the controlling address from the output's `script_pubkey`.

This is the same address-match model used by wonky-dogeord and other Dogenals indexers for
ownership tracking.

### 3.1 Listing PSDT size (Dogecoin P2PKH)

A listing PSDT is one seller input + one (or few) seller/fee outputs. Bytes explode because Dogecoin
legacy inputs carry `nonWitnessUtxo` = the **entire previous transaction**. A P2SH reveal parent can
make `psdt` several kilobytes. Compact JSON keys (`lm`) do not fix that.

- Prefer embedding `psdt` so any venue can Buy Now from chain data.
- If the parent is fat, move the dog to a skinny child UTXO, then list.
- `psdt_hash` without `psdt` is a valid intent but **not** portable fill.

---

## 4. Listing State Machine

```text
States:
  listed           active fixed-price listing
  auction_live     active auction (within start_ts..expiry)
  settled          terminal — valid settle confirmed
  cancelled        terminal — valid cancel confirmed
  invalidated      terminal — UTXO spent without valid ÐMP path
  expired          terminal — fixed-price listing past expiry
  expired_no_sale  terminal — auction past expiry, no winning bid
  pending_settle   provisional — settle in mempool
  pending_cancel   provisional — cancel in mempool
```

### State Transition Table

| From | Event | To | MUST rule |
|------|-------|----|-----------|
| listed | valid settle confirmed (>= 6 blocks) | settled | MUST-030–036 |
| listed | valid cancel confirmed | cancelled | MUST-040–044 |
| listed | inscription UTXO spent, no ÐMP path | invalidated | MUST-015 |
| listed | expiry passed, no settle | expired | MUST-014 |
| listed | newer list op for same inscription | invalidated (superseded) | MUST-013 |
| auction_live | valid settle confirmed | settled | MUST-030–036 |
| auction_live | valid cancel (no valid bids yet) | cancelled | MUST-040–044 |
| auction_live | expiry passed, no winning bid | expired_no_sale | MUST-075 |
| auction_live | inscription UTXO spent | invalidated | MUST-015 |
| any_active | settle in mempool | pending_settle (provisional) | — |
| pending_settle | confirmed >= 6 blocks | settled | MUST-030 |
| pending_settle | replaced/reorged | revert to prior state | reorg |

---

## 5. Auction Handling

### 5.1 Auction mode semantics

| Mode | Settlement rule |
|------|----------------|
| `time_based` | Collect bids until expiry; highest valid non-expired bid wins; settle at/after expiry |
| `seller_can_accept_early` | Seller may settle any valid bid before expiry; once settled, terminal |
| `no_early_accept` | Settlement before expiry is INVALID (MUST-034); settle only at/after expiry |

### 5.2 Auction state storage

```sql
auctions (
  auction_op_id     TEXT PRIMARY KEY,  -- inscription_id of auction op
  inscription_id    TEXT NOT NULL,
  seller            TEXT NOT NULL,
  reserve_price     TEXT,
  start_price       TEXT,
  min_bid_increment TEXT NOT NULL,
  auction_mode      TEXT NOT NULL,
  start_ts          INTEGER NOT NULL,
  expiry            INTEGER NOT NULL,
  status            TEXT NOT NULL,     -- listed, auction_live, settled, cancelled, invalidated, expired_no_sale
  highest_bid_id    TEXT,
  block_height      INTEGER NOT NULL,
  tx_index          INTEGER NOT NULL
)
```

### 5.3 Bid validation against auction

For a bid to be considered for auction settlement:

1. Bid `inscription_id` (or `list_id` backref) must match an active auction.
2. Bid `price` >= auction `start_price` (if set).
3. Bid `price` >= previous highest bid + `min_bid_increment`.
4. Bid is not expired at the time of settlement consideration.
5. For `time_based` / `no_early_accept`: bid must be confirmed before auction expiry.

---

## 6. Offer and Negotiation Lifecycle

### 6.1 Offer state machine

```text
offer states:
  active       -> countered, accepted, declined, expired, cancelled
  countered    -> accepted, declined, expired, cancelled
  accepted     -> (terminal, awaits settle)
  declined     -> (terminal)
  expired      -> (terminal)
  cancelled    -> (terminal)
```

### 6.2 Response authorization

The "controlling seller" for `counteroffer`/`accept`/`decline` is the CURRENT UTXO owner of the
target inscription at the block height of the response op — not the original listing seller.

If ownership changed between the offer and the response, only the new owner can respond.

### 6.3 Collection-target offers

For `offer_target_type = "collection"` with no specific `inscription_id`:

- Acceptance is intent-only until a `settle` ties the accepted response to a concrete inscription transfer.
- At settle time, verify the inscription being transferred is a valid member of the referenced collection.

---

## 7. Transfer Op — Provenance Gap Closure

When a `transfer` op is indexed:

```text
function process_transfer(op, block_height):
  if not tx_confirmed(op.transfer_txid, min_depth=6):
    return PENDING

  actual_from = get_utxo_owner_before_spend(op.inscription_id, op.transfer_txid)
  actual_to   = get_utxo_owner_after_spend(op.inscription_id, op.transfer_txid)

  if actual_from != op.from_address or actual_to != op.to_address:
    return INVALID (MUST-092, MUST-093)

  if inscription has provenance_gap from op.transfer_txid:
    clear provenance_gap
    append provenance_restoration_event to audit log

  update inscription ownership to op.to_address
  return VALID
```

---

## 8. Cancel Authorization

### For v1.0 ops (`canceller` field present):

```text
function verify_cancel_auth(cancel_op, target_op, cancel_tx_inputs):
  authorized_party = get_authorized_canceller(target_op)
  # authorized_party is seller for list/auction/counteroffer, bidder for bid, buyer for offer

  # Method A: UTXO-based (preferred)
  if any(input.address == authorized_party for input in cancel_tx_inputs):
    return VALID

  # Method B: signature-based
  if cancel_op.sig is present:
    recovered = dogecoin_recover_signer(canonical_json(cancel_op), cancel_op.sig)
    if recovered == authorized_party:
      return VALID

  return INVALID
```

### For v1.0 ops (no `canceller` field):

Apply Method A only. Extract input addresses from the cancel inscription's transaction and compare
to the authorized party address on the target op.

---

## 9. Settlement Validation

```text
function validate_settle(settle_op, settlement_tx):
  # MUST-030: confirmation depth
  if confirmation_depth(settlement_tx) < 6:
    return PENDING

  # MUST-031: inscription transferred to buyer
  if not inscription_at_address(settle_op.inscription_id, settle_op.buyer, settlement_tx):
    return INVALID

  # MUST-032: seller received at least price
  if seller_received(settle_op.seller, settlement_tx) < parse_int(settle_op.price):
    return INVALID

  # MUST-033: royalty verification
  if settle_op.royalty_paid is not None:
    expected = floor(parse_int(settle_op.price) * royalty_bps / 10000)
    actual = royalty_output_amount(settle_op.royalty_address, settlement_tx)
    if actual < expected:
      return INVALID

  # MUST-034/035: auction mode timing
  if settle_op.auction_id is not None:
    auction = get_auction(settle_op.auction_id)
    if auction.mode == "no_early_accept":
      if settle_block_ts(settlement_tx) < auction.expiry:
        return INVALID (MUST-034)

  # MUST-036: double-settle prevention
  if is_already_settled(settle_op.list_id or settle_op.auction_id):
    return INVALID

  # MUST-037: platform_fee
  if settle_op.platform_fee is not None:
    if platform_fee_output(settle_op.platform_fee_recipient, settlement_tx) < parse_int(settle_op.platform_fee):
      return INVALID

  return VALID
```

---

## 10. Storage Schema (Recommended)

```sql
-- Core inscription ownership
inscriptions (
  inscription_id        TEXT PRIMARY KEY,
  current_satpoint      TEXT NOT NULL,
  owner_address         TEXT NOT NULL,
  provenance_gap        BOOLEAN NOT NULL DEFAULT FALSE,
  provenance_gap_from_txid TEXT,
  block_height          INTEGER NOT NULL,
  tx_index              INTEGER NOT NULL
)

-- All ÐMP ops, immutable audit log
intents (
  intent_id     TEXT PRIMARY KEY,  -- inscription_id of the ÐMP op
  op            TEXT NOT NULL,
  v             TEXT NOT NULL,
  txid          TEXT NOT NULL,
  block_height  INTEGER NOT NULL,
  tx_index      INTEGER NOT NULL,
  ts            INTEGER,
  raw_json      TEXT NOT NULL,
  valid         BOOLEAN NOT NULL,
  invalid_reason TEXT
)

-- Active listing/auction state (materialized view)
listing_state (
  inscription_id    TEXT PRIMARY KEY,
  active_list_id    TEXT,
  listing_type      TEXT,
  auction_mode      TEXT,
  price             TEXT,
  seller            TEXT,
  expiry            INTEGER,
  status            TEXT NOT NULL,   -- listed, auction_live, settled, cancelled, invalidated, expired, expired_no_sale
  settled_list_id   TEXT            -- set when status=settled
)

-- Auction-specific state
auction_state (
  auction_id        TEXT PRIMARY KEY,
  inscription_id    TEXT NOT NULL,
  seller            TEXT NOT NULL,
  mode              TEXT NOT NULL,
  start_ts          INTEGER NOT NULL,
  expiry            INTEGER NOT NULL,
  reserve_price     TEXT,
  min_bid_increment TEXT NOT NULL,
  status            TEXT NOT NULL,
  highest_bid_id    TEXT,
  block_height      INTEGER NOT NULL
)

-- Bid tracking
bid_state (
  bid_id            TEXT PRIMARY KEY,
  inscription_id    TEXT,
  collection_id     TEXT,
  list_id           TEXT,
  bidder            TEXT NOT NULL,
  price             TEXT NOT NULL,
  expiry            INTEGER,
  status            TEXT NOT NULL    -- active, expired, cancelled, superseded, settled
)

-- Offer and negotiation state
offer_state (
  offer_id          TEXT PRIMARY KEY,
  target_type       TEXT NOT NULL,
  inscription_id    TEXT,
  collection_id     TEXT,
  target_seller     TEXT,
  buyer             TEXT NOT NULL,
  price             TEXT NOT NULL,
  offer_fee         TEXT NOT NULL,
  fee_recipient     TEXT NOT NULL,
  expiry            INTEGER,
  status            TEXT NOT NULL    -- active, countered, accepted, declined, expired, cancelled
)

negotiation_events (
  event_id          TEXT PRIMARY KEY,
  root_offer_id     TEXT NOT NULL,
  event_type        TEXT NOT NULL,   -- counteroffer, accept, decline, cancel
  event_op_id       TEXT NOT NULL,
  actor             TEXT NOT NULL,
  ts                INTEGER,
  block_height      INTEGER NOT NULL
)

-- Collection state
collection_state (
  collection_id     TEXT PRIMARY KEY,
  slug              TEXT UNIQUE NOT NULL,
  name              TEXT NOT NULL,
  creator_address   TEXT NOT NULL,
  type              TEXT NOT NULL,
  supply            TEXT,
  supply_locked     BOOLEAN,
  royalty_bps       TEXT,
  royalty_address   TEXT,
  current_head_id   TEXT NOT NULL,   -- latest collection-update or root
  requires_vote     BOOLEAN NOT NULL DEFAULT FALSE
)
```

---

## 11. API Surface

### Core endpoints every ÐMP indexer SHOULD expose:

```text
# Market state
GET /listings?status=active&collection_id=:id&seller=:addr
GET /listing/:inscription_id
GET /auctions?status=active&collection_id=:id
GET /auction/:auction_id
GET /bids?inscription_id=:id&status=active
GET /offers?target_seller=:addr&status=active
GET /offers/:offer_id/thread

# Negotiation
GET /inscription/:id/negotiations

# Collections
GET /collection/:slug
GET /collections?creator_address=:addr

# Provenance
GET /provenance/:inscription_id    -- full chain with gap flags

# Settlement / activity
GET /settlements?inscription_id=:id
GET /activity?from_block=:n&limit=:n    -- delta feed (sniper/aggregator use case)

# Policy
GET /policy/fees                   -- current indexer-enforced fee thresholds
```

### Delta feed format (for sniper / aggregator)

```json
{
  "from_block": 5000000,
  "to_block": 5000010,
  "events": [
    {
      "type": "list",
      "block_height": 5000001,
      "tx_index": 3,
      "inscription_id": "abc...i0",
      "seller": "D8mZ...",
      "price": "500000000",
      "listing_type": "fixed_price"
    },
    {
      "type": "settle",
      "block_height": 5000005,
      "inscription_id": "abc...i0",
      "buyer": "DRPLk...",
      "price": "500000000",
      "settlement_txid": "9f8e..."
    }
  ]
}
```

---

## 12. Reorg Handling

### 12.1 Savepoint-based (wonky-dogeord style, recommended)

- Create a DB savepoint every `SAVEPOINT_INTERVAL` (10) blocks near chain tip.
- Keep up to `MAX_SAVEPOINTS` (5) savepoints = ~50 block rollback depth.
- On reorg detected: restore to the oldest savepoint covering the fork point.
- Re-index from that height.

```text
on_new_tip(new_tip):
  fork_point = find_common_ancestor(current_tip, new_tip)

  if fork_point.height < oldest_savepoint.height:
    raise UnrecoverableReorg (manual intervention required)

  restore_savepoint_at(fork_point.height)
  re_index_from(fork_point.height + 1, new_tip)

  current_tip = new_tip
```

### 12.2 Reorg safety invariants

- Never mutate the immutable audit log (`intents` table). Append compensating rollback events.
- Recompute `provenance_gap` flags during rollback — do not patch them directly.
- All provisional (mempool) state MUST be fully retractable without savepoints.
- After reorg recovery, state MUST be identical to a fresh replay from the fork point.

---

## 13. Provenance Gap Detection

```text
on_utxo_spend(spend_txid, inscription_id):
  has_dmp_path = (
    find_valid_settle(inscription_id, spend_txid) is not None
    or find_valid_transfer(inscription_id, spend_txid) is not None
  )

  if not has_dmp_path:
    set provenance_gap = true
    set provenance_gap_from_txid = spend_txid
    append provenance_gap_event to audit log

on_valid_transfer_op(transfer_op):
  if provenance_gap and provenance_gap_from_txid == transfer_op.transfer_txid:
    set provenance_gap = false
    append provenance_restoration_event to audit log
```

### ÐMP Verified badge rules

Show **ÐMP Verified** only when ALL are true:

- `provenance_gap = false` for the current lineage.
- Latest relevant intent passes all MUST rules.
- Ownership path reconstructible from valid ÐMP intents + on-chain spends.

Show **Provenance Broken** when ANY is true:

- `provenance_gap = true` (unresolved).
- Required settle/transfer missing for an ownership-changing spend.

---

## 14. Compliance Checklist

### Universal

- [ ] Reject malformed JSON.
- [ ] Ignore unknown fields (never error on them).
- [ ] Accept `v: "1.0"` and `v: "1.0"`. Skip unrecognized versions.
- [ ] `chain` field, if present, validated against expected network.

### Ownership verification

- [ ] Seller authorization uses address-match against indexer UTXO state (NOT UTXO spend).
- [ ] Controlling seller for negotiation responses is the current UTXO owner at response block height.

### list and auction

- [ ] Only one active list per inscription; latest by canonical ordering wins.
- [ ] `auction_mode` validated when auction context is present.
- [ ] `no_early_accept` prevents pre-expiry settlement.
- [ ] `seller_can_accept_early` permits pre-expiry settlement by seller.

### bid

- [ ] `list_id` backref validated when present (must reference active listing).
- [ ] Expired bids are inactive and ineligible for settlement.

### settle

- [ ] Settlement tx verified against Dogecoin node (not just inscription content).
- [ ] Inscription transferred to buyer in settlement tx.
- [ ] Seller payment >= price.
- [ ] Royalty outputs match claimed royalty_paid (>= floor formula).
- [ ] Confirmation depth >= 6 before marking final.
- [ ] Double-settle prevention: second settle for same list_id/auction_id is rejected.
- [ ] `platform_fee` outputs verified when present.

### cancel

- [ ] Cancel authorization verified (UTXO-based or sig-based).
- [ ] v1.0 cancel ops require `canceller` field.
- [ ] Cancel is idempotent on already-terminal intents.

### offer and anti-spam

- [ ] `offer_target_type` validated.
- [ ] `offer_fee` required and > 0.
- [ ] `fee_recipient` required.
- [ ] Sub-threshold offers filterable/deprioritizable by policy.
- [ ] Expired offers are inactive and ineligible for acceptance.

### seller responses

- [ ] `counteroffer`/`accept`/`decline` reference active, non-expired offer/counteroffer.
- [ ] Only current UTXO owner can issue responses.
- [ ] Terminal negotiation branches cannot be re-accepted.

### transfer

- [ ] `transfer_txid` confirmed >= 6 blocks.
- [ ] `from_address` / `to_address` match on-chain reality.
- [ ] Valid transfer closes provenance_gap from `transfer_txid`.

### collections

- [ ] Creator signature verified.
- [ ] `signed_list` signature verified in `explicit` mode.
- [ ] Collection defaults applied as policy hints only.
- [ ] Slug format validated (`^[a-z0-9-]+$`, max 64 chars).

### reorg behavior

- [ ] All ÐMP state transitions fully revertible (savepoint or replay).
- [ ] Provenance_gap flags recomputed deterministically on rollback.

---

## 15. Common Implementation Pitfalls

- **Wrong UTXO verification**: Checking if "list tx spends inscription UTXO" — this is incorrect
  for Dogenals. ÐMP list ops are new inscriptions. Use address-match.
- **Accepting mempool settlements as final**: Always wait for >= 6 confirmations.
- **Not checking expiry at settle time**: Expiry must be checked at the settle op's block time,
  not the bid inscription time.
- **Multiple active lists**: Allowing more than one active list per inscription.
- **Ignoring double-settle**: Not enforcing first-valid-settle-wins for the same listing.
- **Anonymous cancel acceptance**: Not verifying cancel authorization (UTXO or sig).
- **Not treating unknown fields as safe**: Any unknown field MUST be silently ignored.
- **Treating `sig_msg` as authoritative**: Always recompute canonical JSON independently.
- **Not handling reorgs**: Failing to roll back ÐMP state on chain reorganizations.
- **Trusting inscription content for settle**: Settlement validity depends on the actual DOGE tx.

---

## 16. Compliance Declaration

Implementations passing all checklist items above may self-declare:

```
ÐMP-compliant implementation of specification v1.0
```
