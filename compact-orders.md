<!-- markdownlint-disable MD024 -->
# ÐMP 1.0 — Compact Signed Orders

Protocol: ÐMP 1.0 (pre-launch; prototype-tested on regtest only)
Wire marker: `"v":"2"` (the compact-order format field; see §2)
Extends: [spec.md](spec.md). Its ops are unchanged unless stated here.
Status: Pre-launch. Nothing in this document has been exercised on mainnet.
Formerly published as `spec-v2.md` ("ÐMP v2"). The old path stays as a redirect, and all section
numbers are unchanged.

## 1. Goal

A compact `list` inscription carries everything needed to fill the order: the seller's
`SIGHASH_SINGLE|ANYONECANPAY` signature, the public key, the dog outpoint, the price, the payout
address and the declared fee terms. Every indexer rebuilds the **same canonical seller PSDT**
byte-for-byte from the order plus the dog's parent transaction from **its own node**. No venue,
listing server or peer indexer is ever asked for a PSDT.

Keywords MUST, SHOULD, MAY are as in RFC 2119.

## 2. Version and compatibility

**Naming.** ÐMP has not launched, so its first release is **ÐMP 1.0**. Fixed-price `list` and
`cancel` in ÐMP 1.0 are the compact signed orders defined here. Earlier drafts of this document
called them "ÐMP v2"; that was a working name only, and there is no ÐMP 2.

**Wire marker.** The `v` field value `"2"` is the on-chain marker of the compact-order format. It is
kept byte-for-byte so that orders inscribed during development, the vectors and the schemas stay valid.
It means "ÐMP 1.0 compact order", not "protocol version 2". The other ops in [spec.md](spec.md)
(`bid`, `offer`, `auction`, `collection`, …) keep `"v":"1.0"` and are also part of ÐMP 1.0.
File names that contain `v2` (`schemas/*-v2.schema.json`, `vectors/dmp_v2_*.json`,
`reference/dmp_v2_reconstruct.py`, `EXAMPLES/v2/`) and the `asig` prefix (§7.2) keep their names for
the same reason.

- `v` MUST be the string `"2"`. An op with `v:"2"` is processed only by the rules here.
- This document defines `op:"list"` and `op:"cancel"`. Any other op with `v:"2"` MUST be ignored.
- **Draft list format (pre-1.0).** A `list` op without `v:"2"` (the [spec.md](spec.md) §4.1 list,
  with an embedded `psdt` or a `psdt_hash`; formerly "v1 list") is a pre-release draft format. It is
  **not part of ÐMP 1.0**, and the only such lists on chain are the four mainnet test listings in §15.
  - Wallets and venues MUST NOT create new draft lists. New listings MUST be compact orders.
  - ÐMP 1.0 indexers SHOULD ignore draft lists. An indexer MAY keep indexing them for compatibility.
    If it does, it MUST apply the draft-list hardening below and the §15 classification.
- `psdt_hash` (draft hash-only list) is venue-dependent by design and MUST NOT appear in a compact list.
  A compact list containing `psdt_hash` is INVALID.
- A draft `list` MUST NOT supersede an active (`listed`) compact order for the same inscription.
- Draft-list hardening (applies to an indexer that indexes draft `list` ops with an embedded `psdt`):
  the indexer MUST verify the PSDT's partial signature(s) against the dog prevout in `non_witness_utxo`, legacy sighash,
  hashtype `0x83`, low-S:
  - P2PKH prevout: one signer, `hash160(pubkey)` equal to the prevout's key hash, scriptCode = the prevout.
  - P2SH prevout: the PSDT input MUST carry `redeem_script` (key `0x04`) with `hash160(redeem_script)`
    equal to the prevout's script hash; `redeem_script` MUST be a §5.4 template (draft lists also accept 65-byte
    uncompressed keys in it); every partial signature MUST be by a key of the script and verify with
    scriptCode = `redeem_script`; and there MUST be at least `m` of them (1 for P2PK).
  - The signed dog input MUST NOT be input 0. A PSDT that signs the dog at input 0 always returns the
    dog's sat to the locked output 0, so no fill can deliver it. Such a list is INVALID
    (`postage_unsafe`, §15).
  - A draft-list fill is a sale only if the dog lands (§8.1) with an owner other than the seller. A payment
    to the seller is not enough on its own.
  - Any other prevout type is INVALID.

  Without this, any party can inscribe a junk-signature PSDT naming someone else's dog. (The first
  version of this check required P2PKH and rejected every P2SH-held dog; that was a regression.)

## 3. Chain values

`chain` is REQUIRED in compact orders and MUST match the indexer's network.

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
| `pubkey` | string | P2PKH dog: 33-byte compressed SEC1 key, 66 lowercase hex. MUST be absent when `redeem_script` is present |
| `redeem_script` | string | OPTIONAL. P2SH dog: lowercase hex of the redeem script, one of the §5.4 templates. Replaces `pubkey` |
| `sig` | string | lowercase hex: strict-DER (BIP66) ECDSA signature, **low-S**, followed by hashtype byte `0x83`. Used by P2PKH and single-key P2SH orders. MUST be absent on multisig orders |
| `sigs` | array | multisig P2SH orders only (REQUIRED there): exactly `m` signatures, each formatted like `sig`, in redeem-script key order (§5.4) |
| `fees` | object | OPTIONAL. Keys below; absent = no fees |
| `fees.royalty_bps` | string | decimal `0..2500`. REQUIRED with `royalty_to` when > 0 |
| `fees.royalty_to` | string | address |
| `fees.market_bps` | string | decimal `0..2000` |
| `fees.listing_to` | string | listing-venue fee address. Absent ⇒ the whole market fee goes to the settlement venue |
| `fees.listing_share_bps` | string | decimal `0..10000`, default `"5000"` |
| `ts` | integer | Unix seconds |
| `expiry` | integer | OPTIONAL Unix seconds (§9) |
| `psdt` | string | OPTIONAL base64 of the canonical PSDT (§5.3). If present it MUST equal the rebuild byte-for-byte |
| `asig` | string | OPTIONAL signed-message authorship (§7.2): base64 of 65 bytes. Lets any inscriber publish the order. Single-key orders only |
| `asigs` | array | multisig orders only (REQUIRED there, §7): exactly `m` `asig` strings by distinct script keys, in key order |

Exactly one owner shape is valid:

| dog held by | owner field | signature field | authorization (§7) |
|---|---|---|---|
| P2PKH | `pubkey` | `sig` | `asig` or reveal authorship |
| P2SH `<pk> OP_CHECKSIG` | `redeem_script` | `sig` | `asig` (by `pk`) or reveal authorship by `pk` |
| P2SH m-of-n `OP_CHECKMULTISIG` | `redeem_script` | `sigs` (m) | `asigs` (m), REQUIRED |

Any other combination (`pubkey` with `redeem_script`, `sig` on a multisig order, `sigs`/`asigs` on a
single-key order, `asig` on a multisig order, a wrong count) is INVALID.

- Caps are **rejections**, not clamps: `royalty_bps > 2500` or `market_bps > 2000` ⇒ INVALID.
- Emitters SHOULD use the key order shown and omit zero/default fee keys; parsers MUST accept any order.
- Unknown fields are ignored (spec.md §3.2).
- A `list` with top-level `items` and no top-level `inscription_id` is a batch (§16). A body with both is a single order, and `items` is an ignored unknown key.
- JSON Schema: `schemas/list-v2.schema.json`. Batch lists: `schemas/list-batch.schema.json`.

### 4.2 Duplicate keys

A compact-order op (`list` or `cancel`) whose body contains the same object key twice, at any depth (top level,
`fees`, …), is INVALID. Keys are compared after JSON string unescaping, so `"pay_to"` and
`"pay\u005fto"` collide. Parsers disagree on duplicates (most keep the last, some the first, some
error), so without this rule two indexers could read different `pay_to` or `fees` from the same bytes.
The SINGLE|ACP signature does not cover `fees` or `pay_to`'s position in the JSON, and `asig` signs the
canonical re-serialization, which has already collapsed the duplicate. This rule applies to compact-order ops only,
including every object inside a batch `items` array (§16.6 B1). Parsing of spec.md ops is unchanged.

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
OP_EQUALVERIFY OP_CHECKSIG` (P2PKH dog) or `scriptCode = redeem_script` (P2SH dog, §5.4; every
signature in `sigs` signs this same digest). Concretely, the digest is `SHA256d` of: version ‖ 1 input
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
         {0x02 ‖ pubkey: sig}            (DER ‖ 0x83, as in the order; one per signer)
         {0x03: 0x83000000}
         {0x04: redeem_script}           (P2SH dogs only)                      0x00
out[0]:  (no keys)                                                             0x00
out[1]:  (no keys)                                                             0x00
```

Keys appear in ascending key-type order, and `0x02` entries in ascending order of the 33 key bytes
(BIP174 key order; for P2PKH and single-key P2SH there is one). Nothing else is present (no global
version, no xpubs, no proprietary keys, no `0x01`). The PSDT is a pure function of `(order, parent tx)`.

### 5.4 P2SH dogs

A dog held on `P2SH(h)` lists with `redeem_script` instead of `pubkey`. The rules:

1. **Hash.** `hash160(redeem_script) = h`, and the parent tx output `utxo.vout` is exactly
   `OP_HASH160 PUSH20(h) OP_EQUAL`. The indexer's owner hash for the dog is `h`.
2. **Templates.** `redeem_script` MUST be byte-for-byte one of:

   | template | bytes |
   |---|---|
   | single-key P2PK | `0x21 <33-byte pk> 0xac` (`<pk> OP_CHECKSIG`) |
   | m-of-n multisig | `OP_m (0x21 <33-byte pk_i>)×n OP_n 0xae` (`OP_CHECKMULTISIG`), `OP_m`/`OP_n` = `0x50+m`/`0x50+n` |

   with `1 ≤ m ≤ n ≤ 15`, every key a compressed SEC1 point on the curve, all keys distinct, and
   nothing before or after. Anything else (uncompressed keys, `OP_CHECKMULTISIGVERIFY`, hash locks,
   timelocks, `n > 15`, a trailing opcode, a non-minimal push) is INVALID as
   `unsupported redeem_script`. `n ≤ 15` is Dogecoin Core's standard P2SH limit (`MAX_P2SH_SIGOPS`);
   a 1-of-1 multisig is allowed (it is not the P2PK template). The script is ≤ 520 bytes by
   construction (15-of-15 = 513).
3. **Signatures.** Each signature signs §5.2 with `scriptCode = redeem_script`, hashtype `0x83`,
   strict DER, low-S. P2PK: `sig` verifies for `pk`. Multisig: `sigs` holds exactly `m` signatures and is
   matched the way `OP_CHECKMULTISIG` matches: walk the keys in script order with a cursor; each
   signature, in array order, advances the cursor past keys until one verifies it (that key is its
   signer, and the cursor moves past it); if the keys run out, INVALID. So signatures come from `m`
   distinct keys and are in key order, which is exactly what consensus accepts.
4. **Canonical scriptSig.** The fill's input 1 scriptSig is rebuilt identically by every implementation:

   ```
   P2PKH         PUSH(sig ‖ 83) PUSH(pubkey)
   P2SH P2PK     PUSH(sig ‖ 83) PUSH(redeem_script)
   P2SH m-of-n   OP_0 PUSH(sigs[0] ‖ 83) … PUSH(sigs[m−1] ‖ 83) PUSH(redeem_script)
   ```

   (Each signature already ends in its hashtype byte, `83` for compact list orders. The construction
   does not depend on the hashtype.) `PUSH(x)` is the minimal push: `len(x)` as one byte if ≤ 75, else
   `0x4c len` (PUSHDATA1) if ≤ 255, else `0x4d len16le` (PUSHDATA2). `OP_0` is the CHECKMULTISIG
   dummy (`0x00`; NULLDUMMY). The scriptSig MUST be ≤ 1650 bytes (Core `MAX_SCRIPT_SIG_SIZE`); the
   templates guarantee it (15-of-15 with 73-byte DER = 1627). This is what bitcoinjs `finalizeInput`
   and Core `signrawtransaction` produce for these scripts.
5. **PSDT.** §5.3 with one `0x02` entry per signer and `0x04 = redeem_script`.

**Why only these templates.** They are the shapes wallets actually use for P2SH custody (Core
`addmultisigaddress`, `createmultisig`, and P2SH-wrapped single keys). Every rule above is decidable
without an interpreter, the scriptSig is unique, and the buy side can price it exactly. Arbitrary
scripts would need a full script engine in every indexer and venue for no known use.

## 6. Validation (indexer)

An indexer processing a compact `list` revealed in block `B` MUST check, in order, and reject (no state
change) on the first failure:

1. Static: §4 types, caps, `chain` = network, `psdt_hash` absent, `net ≥ 100000`, strict DER, low-S,
   hashtype `0x83`, pubkey on curve.
2. The indexer's own state places `inscription_id` at `utxo` (current outpoint).
3. The dog's current owner hash equals `hash160(pubkey)` (P2PKH) or `hash160(redeem_script)` (P2SH),
   and the parent tx output `utxo.vout` is exactly P2PKH(`hash160(pubkey)`) or
   P2SH(`hash160(redeem_script)`) respectively (§5.4). Other dog scripts cannot list as a compact order.
4. `sig` / `sigs` verify (§5.2, §5.4).
5. **Authorization** (§7): if `asig`/`asigs` is present it MUST verify (§7.2) — a failing one is a
   rejection, with no fallback to reveal authorship. If absent, the list inscription's reveal MUST be
   authored by the order key (§7.1); multisig orders cannot use this path and are INVALID without `asigs`.
6. `|ts − nTime(B)| ≤ 7200`.
7. `expiry`, if present, `> nTime(B)`.
8. If `psdt` is present it equals the §5.3 rebuild byte-for-byte.
9. **Newer `ts` wins** (§6.1).

(§4.2 duplicate keys are checked before step 1.) A list that passes every step supersedes any earlier
listing record for that inscription.

A batch `list` (§16) is not checked by steps 5, 6 and 7. §16.6 B4, B5 and B6 replace those three steps
for the batch as a whole. Each item is then checked as the single order it resolves to.

### 6.1 Ordering: newer `ts` wins

Let `cur` be the indexer's current listing record for `inscription_id` if it is a compact order, whatever
its status (`listed`, `cancelled`, `expired`). A batch item uses the batch's one `ts` as its `ts` (§16.8).
A new valid compact `list` `new` replaces `cur` only if

- `new.utxo ≠ cur.utxo` (the dog has moved since `cur`; `cur`'s outpoint is gone), or
- `new.ts > cur.ts` (strictly).

Otherwise `new` is INVALID: `ts not newer than the indexed order for this outpoint`.

- **Same outpoint ⇒ same signer.** The owner of `utxo` is fixed, so `cur` and `new` were both signed by
  that key (or, for P2SH, satisfy that script). The rule only decides which of the seller's own orders is current.
- **Tie-break.** Ops are applied in chain order: block height, then transaction index in the block,
  then inscription index in the transaction. With equal `ts` the one applied first stays. Re-inscribing
  an identical order is therefore always a no-op rejection.
- **Why.** An `asig` order (§7.2) can be inscribed by anyone. Without ordering, a third party could
  re-inscribe an older order the seller has replaced (e.g. a lower price) and revert it, or revive a
  cancelled order by re-inscribing it. With this rule the seller's latest order stays current, and a
  cancel (§9) is final for every order with `ts ≤` the cancelled one.
- **Re-pricing on the same outpoint.** Sellers MUST use a strictly larger `ts` than their previous
  order. `ts` is bounded by §6 step 6 (`±7200 s` of `nTime`), so a re-price normally uses the current time.
- Draft-list records (no compact order) are not compared; a valid compact list replaces them as before.

**Time base.** Compact orders use block header `nTime` for `ts` and `expiry` (not MTP). Every indexer has it
without reading 11 prior headers, and it is deterministic per block. This deviates from spec.md MUST-102,
which prefers MTP.

## 7. Authorization

The SINGLE|ACP signature (§5.2) does not cover `fees`, `listing_to`, `royalty_to`, `ts` or `expiry`.
Without an extra rule anyone could copy a live order, swap `listing_to`/`royalty_to` (keeping the same
bps, so `net` and `sig` are unchanged), and re-inscribe it to supersede the seller's terms. A compact
`list` or `cancel` is therefore accepted only if it is authorized by the order's owner:

| order | how | who may inscribe |
|---|---|---|
| single-key (P2PKH `pubkey`, P2SH `<pk> OP_CHECKSIG`) | §7.1 reveal tx signed by the key | only the key holder |
| single-key | §7.2 `asig` by the key | anyone (relayer, inscription service, venue) |
| m-of-n multisig | §7.2 `asigs`: `m` signatures by distinct script keys | anyone |

The order key of a single-key order is `pubkey`, or `pk` from the P2PK `redeem_script`.

**Rule.** If the op contains an `asig` or `asigs` key it MUST verify per §7.2, otherwise the op is
INVALID (indexers MUST NOT fall back to §7.1 — a broken `asig` is evidence of tampering). If neither is
present, §7.1 MUST hold, which a multisig order can never satisfy.

**Why m of n for multisig.** The alternative, "any one key of the script", is simpler but lets a single
co-signer act for the group on everything the spending signatures do not cover: cancel the order,
supersede it with a newer `ts`, or rewrite `fees`/`royalty_to`/`listing_to` (a fresh op re-using the
group's `sigs`, which do not cover fees, plus that one key's `asig`). The script owners chose `m` keys
to move the dog; listing terms get the same threshold. It costs no extra round: the co-signers who
produce `sigs` sign the canonical op at the same time. Reveal authorship is excluded because a
doginals reveal is signed by one key.

### 7.1 Reveal authorship

The reveal transaction has an input whose scriptSig ends `<sig> <redeem>` where `sig`'s last byte is
`0x01` (`SIGHASH_ALL`) and `redeem` begins `<33-byte pubkey> OP_CHECKSIGVERIFY` with that pubkey equal
to the order's `pubkey`. This is the doginals P2SH lock used by dojak's inscriber. Consensus has already
checked that signature, so the indexer only pattern-matches.

### 7.2 `asig` (signed canonical op)

**Canonical serialization `C(op)`.** Take the op's parsed JSON object, remove the top-level keys
`asig`, `asigs` and `psdt` (`psdt` is derived data, checked separately by §6.8), and serialize:

- object → `{` + members joined by `,` + `}`; member = `C(key)` `:` `C(value)`; members sorted by
  key in ascending **byte** order; this applies at every nesting level (e.g. inside `fees`);
- string → `"` + the raw characters + `"`. Every string (keys included) MUST consist only of bytes
  `0x20..0x7E` excluding `"` (0x22) and `\` (0x5C), so no escaping ever occurs;
- integer → canonical decimal, no sign, no leading zeros, range `0..2^53−1`;
- array → `[` + `C(element)` in array order joined by `,` + `]` (e.g. `sigs`);
- no whitespace anywhere.

Any other value (float, negative, boolean, null, or a forbidden character) makes `asig`
INVALID. All defined compact-order fields already satisfy these rules. Unknown fields are covered too, so a
relayer cannot add or alter any field. JSON with duplicate keys MUST NOT be signed; parsers keep the
last occurrence (prototype behaviour of serde_json / `JSON.parse` / Python `json`).

**Message and digest.**

```
M      = "dmp-v2-asig:" ‖ C(op)                        (ASCII)
digest = SHA256d( varstr("Dogecoin Signed Message:\n") ‖ varstr(M) )
```

The prefix `dmp-v2-asig:` is a fixed wire constant of ÐMP 1.0. Its `v2` is historical and MUST NOT be
changed, since every existing `asig` signs it.

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

**Which key.** For `list`, the op's own order key (`pubkey`, or the P2PK `redeem_script` key). For
`cancel`, the order key of the listing that `list_id` names (the stored order).

**`asigs` (multisig).** An array of exactly `m` strings, each encoded and checked like `asig`, all over
the same digest (`C(op)` excludes `asigs`, so co-signers sign independently). Each entry's recovered
key MUST be a key of the stored or listed `redeem_script`, at a strictly greater script position than
the previous entry's (distinct keys, script order), and MUST verify for that key. Any failure ⇒
INVALID. `verifymessage` checks each entry against `P2PKH(key)`, so it works as an independent check
here as well. A cancel of a multisig order uses `asigs` the same way.

**What it covers.** Everything an attacker could profitably change: `fees.*`, `pay_to`, `price`,
`ts`, `expiry`, `inscription_id`, `utxo`, `sig` and `chain`. Copying an `asig` onto another order
(another dog, another outpoint, other fees) fails because those fields are in `M`. A signed cancel
covers `list_id`, so it cannot be redirected. Re-inscribing an identical, valid op is harmless: it
is the seller's own terms (and is a no-op if it is already the active listing).

**Size.** `asig` adds 98 bytes to the body (`,"asig":"<88 base64 chars>"`); `asigs` adds
`10 + 91·m` (`,"asigs":[…]`).

## 8. Fill, settlement and compliance

### 8.1 Inscription location (normative)

Every rule in this spec that says "the dog is at", "the owner of" or "the dog lands" means the location
computed here. It is the ord sat-flow rule as Doginals indexers apply it (ord / wonky-ord; dogesoft).
The indexer computes it only from transactions in the chain it has connected. It MUST NOT consult any
external service for validity.

- **Inscription ID.** `<reveal txid>i<n>`, where `n` is the index of the inscription among those
  revealed in the transaction (0 for a standard doginal). For a multi-part doginal (the body continues
  across chained reveal transactions), the ID is the **first** part's txid with `i0`.
- **Genesis location.** For a single-transaction reveal, the location is `<reveal txid>:0:0`: the first
  sat of the reveal's input 0 flows to output 0. For a multi-part reveal, it is
  `<completing reveal txid>:0:0`, the transaction that carries the final part. A chain that never
  completes produces no inscription. If output 0 cannot receive the sat (for example, all outputs are
  zero-value), the inscription is lost to fee from genesis.
- **Sat flow (FIFO).** For a transaction spending an outpoint that holds an inscription at offset `o`
  within input `i`, let `abs = (Σ value of inputs 0..i−1) + o`. Walk the outputs in order with a
  running start `s`. Zero-value outputs (OP_RETURN) are skipped and receive nothing. The inscription
  moves to the first output `j` with `s ≤ abs < s + value(out[j])`, at offset `abs − s`. Then
  `location = <txid>:<j>:<abs − s>`.
- **Lost to fee.** If `abs ≥ Σ output values`, the sat goes to the miner. The inscription is no longer
  owned by any script that a ÐMP rule can match. An indexer MAY follow it into the coinbase as ord does;
  for ÐMP it counts as "not landed with a new owner".
- **Several inscriptions on one UTXO.** Each one keeps its own offset and is moved independently by the
  rule above. A compact order's `utxo` names the outpoint, and `inscription_id` names which inscription on it is
  listed. An order is still the seller's signature over the whole outpoint, so a fill moves every
  inscription on it.
- **Owner.** The owner of a location is the scriptPubKey of the output it sits on. ÐMP compares
  script hashes: `hash160(pubkey)` for P2PKH, `hash160(redeem_script)` for P2SH.
- **Input values.** Computing `abs` needs every earlier input's value. Indexers MUST obtain prevout
  values from chain data they hold: their own UTXO set, undo data, or a txindex node. When a value is
  unavailable, the indexer MUST halt that block rather than guess. Treating a missing value as 0 moves
  inscriptions to the wrong output.

Vectors: `vectors/dmp_v2_state_vectors.json` → `location` (11 cases: non-zero offset 1,000,000,
an offset inside a later input, two inscriptions on one UTXO split and together, lost to fee and its
boundary, the last sat, a zero-value output skipped) and `genesis` (single part, 3-part, incomplete).

### 8.2 Fill

- **Is it a fill.** A transaction is a fill of an open order iff `input[1].prevout == utxo` and
  `output[1] == template out[1]` (value and script). These are the only two things the seller's
  `SIGHASH_SINGLE|ANYONECANPAY` signature binds. Validation MUST NOT depend on anything else in the
  layout: not the number of inputs or outputs, not which output carries the dog, and not the
  input 0 or output 0 values.
- **Sale or cancel.** A fill is a **sale** iff the dog, located by §8.1, lands on an output whose owner
  (§8.1) is not the order owner, meaning neither `hash160(pubkey)` nor `hash160(redeem_script)`. If the dog
  lands back with the order owner, or is lost to fee, the spend is a **cancel-by-move**
  (`cancel_kind:"moved"`). The buyer is the address of the output where the dog landed.
- **Any spend that is not a fill** is a cancel-by-move.
- **Canonical layout (what venues SHOULD build).**

  ```
  in[0]  buyer coin, value ≥ net (its value decides where the dog lands)
  in[1]  dog (seller sig, 0x83)
  in[2…] buyer payment / fee coins
  out[0] buyer change = value(in[0]) − net     (so out[0] + out[1] end exactly where the dog sat starts)
  out[1] signed: net → pay_to
  out[2] dog → buyer, value = dog postage
  out[3…] royalty, listing, settlement outputs, optional OP_RETURN, buyer change
  ```

  With `value(out[0]) + value(out[1]) = value(in[0])`, the dog's `abs = value(in[0])` is the first sat
  of `out[2]`, at offset 0. This is dogex's `postage_safe_plan` and the spec.md "postage-safe fill".
- **Other valid layouts.** Any layout that meets the fill rule is a valid fill, and §8.1 decides
  whether it is a sale. Example: a venue uses a 1,000,000-koinu buyer coin as `in[0]` and pays
  `out[0] = 1,000,000 + postage` to the buyer. The dog lands on `out[0]` at offset 1,000,000, and the
  buyer owns it. This is the diggydoge layout. Wallets SHOULD keep the dog at offset 0 (the canonical
  layout), because some wallets spend high-offset sats by accident.
- **State.** `listed → settle_pending` (on a sale) `→ settled`. A fill is `settled` once it has at
  least 6 confirmations, i.e. `tip − fill_height + 1 ≥ 6`. The pending record's seller amount is `net`
  to `pay_to`.
- **Compliance flags** are recorded on the fill. They **never** invalidate a sale:
  - `seller_paid_ok`: the fill rule holds.
  - `royalty_ok`: `null` if no royalty is owed, else (sum paid to `royalty_to`, excluding output 1) ≥ `royalty`.
  - `listing_fee_ok`: same for `listing_to` / `listing`.
  - `settlement_fee_ok`: `null` unless the fill carries a `dmp2` venue tag (§8.3) and `settlement > 0`;
    then the sum paid to the tagged venue script ≥ `settlement`.
  - `fee_split_ok`: `seller_paid_ok` and no flag is `false`.
  - `after_cancel`, `after_expiry`: the fill happened after a signed cancel / after expiry.
- **Why flags, not rules.** Under `SIGHASH_SINGLE|ANYONECANPAY` the buyer chooses every other input
  and output. Royalty and venue fees cannot be enforced by the seller's signature, so indexers
  report them. The seller signs `net`; buyer-side venues add the fee outputs.

Vectors: `fill_layout` (canonical `out[2]` with and without fees, diggydoge `out[0]` at offset
1,000,000 with a venue's own JSON OP_RETURN and with fees unpaid, dog back to the seller, altered `out[1]` (a transfer,
not a fill), dog lost to fee, dog on `in[2]`).

### 8.3 OP_RETURN and the venue tag

Dogecoin Core relays at most **one** OP_RETURN output per transaction, up to 80 bytes of data. So:

- The `dmp2` venue tag `OP_RETURN PUSH("dmp2") PUSH(<settlement venue scriptPubKey>)` (value 0) is
  **OPTIONAL**. It only drives `settlement_fee_ok`.
- ÐMP defines no venue- or brand-specific tags. A venue MAY write its own OP_RETURN (for example a JSON
  object) instead of the `dmp2` tag, as long as it does not conflict with the one-OP_RETURN rule: the
  fill stays valid and `settlement_fee_ok` is `null`. Venues MUST NOT add a second OP_RETURN.
- Indexers read **only the first** OP_RETURN output. They MUST NOT reject a fill for having an
  OP_RETURN of any kind, or several of them (a non-standard but mined transaction is still a fill).
- Informative: indexers MAY record `op_return_kind` on the fill. It is `"dmp2"` for a venue tag, and
  `"json:<k>"` when the data parses as a JSON object, with `<k>` its lexicographically smallest key
  (e.g. `"json:mkt"` for `{"mkt":…}`). It is `"other"` for anything else and absent/`null` when there is no OP_RETURN.

- **Open question (tag-free venue check).** Without a `dmp2` tag an indexer cannot tell which output, if
  any, is the settlement-venue fee: the order names no venue address, and any extra output may be buyer
  change. ÐMP 1.0 therefore reports `settlement_fee_ok: null` for untagged fills and MUST NOT guess.
  Checking untagged fills would need either a venue address field on the order (a format change) or an
  aggregate "unattributed outputs" figure; neither is part of 1.0.

### 8.4 Dust and fees (guidance)

These are Dogecoin Core relay defaults, not ÐMP validity rules. A mined fill is a fill whatever it pays.

- Hard dust limit 0.001 DOGE (100000 koinu): outputs below it are not relayed. `net ≥ 100000` is
  already a §6 rule.
- Soft dust 0.01 DOGE (1000000 koinu): each output below it adds 0.01 DOGE to the required fee.
  Venues SHOULD keep royalty, listing and settlement outputs ≥ 0.01 DOGE or merge them into change.
- Fee: Dogecoin Core 1.14.4+ recommends at least 0.01 DOGE/kB. dogex and the reference fills pay
  1 DOGE/kB for margin. A typical canonical fill is 400–700 bytes.
- Sellers SHOULD list with `net ≥ 1 DOGE`.
- Postage: dogs SHOULD keep 100000 koinu (0.001 DOGE) postage; the canonical template's `out[0]`
  placeholder uses that value.

## 9. Cancel and expiry

- **Cancel-by-move (authoritative).** Spending `utxo` other than by a fill cancels the order
  (`cancel_kind:"moved"`). The signature can never be used again because its outpoint is gone.
  A replay of the old order is INVALID by §6 step 2 (the indexer no longer places the dog at `utxo`).
- **Cancel inscription (advisory).**
  `{"p":"dmp","v":"2","op":"cancel","list_id":"<list inscription id>"}`, optionally with `"asig"`
  (§7.2, signed by the listing's order key, so any inscriber may publish it; multisig listings need
  `"asigs"`, m of n). Valid only if
  authorized by the order key (§7) and `list_id` is the current list for that inscription (not
  superseded).
  Cancels carry no `ts` and are not ordered by §6.1. They are bound to `list_id` instead: a cancel
  naming a superseded `list_id` is INVALID, and a cancel of an already-cancelled order changes nothing.
  Re-inscribing the cancelled order (or any older one for the same `utxo`) is INVALID by §6.1, so a
  cancel cannot be undone by a third party. The seller re-lists with a newer `ts`.
  A batch list is cancelled with this same op (§16.10).
  The order becomes `cancelled` (`cancel_kind:"inscription"`). Venues MUST NOT serve or build fills
  for it. The signature remains valid on-chain until the dog moves, so a later fill is still
  recorded, flagged `after_cancel`. Sellers who need certainty MUST cancel by moving.
- **Expiry.** At the start of the first block with `nTime ≥ expiry`, an open order becomes
  `expired`. Venues MUST NOT serve it. A later fill is recorded, flagged `after_expiry`.

## 10. Reorgs

All compact-order state is a function of the chain. When a block is disconnected, indexers MUST revert every compact-order
effect of that block: listings created (the record disappears if the list inscription is
orphaned), fills (`settle_pending → listed`, buyer/compliance cleared), cancels, expiries, and the
dog's owner/outpoint. Reconnected blocks are re-validated from scratch (including the `ts` window
against the new block). An implementation MUST keep per-block undo data for at least as many blocks
as its settlement depth (6).

## 11. Serving (informative)

dogex exposes `GET /api/dmp/psdt/{listed or list id}` (old path `/api/dmp/v2/psdt/…` kept as an alias) → `{psbtBase64, psbtHex, sha256, status, …}`
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
  by consensus, so §7 authorship is not needed for them. A ÐMP 1.0 indexer would treat it as a separate
  `mode:"enforced"`. This is not implemented in dogex.
- **P2SH dogs in a future enforced mode.** §5.4 is written so it carries over unchanged: the templates,
  the hash check, the `OP_CHECKMULTISIG` signature walk, the canonical scriptSig (which takes each
  signature with whatever hashtype byte it carries) and PSDT key `0x04`. Only the hashtype (`0x81`)
  and the pinned output set would differ. `asigs` (m of n) would stay REQUIRED for multisig. Consensus
  would bind the fee terms there, but cancels and supersession are still not covered by the spending
  signatures, so one co-signer must not be able to act alone.

## 13. Security notes

- Signatures MUST be low-S and strict DER so the rebuilt PSDT bytes are unique.
- `chain` is not covered by `sig` (it is by `asig`). Cross-chain replay is prevented by the outpoint (txids differ per chain).
- Two buyers can race for one order. The first confirmed fill wins and the other is a double-spend.
- The parent tx comes from the indexer's own node. With `-txindex` off, Dogecoin Core 1.14 still
  serves the tx while the dog output is unspent, which is always the case for an open order.
- The order JSON sits in the reveal **scriptSig** (the doginals envelope), not witness data, so its
  size is paid at full weight. Measured on regtest (JSON body bytes): 532 no fees; 682 with royalty +
  market + `listing_to` (reveal tx 918 B); 702 + `expiry`; 780 + `asig`; 800 with fees + `expiry` +
  `asig`; 1258–1408 with an embedded `psdt`. For comparison, a draft list with an embedded PSDT is 1059 (reveal 1306 B)
  and a draft `psdt_hash`-only list is 412.
- Batch lists (§16.12), chain bytes for N dogs. A batch of one is not allowed. The 4 KB soft cap does not apply; the cap is 32768 B.

  | N | singles | batch, shared price | batch, per-item price |
  |---|---|---|---|
  | 2 | 2,120 | 1,389 | 1,410 |
  | 10 | 10,600 | 4,461 | 4,650 |
  | 50 | 53,000 | 19,553 | 20,850 |

- P2SH sizes (vectors, bytes):

  | order | JSON body | canonical PSDT | dog scriptSig in the fill |
  |---|---|---|---|
  | P2PKH, no fees | 531 | 376 | 106–107 |
  | P2PKH, fees + `asig` | 824 | 376 | 106–107 |
  | P2SH P2PK, fees + `asig` | 815 | 412 | 108 |
  | P2SH 2-of-3, fees + `asigs` | 1200 | 586 | 253 |
  | P2SH 2-of-3, `asigs` + `psdt` (no fees) | 1820 | 589 | 252 |
  | P2SH 15-of-15 (bound) | — | — | 1627 |

  A P2SH P2PK body is about the size of a P2PKH one (`redeem_script` is 70 hex chars vs 66). Each
  extra multisig key adds 68 hex chars to `redeem_script`; each extra required signature adds about
  147 (`sigs`) + 91 (`asigs`) chars. The buyer pays for the larger dog scriptSig (2-of-3: +147 bytes
  over P2PKH); the dogex buy builder prices it.
- P2SH owners are hash-only on the index (`owner_hash160` holds the script hash); `redeem_script`
  is revealed only in the order. Indexers MUST render P2SH owners as P2SH addresses.

## 14. Conformance vectors

`vectors/dmp_v2_vectors.json`: `valid[]` (order, parent tx, canonical PSDT hex, sighash, fill tx,
fill txid, `fee_split_ok`; for `asig` cases also `asig_canonical`, `asig_message`, `asig_digest`,
`asig_address`; P2SH cases also `dog_script_sig_hex`, `dog_script_sig_bytes` and
`asig_addresses`), `invalid[]` (order, parent tx, reason; `duplicate-key` also carries the raw
`order_json`, which MUST be parsed as given) and `cancel[]` (signed cancel, order pubkey,
`valid`), and `ordering[]` (`current`, `new`, expected `supersedes`, §6.1). An implementation conforms
if it reproduces every `psdt_hex`, `sighash`, `fill_txid`, `dog_script_sig_hex`, `asig_canonical` and `asig_digest`, accepts
every valid case, rejects every invalid case and matches every `supersedes`.
The `asig-*` invalid cases all carry a valid `sig`; only §7.2 rejects them. `reference/dmp_v2_reconstruct.py`
is an independent (non-dogex, non-dojak) implementation that checks every vector, including its own
pubkey recovery for `asig`.

Batch lists (§16.16) are `vectors/dmp_v2_batch_vectors.json`, checked by `reference/dmp_v2_batch.py`
(batch `asig`, per-item PSDT, item rejects, ordering, fill of one item, advisory cancel).

`vectors/dmp_v2_state_vectors.json` covers what single-order vectors cannot: `location[]` and
`genesis[]` (§8.1: inputs, inscriptions with offsets, outputs → expected location or `null` for lost),
`fill_layout[]` (§8.2: a raw fill tx against an order → `is_fill`, `outcome` sale | cancelled_moved,
dog location, `op_return_kind`), `reveal_authorship[]` (§7.1: raw reveal tx → authorized or not), and
`state[]` (§6.1, §9, §10: a sequence of blocks, each with `nTime`, list, cancel, fill and move events,
and `reorg` steps that disconnect blocks; the expected listing record after each step). The state is a
pure fold over the connected chain, so a reorg is replayed by disconnecting and reconnecting blocks.
An implementation conforms if it reproduces every expectation. Check them with
`python3 reference/dmp_v2_reconstruct.py state vectors/dmp_v2_state_vectors.json`.

## 15. Draft lists already on mainnet

Four draft-format `list` ops (pre-1.0 test listings) were inscribed on Dogecoin mainnet:

| list inscription | block | dog | price | seller | form |
|---|---|---|---|---|---|
| `bd75ee39…c2d4i0` | 6417318 | `315fdeb6…80edi0` | 420 DOGE | `DDMg44HLnLCHsjdviuxfLsqvUJUG7Rmrat` | embedded `psdt`, dog at input 0 |
| `54f111c3…6236i0` | 6421388 | `169ff297…c3a2i0` | 42 DOGE | `DDMg44HLnLCHsjdviuxfLsqvUJUG7Rmrat` | embedded `psdt`, dog at input 0 |
| `ee6fb2d8…0a42i0` | 6424225 | `12547783…92f4i0` | 1 DOGE | `DLJRAQxPQj9xSzmwvcRP1QzHAS9CJPo2RU` | `psdt_hash`, 3% royalty, 1% market fee |
| `65992ab5…cd6ci0` | 6424299 | `d7a47274…9ffdi0` | 1 DOGE | `DNVASM9WAz1Tc4VGE4ifCwAmv4fnREwSKk` | `psdt_hash`, 3% royalty, 1% market fee |

(The full IDs are in [IMPLEMENTERS.md](IMPLEMENTERS.md#draft-lists-on-mainnet).)

**The two hash-only lists** (`listing_marketplace:"marketplace.dogesoft.io"`) are valid draft-list records
for an indexer that indexes draft lists (§2). The §2 draft-list hardening applies only to an embedded `psdt`, so it does not apply here. They are
venue-dependent by design: another venue cannot fill them without the off-band PSDT. Their outcome
follows the dog's location, like any draft list. A spend where the dog lands (§8.1) with a non-seller
owner and the seller is paid by the spec.md fee plan is a sale. Any other spend is cancel-by-move.

**The two embedded lists** (`listing_marketplace:"dogecoin.dog"`) predate the postage-safe rule
(`bd900e2`). Each embeds a PSDT
with **one input, the dog at input 0** (its genesis outpoint, a 100000-koinu postage coin), and
**one output**, output 0, which pays the price to the seller's own P2PKH. The `0x83` signature is
valid (strict DER, and the key hashes to the dog's prevout), but the shape is the one the spec.md
postage-safe rule forbids (spec.md §3, "Postage-safe fill"). The dog's sat sits at offset 0 of input
0, so by §8.1 it always lands in output 0, which pays the seller. No transaction that uses these
signatures can deliver the dog to a buyer. A buyer who "fills" one pays the seller and receives
nothing.

**Classification (normative).** A draft `list` whose embedded PSDT signs the dog at input 0 is
**INVALID** (`postage_unsafe`). It is never `listed`, and venues MUST NOT serve it. Both embedded
mainnet lists fall under this rule, which is defined by shape, not by ID. If either signature is ever used,
the spend is an ordinary transfer back to the seller. Nothing is listed, so nothing is cancelled and
no sale is recorded. An indexer of draft lists that settles on "the spend pays the seller ≥ price" (662f8d1
MUST-112) would record a false sale here, so such indexers MUST also require the §8.2 sale condition:
the dog lands with an owner other than the seller. The seller retires them by moving the dog or by
listing it as a compact order. Moving the dog also stops a buyer from being misled by an off-index copy of the
PSDT. These two dogs are Doginals era-1 inscriptions, so judging their current owner requires an index
built from the era-1 floor. The vectors are in `vectors/dmp_v1_psdt_vectors.json`
(`dmp_v2_reconstruct.py v1`).

## 16. Batch list orders

**Decisions (settled, no longer open):**

1. **One shared `expiry`.** Only the header carries `expiry`. Items may not (§16.4). Per-item expiry was cut for minimalism.
2. **A batch has 2 to 50 items.** A batch of one is INVALID (§16.6 B2). One order has one form, the single order.
3. **No activation height.** Batch lists ship in ÐMP 1.0 itself (§16.3). Every indexer that claims 1.0 implements this section.

### 16.1 Goal and design rule

A seller who lists N dogs today inscribes N compact `list` orders, one reveal each (about 1,060 B on
chain per order, §16.12). This section adds one inscription that carries N orders for **one owner key**, with
one authorization signature over the whole set. Header fields (`chain`, owner key, `ts`, and optional
defaults for `price`, `pay_to`, `fees`, and one shared `expiry`) are written once.

**Design rule: a batch is a transport, not a state object.** After fan-out (§16.5) an indexer holds N
ordinary single-order records. Fill (§8.2), cancel-by-move (§9), expiry, ordering (§6.1) and reorgs (§10)
act on those records exactly as on single orders. The only batch-aware pieces are the id format, the
batch-level checks, and the optional item selector on the advisory cancel. The conformance test is one
sentence: *batch validity = §16.6 batch checks, then the existing single-order validity of each resolved item.*

Everything stays layer 1. The batch carries no venue, brand or listing-server reference, and every indexer
rebuilds every item's PSDT from the chain plus its own node, as in §1.

### 16.2 Alternatives considered

| | Idea | Result |
|---|---|---|
| **A** | `op:"list"` with an `items` array and one batch `asig` | **Chosen.** Every byte an indexer needs is on chain. It reuses §5, §6, §7.2 and §8 unchanged. Smallest delta to the spec. |
| **B** | Commit to a merkle root of the N orders; publish leaves later | Rejected, see below. |
| **C** | Compact the shared fields into columns (`"ids":[…],"utxos":[…],"sigs":[…]`), or drop `inscription_id` from items | Rejected for 1.0. |
| **D** | Keep single orders, make mass-inscribing cheap (one commit tx, N reveals) | Not a substitute. Wallets can ship it today, independent of this spec. |
| **E** | A new op (`"op":"list-batch"`) | Rejected. A distinct op name adds nothing over the detection rule in §16.3 and splits the `list` family. |
| **F** | N complete orders concatenated, each with its own `asig` | Rejected. It saves only the envelope and is larger than A. |

**Why not B (merkle root).** A root is about 32 B regardless of N, but it fails the §1 requirement that
*any indexer rebuilds everything from the chain alone*. The chain would hold the root, not the prices,
payout addresses, fees or signatures. A buyer or indexer needs the leaf (price, `pay_to`, `fees`, sig) to
know that an outpoint is listed and on what terms. Leaves would have to come from a venue or peer, which
puts a listing server back in the trust path. Publishing the proof at fill time does not work either. A
depth-6 proof is about 192 B and a fill's `OP_RETURN` carries at most 80 B (§8.3). The fill's scriptSig
and outputs carry the signature, the net payout and the `pay_to`, but not `fees`, `ts` or `expiry`. So
the chain would show a sale but could not say whether it was a fill of a listing. B also does not remove
the dominant cost: each outpoint needs its own `SIGHASH_SINGLE|ANYONECANPAY` signature, 72 B (about 144 hex
chars). B shrinks the inscription to about 0.5 KB for any N, but the same leaf bytes (about 317 B per item,
72 B of it signature) must still be published somewhere before anyone can fill. On chain they cost what A
costs. Off chain they reintroduce the venue. B therefore saves nothing that matters and loses verifiability.

**Why not C.** Columnar arrays save only the repeated key names, about 34 B of a 317 B item (about 10%).
They add a length-mismatch failure mode (three arrays that must agree) and make a per-item override
awkward. Dropping `inscription_id` (66 B per item, about 21%) would force the indexer to guess which
inscription on an outpoint is meant. That is ambiguous when a UTXO holds several, and it differs from a
single order. Both can be added later as an optional compact item form (§16.14) without changing what is defined here.

**Why not D alone.** Era-1 Doginals index only `vin[0].scriptSig` (§8.1), so N inscriptions need N reveals.
D leaves N bodies of about 800 B, N reveals of about 236 B fixed overhead, and N `asig`s. It saves only
the N commit transactions. It is complementary: a wallet that lists singles SHOULD still use one
commit with N outputs. It is not what a user means by "list these 10 in one action".

### 16.3 Detection and compatibility

A `p:"dmp"`, `v:"2"`, `op:"list"` body is a **batch** iff the top-level key `items` is present **and** the
top-level key `inscription_id` is absent. A body with both is a single order, and `items` is an ignored
unknown key (§2). A body with neither is a malformed single order.

- A batch MUST NOT carry the top-level keys `inscription_id`, `utxo`, `sig`, `sigs`, `psdt` or `psdt_hash`
  (INVALID, §16.6 B2).
- **Old indexers.** An indexer that implements only §4 rejects a batch with `inscription_id required`.
  It never reads a batch as a single order, so there is no mis-parse, only invisibility. The existing rule
  "ignore unknown fields" is not used, because it cannot distinguish a batch from a malformed single.
- **No activation height (decided).** ÐMP 1.0 is pre-launch (§1 status), so batches are part of 1.0 itself.
  Every indexer that implements 1.0 MUST implement this section. There is no flag height and no earlier
  batch-less 1.0 to stay compatible with.
- `v` stays `"2"` and `op` stays `"list"`. No new marker.

### 16.4 Wire format

```json
{
  "p": "dmp", "v": "2", "op": "list", "chain": "dogecoin",
  "pubkey": "<66 hex>",
  "pay_to": "<default payout address>",
  "price": "<default price, koinu string>",
  "fees": { "…": "default fee terms, §4" },
  "ts": 1792632460,
  "expiry": 1792718860,
  "items": [
    { "inscription_id": "<txid>i<n>", "utxo": "<txid>:<vout>", "sig": "<DER+83 hex>",
      "price": "…", "pay_to": "…", "fees": { } }
  ],
  "asig": "<base64>"
}
```

**Header** (every key at top level; types and caps as §4):

| key | req | meaning |
|---|---|---|
| `p`,`v`,`op`,`chain` | yes | `"dmp"`, `"2"`, `"list"`, network (§3). |
| `pubkey` \| `redeem_script` | one of | the single owner of **all** items (§5.4 shapes). Mixed owners are out of scope in v1. |
| `ts` | yes | integer, one value for the whole batch (§6.1, §16.8). |
| `price`, `pay_to`, `fees` | no | defaults used by an item that does not set its own. |
| `expiry` | no | integer, one value for every item (§16.8). Items cannot override it. |
| `asig` \| `asigs` | **yes** | authorization (§16.7). `asig` for a single-key owner, `asigs` (m of n) for multisig. |
| `items` | yes | array of 2 to 50 objects. |

**Item**:

| key | req | meaning |
|---|---|---|
| `inscription_id`, `utxo` | yes | as §4. The dog and its current outpoint. |
| `sig` \| `sigs` | one of | this item's `SIGHASH_SINGLE\|ANYONECANPAY` signature (§5.2), or the m signatures for a multisig owner (§5.4). Which one is fixed by the header's owner shape. |
| `price`, `pay_to`, `fees` | no | override the header value for this item (§16.5). |

Items carry **no** `ts`, `expiry`, `pubkey`, `redeem_script`, `chain`, `p`, `v`, `op`, `asig`, `asigs`, `psdt`,
`psdt_hash` or `items`. Such an item is rejected (§16.6 I1). That keeps a silently ignored "different owner" in one item
from looking like a mixed-owner listing.

A batch has an id like any inscription: `<txid>i<n>` (for a multi-part reveal, the first part's txid, §8.1).

### 16.5 Resolution and fan-out

Item `n` (0-based position in the signed `items` array) resolves to a **single order** `R_n`:

- from the header: `p`, `v`, `op`, `chain`, the owner key, `ts`;
- from the item: `inscription_id`, `utxo`, `sig` or `sigs`;
- `price = item.price ?? header.price`, `pay_to = item.pay_to ?? header.pay_to`, and
  `fees = item.fees ?? header.fees` (which may stay absent);
- `expiry = header.expiry` for every item (which may be absent).

An override **replaces** the header value; there is no merging. `fees` is replaced as a whole object, and
`"fees":{}` on an item means no fees for that item. An item with no `price` and no header `price`, or no
`pay_to` and no header `pay_to`, is rejected (§16.6 I2).

`R_n` has list id **`<batch id>:<n>`**. `n` is canonical decimal in `0..49` and is **never renumbered**
when an item is rejected. Every other layer sees `R_n` as an order whose authorization is "the batch `asig`
verified" (§16.7). Its PSDT is the §5.3 rebuild of `R_n`, so item `n`'s template, `pay_to` and net are exactly
those of a single order with the same resolved fields.

### 16.6 Validation

A batch revealed in block `B` is checked in two tiers. (`B` is the block of the completing reveal for a
multi-part body, §8.1.)

**Batch checks.** Failure makes the **whole batch INVALID**, with no item state changed. Checked in order:

- **B1** §4.2 duplicate keys, at any depth, including inside every item.
- **B2** Shape: §16.3 detection, forbidden top-level keys absent, `items` is an array of 2 to 50 objects
  (a batch of one is INVALID), and the body is at most `MAX_BATCH_BYTES` = 32768 B (§16.11).
- **B3** Header syntax: `chain` is the network; exactly one owner key of a valid shape (§5.4); header
  `price`, `pay_to`, `fees`, `expiry`, `ts` well-formed by §4 (`ts` and `expiry` integers in `0..2^53−1`);
  `asig` present for single-key owners, `asigs` (m distinct, in key order) for multisig, neither otherwise.
- **B4** Authorization: the `asig`/`asigs` verifies over `C(batch)` (§16.7). The reveal-authorship path (§7.1)
  is **not** available to batches, and a missing signature is INVALID.
- **B5** `|ts − nTime(B)| ≤ 7200` (§6 step 6).
- **B6** `expiry`, if present, `> nTime(B)` (§6 step 7). Otherwise the batch is INVALID, because the one shared
  expiry has already passed for every item.

Auth runs before any item check, so a forged batch costs one signature verification, not 50.

**Item checks.** Failure rejects **only that item**, with no effect on the others. For each item `n`, in
this order (cheap and state-only first, signature last):

- **I1** The item is an object with no reserved key (§16.4).
- **I2** Static (§6 step 1 on `R_n`): §4 types and caps, the resolved `price` and `pay_to` exist,
  `net ≥ 100000` (§4.1), `sig`/`sigs` strict DER, low-S, hashtype `0x83`, matching the owner shape.
- **I3** Uniqueness: no other item in this batch has the same `utxo` string or the same `inscription_id`
  string (§16.7).
- **I4** The indexer's state places `inscription_id` at `utxo` (§6 step 2).
- **I5** The dog's owner hash equals the header owner's `hash160`, and the parent output script has the §5.4
  shape (§6 step 3). A dog the header key does not own is rejected here.
- **I6** `sig`/`sigs` verify against the §5.2/§5.4 template of `R_n` (§6 step 4).
- **I7** Ordering (§6.1) against the current record for that `inscription_id`.

An accepted item becomes the current listing record for its `inscription_id`, with `list_id =
<batch id>:<n>` and `auth:"batch"`. Rejected items are not recorded. Indexers SHOULD expose the per-item
reject reason (informative, §16.13).

### 16.7 Authorization, canonical form, per-item signature

**Batch signature.** §7.2 applies unchanged, with `op` = the batch body:

> `C(batch)` = the batch body with the top-level `asig` and `asigs` removed (and `psdt`, which a batch may not
> have), serialized as in §7.2: objects with members sorted by key in byte order **at every level**
> (including inside each item and inside `fees`); strings printable ASCII `0x20`–`0x7E` without `"` or `\`;
> integers canonical decimal in `0..2^53−1`; no whitespace; **arrays keep their order**.
> `M = "dmp-v2-asig:" ‖ C(batch)`. The digest and the 65-byte base64 signature are exactly §7.2.

Nothing new is defined. §7.2 already sorts keys at every level and keeps array order, so `items` serializes
deterministically as written. The signed bytes contain the `items` array, so a relayer cannot add, drop,
reorder or recombine items or change a header default. Domain separation from a single order is the
`items` key being inside the signed bytes. Any Dogecoin-Core-compatible `verifymessage` check of
`P2PKH(pubkey)`, `asig` and `M` verifies a batch. For multisig, `asigs` is m signatures over the same `M`.

**Emitting.** An emitter SHOULD write the body as `C(batch)` with `,"asig":"<base64>"` before the closing
brace. Then the signed bytes are the body bytes with that tail removed and `}` restored. Parsers MUST NOT
rely on this and MUST parse and re-serialize.

**Item order.** The array order is part of the signed bytes and is the identity of `<batch id>:<n>`. There
is no required sort. A reordered body has a different `asig` and a different set of ids, so it cannot be
confused with the original.

**What an item `sig` covers.** Exactly §5.2 for its own resolved order: the legacy sighash of input 1 of the
§5.1 template, with that item's `utxo` as the outpoint and output 1 = `net → pay_to`, hashtype `0x83`.
That commits to this outpoint, the net payout and the payout address. It does not commit to `fees`, `ts`,
`expiry`, `chain` or the other items, and the batch `asig` covers those. An item `sig` is therefore not
transferable to another outpoint, and a revealed `sig` cannot be combined with other items without the owner's `asig`.

**Duplicates inside a batch.** If two items share a `utxo` string or an `inscription_id` string, **all**
of those items are rejected (I3). The rule is symmetric: no first-wins, because "first" would depend on array
order, and the rule is evaluated on the raw strings of all items regardless of their other validity. The seller
who signed both copies gets neither, so the mistake is visible.

### 16.8 Ordering, replay, and expiry

- **One `ts` per batch.** Item `n` is compared by §6.1 with the current record for its `inscription_id`: it
  replaces it only if `utxo` differs or the batch `ts` is strictly newer. Equal `ts` means the first applied in
  chain order wins (height, tx index, inscription index; the batch is one inscription).
- **Replay across batches.** Re-inscribing an old batch is a per-item no-op wherever a newer or equal
  record exists, and it cannot revive a cancelled item (§9). Where an item's outpoint has moved, I4 rejects it.
  A batch whose `ts` is outside the window (B5) is INVALID, so the window bounds how stale a relayed batch
  can be, as for singles.
- **Batch against single.** A single order and a batch item for the same `inscription_id` compete by the
  same rule: strictly newer `ts`, or a different `utxo`.
- **One shared expiry.** Items have no `expiry` of their own. Every accepted item inherits `header.expiry`
  (none if absent) and expires at the first block with `nTime ≥ expiry` (§9). The batch holds no expiry state:
  each item's record carries the value and expires like a single order, so a fill or cancel of one item does not
  change the others. A batch whose `expiry` is not after `nTime(B)` is INVALID (B6). A seller who wants
  different lifetimes inscribes separate batches (one per lifetime, each with 2 or more items) or single orders.
- **Re-pricing.** To change one price, inscribe a single order or a new batch with a newer `ts`.

### 16.9 Fill and settlement

Unchanged, per item. A transaction is a fill of item `n` iff it is a fill of `R_n` under §8.2
(`input[1].prevout == utxo` and `output[1]` equals `R_n`'s template output 1). A **partial fill leaves every
other item listed**. Compliance flags, `after_cancel` and `after_expiry` are per item.

**Limitation (v1).** `SIGHASH_SINGLE|ANYONECANPAY` fixes the dog at input 1 and output 1 of the template
(§5.1). One transaction therefore fills one item, and there is no "buy all 10 in one tx". A multi-item fill
would need a different template and is not defined here (§16.14).

### 16.10 Cancel

- **Cancel-by-move** is unchanged and authoritative, per outpoint. A single transaction that spends several
  listed outpoints (other than as a fill) cancels all of them at once, so cancelling N items costs one
  transaction.
- **Advisory cancel** (§9) gains one optional key: `{"p":"dmp","v":"2","op":"cancel","list_id":"<batch id>",
  "items":[0,2,5],"asig":"…"}`.
  - `list_id` MUST be the plain batch inscription id. A `:<n>` suffix is INVALID.
  - `items`, if present, is a non-empty array of strictly ascending distinct integers, each `< len(batch.items)`.
    Absent means all items. An out-of-range or malformed `items` is INVALID.
  - It is authorized like any cancel (§9): `asig`/`asigs` by the batch's order key over `C(cancel)`.
  - It is INVALID if `list_id` is not a known valid batch. This rule is for a cancel of a batch. A cancel whose `list_id` is a single-order inscription id stays §9, and it MUST NOT contain `items`. For each selected index it applies only if the
    item's record is still the current record for that `inscription_id` (not superseded, not already cancelled,
    not moved). Otherwise that index is a no-op. A cancel that changes nothing is a no-op, not an error.
  - An applied cancel sets `cancelled` with `cancel_kind:"inscription"` per item. Cancelled items cannot be revived by
    re-inscribing the same batch (§16.8). Fills after cancel are recorded as `after_cancel`.
- An old indexer ignores a batch cancel (it does not know the batch), as it ignores the batch.

### 16.11 Limits

| limit | value | why |
|---|---|---|
| `MAX_ITEMS` | 50 | bounds work (one batch auth plus at most 50 item sig checks, m each for multisig), reorg-undo size and wallet signing |
| `MAX_BATCH_BYTES` | 32768 | the body as assembled from all reveal parts. A maximal single-key item is about 540 B, so 50 fit |

- **The 4 KB soft cap does not apply to batches.** spec.md "Size Guidelines" ("Bodies SHOULD stay under 4 KB",
  "SHOULD reject … larger than 4 KB") exists to deter spam. A conforming indexer MUST accept batch bodies up to
  `MAX_BATCH_BYTES` and MUST NOT apply the 4 KB rule to them. The spam budget is unchanged because cost still
  scales with bytes: about 1,060 B of chain data per listed dog for a single, about 400 B for a batch (§16.12).
- Multisig batches reach the byte cap first: each item carries m signatures (m = 3 gives about 590 B per item, so
  about 50 items still fit; m ≥ 5 does not).
- Over `MAX_ITEMS` or `MAX_BATCH_BYTES` the whole batch is INVALID. There is no "first 50".
- A body of 32768 B needs about 24 reveal parts at 1,390 B per part, plus one commit, which is 25 chained
  transactions. That stays within the default mempool ancestor limit of 25 (needs regtest, §16.14), so a batch can be relayed in one
  go.

### 16.12 Size and fee economics

Model: placeholder-length strings (34-char addresses, 72 B DER signatures, 66-hex ids, 87-char `asig`).
Single order body 792 B with `fees` + `expiry` + `asig`, which matches §13's measured 800 B (a 1% model error).
Reveal overhead is 236 B per reveal part (derived from §13: 918 B reveal for a 682 B body), plus 32 B
per commit output; multi-part bodies split at 1,390 B per part (the wallet's single-reveal cap). The part
overhead for chained reveals is an estimate to confirm on regtest.

| N | singles (N × 1,060 B) | batch, shared price | batch, per-item price | batch / singles |
|---|---|---|---|---|
| 1 | 1,060 | not allowed | not allowed | n/a (a batch of one is INVALID; it would be 1,072 B, 101%) |
| 2 | 2,120 | 1,389 | 1,410 | 66% |
| 3 | 3,180 | 1,974 | 2,016 | 62% |
| 10 | 10,600 | 4,461 | 4,650 | 42% |
| 25 | 26,500 | 10,288 | 10,792 | 41% |
| 50 | 53,000 | 19,553 | 20,850 | 37–39% |

(Body bytes: N = 3: 1,438 shared or 1,480 per-item. N = 10: 3,657 or 3,846. N = 50: 16,337 or 17,366.)

- **Marginal item:** about 317 B with a shared price, about 338 B with a per-item price (a `"price":"…"`
  member costs about 21 B), against 1,060 B per single including its reveal and commit output.
- **Fixed batch cost:** about 487 B (shared header plus one 88 B `asig`) plus 268 B per reveal part (236 B reveal
  overhead, 32 B commit output). The break-even is N = 2, the smallest allowed batch. A batch of one would cost about 12 B more than a single, which is one reason it is INVALID.
- **Worst case:** every item overriding `price`, `pay_to` and `fees` is about 539 B per item, and 50 items are
  27,087 B, still about 61% of the singles' 53,000 B.
- At a relay fee near 1 DOGE/kB, 10 listings cost about 4.5 DOGE instead of about 10.6 DOGE.
- **Floor:** each outpoint needs its own signature, 72 B. Nothing in this design (or any alternative that keeps
  the order on chain) can remove that.

### 16.13 Security considerations

- **Duplicate outpoints.** Handled by I3. The seller cannot make a duplicate mean "last wins" or "first wins".
  An indexer cannot count one signature twice.
- **Outpoints the key does not own.** Header `pubkey` is only a claim. I4/I5 require that the indexer's state
  places the dog at `utxo` and that the owner hash matches the key, per item. A batch listing dogs of other people
  has all those items rejected and gets no effect. A third party cannot list a victim's dog with the victim's
  public key, because that needs the victim's `asig` and per-item `sig`.
- **Relay and mix-and-match.** Anyone can inscribe a signed batch (it is `asig`-authorized). They cannot change
  it, take items from it into another batch (the new batch needs the owner's `asig`), or reuse an item `sig` for
  another outpoint or payout (§16.7). The `ts` window (B5) and strict ordering (§16.8) bound replay.
- **`ts` and `expiry`.** `ts` is one value, checked in the window at reveal. There is one `expiry`, so no item
  can hide a longer lifetime than the one the owner signed, and a batch whose `expiry` has passed is INVALID
  (B6). As for singles, only moving the dog gives certainty (§9).
- **Partial acceptance.** The cost of per-item rejection is that a seller can get 7 of 10 items listed.
  Wallets MUST dry-run the batch against §16.6 B5, B6 and every item against I1–I5 before signing and show the result. Indexers SHOULD report the per-item reject
  reason, and venues SHOULD show unlisted items to their seller.
- **Blind signing.** `M` is about 1.4–27 KB of ASCII. A signing UI MUST display, per item, the inscription, the
  gross price, the net payout and the payout address, derived from `M`, and SHOULD show a digest of `M`.
- **Resource use.** Bounded by §16.11. Auth is checked first (B4). Per item the state checks precede the
  signature check, so an item for a dog that is not there costs no signature verification.
- **Mass cancel.** Cancel-by-move over N outpoints is one transaction (§16.10), and the advisory batch cancel is one
  inscription. A seller can pull a whole batch quickly, and the advisory cancel remains advisory.
- **Parser divergence.** The detection rule is defined on the parsed top-level keys. §4.2 (duplicate keys) already makes `items` and
  `inscription_id` unambiguous across parsers.

### 16.14 Open questions

**Needs regtest** (cannot be settled by reading the spec):

1. **Wallet signing.** N PSBT-style signatures plus one message of up to 27 KB. Can wallets present one prompt? What
   do browser wallets' `signMessage` limits allow?
2. **Multi-part parser.** Do the era-1 envelope parsers (indexers and wallets) handle a body of about 24 chained
   parts? Does every era-1 indexer reassemble multi-part bodies (a batch above 1,390 B is invisible on one that does
   not)? Confirm the 236 B per-part overhead and the 1,390 B per-part cap.
3. **Ancestor limit.** Is the default mempool ancestor limit 25 in the node versions in use, so that a 24-part body
   plus its commit relays as one chain (§16.11)?

**Deferred (not needed for 1.0):**

4. **Which block is `B`** for a multi-part batch. This section says the block of the completing reveal, consistent with §8.1.
5. **Mixed owners.** Out of scope for v1. A later `groups` form (header per owner) can be added without changing
   what is defined here.
6. **Sweep fills** (one tx filling several items) need a template with the dog at a pinned index other than 1.
7. **Compact item form** (§16.2 C): optional later, only if the 10% to 21% saving justifies a second
   representation.
8. **Cancel selector** versus several cancels. The selector is the smallest addition that makes "cancel one of ten" a single inscription.

### 16.15 Worked examples

Every value is a placeholder: `ab…ab` key, repeated-byte `sig` strings (`30e1e1…e183`), `A…A=` for `asig`,
visibly fake addresses (valid base58 characters, invalid checksum). They validate against
`list-batch.schema.json` and do **not** verify cryptographically. The full unabbreviated bodies, the
canonical strings and digests are in [EXAMPLES/](EXAMPLES/). The wire body is compact JSON; indentation below is for display.
The same header is used by both: `chain` `dogecoin`, `pubkey` `02ab…ab`, `pay_to` `DEXAMPLEPAYADDRESS…`, `ts` 1792632460.

**(a) Three items at one shared price of 10 DOGE** (1,000,000,000 koinu), 2% market fee, shared expiry.

```json
{
  "p": "dmp", "v": "2", "op": "list", "chain": "dogecoin",
  "pubkey": "02abababababababababababababababababababababababababababababababab",
  "pay_to": "DEXAMPLEPAYADDRESSXXXXXXXXXXXXXXXX",
  "price": "1000000000",
  "fees": { "market_bps": "200", "listing_to": "DEXAMPLEMARKETADDRESSXXXXXXXXXXXXX" },
  "ts": 1792632460,
  "expiry": 1792718860,
  "items": [
    { "inscription_id": "1111…1111i0", "utxo": "aaaa…aaaa:0", "sig": "30e1e1…e183" },
    { "inscription_id": "2222…2222i0", "utxo": "bbbb…bbbb:0", "sig": "30e2e2…e283" },
    { "inscription_id": "3333…3333i0", "utxo": "cccc…cccc:1", "sig": "30e3e3…e383" }
  ],
  "asig": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
}
```

Body 1,368 B; `C(batch)` 1,270 B; `M` 1,282 B; digest = SHA256d of the signed-message framing of `M`:
`07aa4b53f28e15bc9a1d828e9f6d3dafe40565aa83a84a84473e7706962795b9` (the value an `asig` would be a
signature over; the placeholder `asig` is not one). `C(batch)` begins
`{"chain":"dogecoin","expiry":1792718860,"fees":{"listing_to":"DEXAMPLEMARKETADDRESS…","market_bps":"200"},"items":[{"inscription_id":"1111…i0","sig":"30e1e1…`
(key order `inscription_id`, `sig`, `utxo` inside items).

Fan-out: ids `<batch id>:0`, `:1`, `:2`. Every item resolves to price 1,000,000,000, market fee 20,000,000, net
980,000,000 → `DEXAMPLEPAYADDRESS…`, expiry 1792718860. For example item 0 is the single order:

```json
{ "p":"dmp","v":"2","op":"list","chain":"dogecoin",
  "pubkey":"02abab…ab","inscription_id":"1111…1111i0","utxo":"aaaa…aaaa:0",
  "price":"1000000000","pay_to":"DEXAMPLEPAYADDRESS…",
  "fees":{"market_bps":"200","listing_to":"DEXAMPLEMARKETADDRESS…"},
  "sig":"30e1e1…e183","ts":1792632460,"expiry":1792718860 }
```

**(b) Three items with per-item prices** (10, 25 and 100 DOGE), no header `price` and no `expiry`; item 1 and item 2 each override `pay_to`.

```json
{
  "p": "dmp", "v": "2", "op": "list", "chain": "dogecoin",
  "pubkey": "02abababababababababababababababababababababababababababababababab",
  "pay_to": "DEXAMPLEPAYADDRESSXXXXXXXXXXXXXXXX",
  "fees": { "market_bps": "200", "listing_to": "DEXAMPLEMARKETADDRESSXXXXXXXXXXXXX" },
  "ts": 1792632460,
  "items": [
    { "inscription_id": "1111…1111i0", "utxo": "aaaa…aaaa:0", "sig": "30e1e1…e183",
      "price": "1000000000" },
    { "inscription_id": "2222…2222i0", "utxo": "bbbb…bbbb:0", "sig": "30e2e2…e283",
      "price": "2500000000", "pay_to": "DEXAMPLEPAYADDRESSNUMBER2XXXXXXXXX" },
    { "inscription_id": "3333…3333i0", "utxo": "cccc…cccc:1", "sig": "30e3e3…e383",
      "price": "10000000000", "pay_to": "DEXAMPLEPAYADDRESSNUMBER3XXXXXXXXX" }
  ],
  "asig": "AAAA…AAAA="
}
```

Body 1,483 B; `C(batch)` 1,385 B; `M` 1,397 B; digest
`cd55017f3c11c578171446f2532b331fbd01a50c379eec0d6f2342bbd0d164c5`.

| id | price | market fee | net | `pay_to` | expiry |
|---|---|---|---|---|---|
| `<batch id>:0` | 1,000,000,000 | 20,000,000 | 980,000,000 | `DEXAMPLEPAYADDRESS…` | none |
| `<batch id>:1` | 2,500,000,000 | 50,000,000 | 2,450,000,000 | `DEXAMPLEPAYADDRESSNUMBER2…` | none |
| `<batch id>:2` | 10,000,000,000 | 200,000,000 | 9,800,000,000 | `DEXAMPLEPAYADDRESSNUMBER3…` | none |

### 16.16 Test vectors

Built, cryptographic vectors (regtest keys; not the §16.15 placeholders) are [vectors/dmp_v2_batch_vectors.json](vectors/dmp_v2_batch_vectors.json), checked by [reference/dmp_v2_batch.py](reference/dmp_v2_batch.py). A `reason` string names the check that failed. It is informative, not a wire format.

Fan-out and PSDT vectors reuse §14: an item's `sig` and PSDT are those of the equivalent resolved single order, so each batch vector can be built from an existing single-order vector plus a real `asig`.

*Valid:* shared price; per-item prices; per-item override of `price`, of `pay_to`, and of `fees` (including
`"fees":{}`); header `expiry` inherited by every item; multisig batch (`asigs`, items with `sigs`); 2 items (the minimum); 50 items;
P2SH single-key owner; one bad item (wrong owner) with the other items listed.

*Invalid (whole batch):* `items` with a top-level `inscription_id` (read as a single order); missing `asig`;
`asig` over a reordered or edited array; 1 item (a batch of one); 51 items; empty `items`; header `expiry` ≤ `nTime(B)`; `items` not an array; duplicate key inside an
item (§4.2); `ts` outside the window; body over 32768 B; top-level `utxo`/`sig`/`psdt`; reveal authorship without `asig`.

*Rejected (item only):* duplicate `utxo`, duplicate `inscription_id` (all copies rejected); no price; net below dust;
dog not at `utxo`; wrong owner; bad `sig`; reserved key in item (including `expiry` and `ts`).

*Ordering:* same-`ts` single vs batch item (first applied wins); older batch re-inscribed (no-op); newer batch for
a subset of the outpoints (those items replaced, others untouched); moved dog (I4).

*Fill and cancel:* fill of item 1 leaves 0 and 2 listed; cancel all; cancel `[1]`; cancel with index out of range
(INVALID); cancel with `:n` suffix (INVALID); consolidation spend of all outpoints cancels all; reorg of the batch block removes all its items.
