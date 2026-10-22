<!-- markdownlint-disable MD024 -->
# ÐMP v2 — Compact Signed Orders

Version: `"2"` (Draft, prototype-tested on regtest only)
Extends: ÐMP v1.0 (`spec.md`). v1 ops are unchanged unless stated here.
Status: Pre-launch draft. Nothing in this document has been exercised on mainnet.

## 1. Goal

A v2 `list` inscription carries everything needed to fill the order: the seller's
`SIGHASH_SINGLE|ANYONECANPAY` signature, the public key, the dog outpoint, the price, the payout
address and the declared fee terms. Every indexer rebuilds the **same canonical seller PSDT**
byte-for-byte from the order plus the dog's parent transaction from **its own node**. No venue,
listing server or peer indexer is ever asked for a PSDT.

Keywords MUST, SHOULD, MAY are as in RFC 2119.

## 2. Version and compatibility

- `v` MUST be the string `"2"`. An op with `v:"2"` is processed only by the rules here.
- v2 defines `op:"list"` and `op:"cancel"`. Any other op with `v:"2"` MUST be ignored.
- `psdt_hash` (v1 hash-only list) is venue-dependent by design and MUST NOT appear in a v2 list.
  A v2 list containing `psdt_hash` is INVALID.
- A v1 `list` MUST NOT supersede an active (`listed`) v2 order for the same inscription.
- v1 hardening adopted with v2 (applies to v1 `list` with an embedded `psdt`): the indexer MUST verify
  the PSDT's partial signature against the dog prevout in `non_witness_utxo` (P2PKH, `hash160(pubkey)`
  equal to the prevout's key hash, legacy sighash). Without this, any party can inscribe a
  junk-signature PSDT naming someone else's dog.

## 3. Chain values

`chain` is REQUIRED in v2 and MUST match the indexer's network.

| `chain`             | P2PKH version | P2SH version |
|---------------------|---------------|--------------|
| `dogecoin`          | `0x1e`        | `0x16`       |
| `dogecoin-testnet`  | `0x71`        | `0xc4`       |
| `dogecoin-regtest`  | `0x6f`        | `0xc4`       |

Regtest and testnet share address prefixes; `chain` is what tells them apart. Addresses
(`pay_to`, `royalty_to`, `listing_to`) MUST be base58check P2PKH or P2SH for that chain.

## 4. `list` order (JSON)

```json
{"p":"dmp","v":"2","op":"list","chain":"dogecoin-regtest",
 "inscription_id":"<txid>i<n>","utxo":"<txid>:<vout>","price":"10000000000",
 "pay_to":"<address>","pubkey":"<66 hex>","sig":"<DER hex>83",
 "fees":{"royalty_bps":"500","royalty_to":"<address>","market_bps":"200","listing_to":"<address>"},
 "ts":1792632460,"expiry":1792718860}
```

| field | type | rule |
|---|---|---|
| `p` | string | `"dmp"` |
| `v` | string | `"2"` |
| `op` | string | `"list"` |
| `chain` | string | §3 |
| `inscription_id` | string | the listed inscription, `<64 hex>i<n>` |
| `utxo` | string | `<64 lowercase hex txid>:<vout>`, vout canonical decimal. The outpoint currently holding the dog |
| `price` | string | koinu, `^[1-9][0-9]*$`, ≤ 2^64−1. Gross price the buyer pays (seller net + fees) |
| `pay_to` | string | seller payout address (§3). MAY differ from the owner address |
| `pubkey` | string | 33-byte compressed SEC1 key, 66 lowercase hex |
| `sig` | string | lowercase hex: strict-DER (BIP66) ECDSA signature, **low-S**, followed by hashtype byte `0x83` |
| `fees` | object | OPTIONAL. Keys below; absent = no fees |
| `fees.royalty_bps` | string | decimal `0..2500`. REQUIRED with `royalty_to` when > 0 |
| `fees.royalty_to` | string | address |
| `fees.market_bps` | string | decimal `0..2000` |
| `fees.listing_to` | string | listing-venue fee address. Absent ⇒ the whole market fee goes to the settlement venue |
| `fees.listing_share_bps` | string | decimal `0..10000`, default `"5000"` |
| `ts` | integer | Unix seconds |
| `expiry` | integer | OPTIONAL Unix seconds (§9) |
| `psdt` | string | OPTIONAL base64 of the canonical PSDT (§5.3). If present it MUST equal the rebuild byte-for-byte |
| `asig` | string | OPTIONAL signed-message authorship (§7.2): base64 of 65 bytes. Lets any inscriber publish the order |

- Caps are **rejections**, not clamps: `royalty_bps > 2500` or `market_bps > 2000` ⇒ INVALID.
- Emitters SHOULD use the key order shown and omit zero/default fee keys; parsers MUST accept any order.
- Unknown fields are ignored (v1 §3.2).
- JSON Schema: `schemas/list-v2.schema.json`.

### 4.1 Fee split (integer math, floor)

```
royalty    = royalty_to ? floor(price · royalty_bps / 10000) : 0
market     = floor(price · market_bps / 10000)
listing    = (listing_to and market > 0) ? floor(market · listing_share_bps / 10000) : 0
settlement = market − listing
net        = price − royalty − market          (the amount the seller signs)
```

`net` MUST be ≥ 100000 koinu (hard dust); otherwise the order is INVALID. Same math as
`collaborative-fees.md` §4.

## 5. Canonical template

### 5.1 Unsigned transaction (pinned)

```
version   2 (int32 LE)            locktime 0
in[0]     prevout 00…00 (32 zero bytes) : 0   scriptSig empty   sequence 0xfffffffe   (buyer placeholder)
in[1]     prevout utxo.txid : utxo.vout       scriptSig empty   sequence 0xffffffff   (dog)
out[0]    100000 koinu → scriptPubKey(pay_to)                                         (placeholder)
out[1]    net koinu    → scriptPubKey(pay_to)                                         (signed)
```

This is exactly dojak `buildListingPSDT`'s layout with `out[1] = net`.

### 5.2 Signature

`sig` signs the **legacy** (pre-segwit) signature hash of `in[1]` with hashtype `0x83`
(`SIGHASH_SINGLE|SIGHASH_ANYONECANPAY`) and `scriptCode = OP_DUP OP_HASH160 <hash160(pubkey)>
OP_EQUALVERIFY OP_CHECKSIG`. Concretely, the digest is `SHA256d` of: version ‖ 1 input
(`in[1]` with scriptCode) ‖ 2 outputs (`out[0]` blanked to value `0xffffffffffffffff` and empty
script, then `out[1]`) ‖ locktime ‖ `0x83000000`.

The digest commits to the dog outpoint, the dog's sequence, the output count (hence index 1),
`out[1]`, version and locktime. It does **not** commit to `in[0]`, `out[0]`, any other input or
output, or the `fees`/`chain`/`ts`/`expiry` JSON fields. `in[0]`/`out[0]` are pinned only so every
implementation produces identical PSDT bytes.

Because `out[1]` exists, the Dogecoin `SIGHASH_SINGLE` out-of-range bug (digest = 1) cannot apply.

### 5.3 Canonical PSDT bytes

```
"psbt" 0xff
global:  {0x00: unsigned tx (§5.1, empty scriptSigs)}                          0x00
in[0]:   (no keys)                                                             0x00
in[1]:   {0x00: non_witness_utxo = full parent tx of utxo.txid}
         {0x02 ‖ pubkey: sig}            (DER ‖ 0x83, as in the order)
         {0x03: 0x83000000}                                                    0x00
out[0]:  (no keys)                                                             0x00
out[1]:  (no keys)                                                             0x00
```

Keys appear in ascending key-type order; nothing else is present (no global version, no xpubs,
no proprietary keys). The PSDT is a pure function of `(order, parent tx)`.

## 6. Validation (indexer)

An indexer processing a v2 `list` revealed in block `B` MUST check, in order, and reject (no state
change) on the first failure:

1. Static: §4 types, caps, `chain` = network, `psdt_hash` absent, `net ≥ 100000`, strict DER, low-S,
   hashtype `0x83`, pubkey on curve.
2. The indexer's own state places `inscription_id` at `utxo` (current outpoint).
3. The dog's current owner key hash equals `hash160(pubkey)`, and the parent tx output `utxo.vout`
   is exactly P2PKH(`hash160(pubkey)`). v2 orders require a P2PKH dog owner.
4. `sig` verifies (§5.2).
5. **Authorization** (§7): if `asig` is present it MUST verify for `pubkey` (§7.2) — a failing
   `asig` is a rejection, with no fallback to reveal authorship. If `asig` is absent, the list
   inscription's reveal MUST be authored by `pubkey` (§7.1).
6. `|ts − nTime(B)| ≤ 7200`.
7. `expiry`, if present, `> nTime(B)`.
8. If `psdt` is present it equals the §5.3 rebuild byte-for-byte.

A valid v2 list supersedes any earlier listing record for that inscription (the owner signed it).

**Time base.** v2 uses block header `nTime` for `ts` and `expiry` (not MTP). Every indexer has it
without reading 11 prior headers, and it is deterministic per block. This deviates from v1 MUST-102,
which prefers MTP.

## 7. Authorization

The SINGLE|ACP signature (§5.2) does not cover `fees`, `listing_to`, `royalty_to`, `ts` or `expiry`.
Without an extra rule anyone could copy a live order, swap `listing_to`/`royalty_to` (keeping the same
bps, so `net` and `sig` are unchanged), and re-inscribe it to supersede the seller's terms. A v2
`list` or `cancel` is therefore accepted only if it is authorized by the order key in one of two ways:

| | how | who may inscribe |
|---|---|---|
| §7.1 reveal authorship | reveal tx signed by `pubkey` | only the key holder |
| §7.2 `asig` | signed-message signature over the whole canonical op | anyone (relayer, inscription service, venue) |

**Rule.** If the op contains an `asig` key it MUST verify per §7.2, otherwise the op is INVALID
(indexers MUST NOT fall back to §7.1 — a broken `asig` is evidence of tampering). If `asig` is
absent, §7.1 MUST hold.

### 7.1 Reveal authorship

The reveal transaction has an input whose scriptSig ends `<sig> <redeem>` where `sig`'s last byte is
`0x01` (`SIGHASH_ALL`) and `redeem` begins `<33-byte pubkey> OP_CHECKSIGVERIFY` with that pubkey equal
to the order's `pubkey`. This is the doginals P2SH lock used by dojak's inscriber. Consensus has already
checked that signature, so the indexer only pattern-matches.

### 7.2 `asig` (signed canonical op)

**Canonical serialization `C(op)`.** Take the op's parsed JSON object, remove the top-level keys
`asig` and `psdt` (`psdt` is derived data, checked separately by §6.8), and serialize:

- object → `{` + members joined by `,` + `}`; member = `C(key)` `:` `C(value)`; members sorted by
  key in ascending **byte** order; this applies at every nesting level (e.g. inside `fees`);
- string → `"` + the raw characters + `"`. Every string (keys included) MUST consist only of bytes
  `0x20..0x7E` excluding `"` (0x22) and `\` (0x5C), so no escaping ever occurs;
- integer → canonical decimal, no sign, no leading zeros, range `0..2^53−1`;
- no whitespace anywhere.

Any other value (array, float, negative, boolean, null, or a forbidden character) makes `asig`
INVALID. All defined v2 fields already satisfy these rules. Unknown fields are covered too, so a
relayer cannot add or alter any field. JSON with duplicate keys MUST NOT be signed; parsers keep the
last occurrence (prototype behaviour of serde_json / `JSON.parse` / Python `json`).

**Message and digest.**

```
M      = "dmp-v2-asig:" ‖ C(op)                        (ASCII)
digest = SHA256d( varstr("Dogecoin Signed Message:\n") ‖ varstr(M) )
```

`varstr` is a Bitcoin CompactSize length followed by the bytes. The magic string is 25 bytes, so the
digest input starts `0x19`. This is exactly the digest Dogecoin Core's `signmessage` produces, so
`verifymessage <P2PKH(pubkey)> <asig> <M>` on any Core node is an independent check (Core does not
enforce low-S; dmp does).

**Encoding.** `asig` = standard base64 (with padding, canonical) of 65 bytes `header ‖ r ‖ s`, where
`header = 31 + recid` (`31..34`, compressed key), `r` and `s` are 32-byte big-endian, and `s ≤ n/2`
(low-S).

**Verification.** Decode (65 bytes, canonical base64, header `31..34`, `0 < r,s < n`, low-S); compute
`digest` over `C(op)`; ECDSA-verify `(r,s)` against the order `pubkey`; and require that recovering
with `recid` yields `pubkey` (keeps `asig` interchangeable with Core). Any failure ⇒ INVALID.

**Which key.** For `list`, the op's own `pubkey`. For `cancel`, the `pubkey` of the listing that
`list_id` names (the stored order).

**What it covers.** Everything an attacker could profitably change: `fees.*`, `pay_to`, `price`,
`ts`, `expiry`, `inscription_id`, `utxo`, `sig` and `chain`. Copying an `asig` onto another order
(another dog, another outpoint, other fees) fails because those fields are in `M`. A signed cancel
covers `list_id`, so it cannot be redirected. Re-inscribing an identical, valid op is harmless: it
is the seller's own terms (and is a no-op if it is already the active listing).

**Size.** `asig` adds 98 bytes to the body (`,"asig":"<88 base64 chars>"`).

## 8. Fill, settlement and compliance

- **Fill.** A transaction is a fill of an open order iff `input[1].prevout == utxo` and
  `output[1] == template out[1]` (value and script), and the dog lands with a new owner other than
  the order key. Any other spend of `utxo` is a **cancel-by-move**.
- **State.** `listed → settle_pending` (on fill) `→ settled` (fill has ≥ 6 confirmations).
  The pending record's seller amount is `net` to `pay_to`.
- **Compliance flags** are recorded on the fill. They **never** invalidate a sale:
  - `seller_paid_ok`: the fill rule holds.
  - `royalty_ok`: `null` if no royalty is owed, else (sum paid to `royalty_to`, excluding output 1) ≥ `royalty`.
  - `listing_fee_ok`: same for `listing_to` / `listing`.
  - `settlement_fee_ok`: `null` unless the fill carries a venue tag and `settlement > 0`; then the
    sum paid to the tagged venue script ≥ `settlement`.
  - `fee_split_ok`: `seller_paid_ok` and no flag is `false`.
  - `after_cancel`, `after_expiry`: the fill happened after a signed cancel / after expiry.
- **Venue tag.** The buyer-side venue SHOULD add one output
  `OP_RETURN PUSH("dmp2") PUSH(<settlement venue scriptPubKey>)`, value 0.
- **Why flags, not rules.** Under `SIGHASH_SINGLE|ANYONECANPAY` the buyer chooses every other input
  and output. Royalty and venue fees cannot be enforced by the seller's signature, so indexers
  report them. The seller signs `net`; buyer-side venues add the fee outputs.

## 9. Cancel and expiry

- **Cancel-by-move (authoritative).** Spending `utxo` other than by a fill cancels the order
  (`cancel_kind:"moved"`). The signature can never be used again because its outpoint is gone.
  A replay of the old order is INVALID by §6.2.
- **Cancel inscription (advisory).**
  `{"p":"dmp","v":"2","op":"cancel","list_id":"<list inscription id>"}`, optionally with `"asig"`
  (§7.2, signed by the listing's order key, so any inscriber may publish it). Valid only if
  authorized by the order key (§7) and `list_id` is the current list for that inscription (not
  superseded).
  The order becomes `cancelled` (`cancel_kind:"inscription"`). Venues MUST NOT serve or build fills
  for it. The signature remains valid on-chain until the dog moves, so a later fill is still
  recorded, flagged `after_cancel`. Sellers who need certainty MUST cancel by moving.
- **Expiry.** At the start of the first block with `nTime ≥ expiry`, an open order becomes
  `expired`. Venues MUST NOT serve it. A later fill is recorded, flagged `after_expiry`.

## 10. Reorgs

All v2 state is a function of the chain. When a block is disconnected, indexers MUST revert every v2
effect of that block: listings created (the record disappears if the list inscription is
orphaned), fills (`settle_pending → listed`, buyer/compliance cleared), cancels, expiries, and the
dog's owner/outpoint. Reconnected blocks are re-validated from scratch (including the `ts` window
against the new block). An implementation MUST keep per-block undo data for at least as many blocks
as its settlement depth (6).

## 11. Serving (informative)

dogex exposes `GET /api/dmp/v2/psdt/{listed or list id}` → `{psbtBase64, psbtHex, sha256, status, …}`
built from its own DB and its own node (`getrawtransaction` for the parent). It returns 409 for
orders that are not `listed`. `POST /api/dmp/buy/prepare` with no `sellerPsbtBase64` rebuilds
locally and uses the indexed fee terms; only the settlement venue comes from the caller.

## 12. Optional enforced-royalty variant (informative)

Under SINGLE|ANYONECANPAY no seller-side construction can force a public buyer to pay a royalty.
Tested on regtest:

- **Seller-signed second pair (does not work).** A seller carrier coin at input 2 signed
  SINGLE|ACP to a royalty output 2: the buyer just omits the pair. The dog's signature still
  verifies and the sale goes through.
- **Buyer-bound order (works).** The seller signs the dog input `SIGHASH_ALL|ANYONECANPAY` (`0x81`)
  over the full output set `[lead→buyer, dog→buyer, seller net, royalty, listing fee, settlement fee]`.
  Buyer inputs stay open, but every output is pinned. Redirecting, dropping or folding the royalty
  fails consensus (`mandatory-script-verify-flag-failed`).
  Tradeoffs: the order names one buyer and the exact lead-coin value (interactive, RFQ-style; not a
  public listing). The buyer must fund the pinned outputs exactly, because there is no change output,
  which needs a prep tx. The order is larger (~780 B JSON with pinned outputs). Fee terms are bound
  by consensus, so §7 authorship is not needed for them. A v2 indexer would treat it as a separate
  `mode:"enforced"`. This is not implemented in dogex.

## 13. Security notes

- Signatures MUST be low-S and strict DER so the rebuilt PSDT bytes are unique.
- `chain` is not covered by `sig` (it is by `asig`). Cross-chain replay is prevented by the outpoint (txids differ per chain).
- Two buyers can race for one order. The first confirmed fill wins and the other is a double-spend.
- The parent tx comes from the indexer's own node. With `-txindex` off, Dogecoin Core 1.14 still
  serves the tx while the dog output is unspent, which is always the case for an open order.
- The order JSON sits in the reveal **scriptSig** (the doginals envelope), not witness data, so its
  size is paid at full weight. Measured on regtest (JSON body bytes): 532 no fees; 682 with royalty +
  market + `listing_to` (reveal tx 918 B); 702 + `expiry`; 780 + `asig`; 800 with fees + `expiry` +
  `asig`; 1258–1408 with an embedded `psdt`. For comparison, v1 with an embedded PSDT is 1059 (reveal 1306 B)
  and v1 `psdt_hash`-only is 412.

## 14. Conformance vectors

`vectors/dmp_v2_vectors.json`: `valid[]` (order, parent tx, canonical PSDT hex, sighash, fill tx,
fill txid, `fee_split_ok`; for `asig` cases also `asig_canonical`, `asig_message`, `asig_digest`,
`asig_address`), `invalid[]` (order, parent tx, reason) and `cancel[]` (signed cancel, order pubkey,
`valid`). An implementation conforms if it reproduces every `psdt_hex`, `sighash`, `fill_txid`,
`asig_canonical` and `asig_digest`, accepts every valid case and rejects every invalid case.
The `asig-*` invalid cases all carry a valid `sig`; only §7.2 rejects them. `reference/dmp_v2_reconstruct.py`
is an independent (non-dogex, non-dojak) implementation that checks every vector, including its own
pubkey recovery for `asig`.
