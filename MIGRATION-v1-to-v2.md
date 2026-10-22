# Migrating a v1 ÐMP implementation to v2

This is for implementers who built ÐMP before v2 compact orders merged. It lists what changed and
marks each item **must-change** or **optional**.

## Which spec you probably built against

| commit | time (PDT) | what it fixed |
|---|---|---|
| `bd900e2` | 2026-10-20 17:55 | Postage-safe fill (dog on input 1, locked output 1, `0x83`). The fill tx is the settle. `p` must be `"dmp"`. |
| `662f8d1` | 2026-10-21 15:15 | Fixed-price `settle` inscriptions are ignored. With an embedded `psdt`, `inscription_id`/`price`/`seller` may be omitted. |
| `e4e8ba7` (#1) | 2026-10-21 22:30 | **v2 compact signed orders** (`spec-v2.md`), `asig`, vectors, reference reconstructor |
| `5b3130c` (#2) | 2026-10-21 23:41 | v2 newer-`ts`-wins ordering, duplicate-key rejection |
| `e171638` (#3) | 2026-10-22 08:38 | v2 P2SH dogs, m-of-n `asigs`; v1 PSDT signature check covers P2SH |

An implementation written on 20–21 Oct was most likely built against **`bd900e2`**. The chain
agrees. The two mainnet lists tagged `listing_marketplace:"marketplace.dogesoft.io"` were inscribed
at blocks 6424225 and 6424299 (2026-10-21 02:14 and 03:31 PDT). That is after `bd900e2` and about
12 hours before `662f8d1`. Both are hash-only lists (`psdt_hash` with `inscription_id`, `price`,
`seller` and flat fee keys, and no `v` or `ts`), which `bd900e2` allows. `662f8d1` is possible only
for code changed after 15:15 on the 21st. Everything below is measured from `bd900e2`. Run
`git diff bd900e2 -- spec.md` to see the v1 text changes yourself.

## What still works unchanged

- **The seller signature.** `SIGHASH_SINGLE|ANYONECANPAY` (`0x83`), legacy sighash, dog on **input 1**,
  seller paid on **output 1**. The v2 signature commits to exactly the same digest (spec-v2 §5.2).
  A v1 signer that already produces this signature only needs to emit different JSON.
- **The fill shape.** Your buyer-side transaction (buyer coin on input 0, dog on input 1, seller on
  output 1, dog to the buyer on a later output, fee inputs after the dog) is a valid v2 fill. It is
  the canonical layout.
- **The fill tx is the settle.** No `settle` inscription is needed, and none is read.
- **Cancel-by-move.** Spending the dog anywhere other than a fill ends the order.
- **`p:"dmp"`**, koinu decimal strings, `±7200 s` `ts` window, 6-block settlement.
- **v1 lists stay valid.** A v2 indexer still reads v1 `list` ops. v2 adds two requirements to
  them: the embedded PSDT signature must verify, and the dog must not be signed at input 0 (row 9
  below).

## Changes

| # | area | v1 (`bd900e2`) | v2 | status |
|---|---|---|---|---|
| 1 | Order fields | `seller`, `psdt` or `psdt_hash`, flat fee keys (`royalty_address`, `royalty_bps`, `market_fee_bps`, `listing_fee_address`, …) | `v:"2"`, `chain` (required), `inscription_id`, `utxo`, `price` (gross), `pay_to`, `pubkey` (or `redeem_script`), `sig` (DER+`83`), `fees{royalty_bps,royalty_to,market_bps,listing_to,listing_share_bps}`, `ts`, `expiry`. `psdt` optional and derived; `psdt_hash` forbidden. The fee split uses integer floor math (§4.1). The schema is `schemas/list-v2.schema.json`. | **must-change** to emit or index v2 |
| 2 | PSDT | Embedded bytes are the contract | The indexer rebuilds the canonical PSDT from the JSON (§5.1–5.3). An embedded `psdt` must match the rebuild byte for byte. Placeholder: `in[0]` = 32 zero bytes:0, `out[0]` = 100000 koinu to `pay_to`, `out[1]` = net. | **must-change** (indexer); optional for emitters (omit `psdt`) |
| 3 | Authorization (`asig`) | Ownership by address match | A v2 `list`/`cancel` must be authorized by the order key: either the reveal is signed by that key (§7.1) or it carries a valid `asig` (§7.2, a signed-message signature over the canonical serialization). An `asig` that fails is a rejection, with no fallback. Multisig needs `m` `asigs`. | **must-change** (indexer); `asig` optional for emitters that inscribe with the seller key |
| 4 | `ts` ordering | Latest valid op wins, no ordering rule | Newer `ts` wins for the same outpoint, and ties go to the op applied first in chain order (§6.1). Re-pricing needs a strictly larger `ts`. v2 compares against block `nTime`, not MTP. | **must-change** (indexer) |
| 5 | Duplicate keys | Parser-dependent | A v2 op with a repeated key at any depth, compared after unescaping, is INVALID (§4.2). | **must-change** (indexer) |
| 6 | P2SH dogs | v1 PSDT check was P2PKH-only | `redeem_script` replaces `pubkey`, for P2PK or m-of-n templates (§5.4). The canonical PSDT carries key `0x04`. | **must-change** if you index P2SH-held dogs; optional otherwise (P2PKH-only emitters are fine) |
| 7 | Location rule | "Address-match against indexed inscription state" (undefined) | ord FIFO sat flow with offsets, zero-value outputs skipped, and sats past the last output lost to fee. Multi-part reveal: the ID is the first part's `txid i0`, and the location is the completing reveal's `:0:0` (§8.1). This is what Doginals indexers such as dogesoft and wonky-ord already do. | **must-change** if you do not already use ord FIFO. Most Doginals indexers already comply. |
| 8 | Fill layout | Dog on the buyer's output after output 1 | Validation is **layout-agnostic** (§8.2). A fill is `in[1] = utxo` and `out[1] = signed out[1]`. It is a sale if the dog lands, by §8.1, on any output owned by someone other than the order key. Example: diggydoge's dog on `out[0]` at offset 1,000,000. Dog back to the seller, or lost to fee, is cancel-by-move. The canonical layout is unchanged. | **must-change** for indexers that only accept one layout; optional for fill builders |
| 9 | v1 PSDT check | Not required | A v1 `list` with an embedded `psdt` must have its partial signature verified against the dog prevout (`0x83`, low-S, P2PKH or §5.4 P2SH). Without that check, anyone can list someone else's dog. A PSDT that signs the dog at **input 0** is INVALID (`postage_unsafe`): every use of it returns the dog to the seller (spec-v2 §15). A v1 sale also needs the dog to land with a non-seller owner (row 8), not just a payment to the seller. | **must-change** (indexer, v1 path too) |
| 10 | OP_RETURN tag | DOTC `dotc|1|…` optional | The optional `dmp2` venue tag `OP_RETURN PUSH("dmp2") PUSH(<venue spk>)` drives only `settlement_fee_ok`. A tx relays with one OP_RETURN, so a dogesoft-style `{"ds":…}` JSON OP_RETURN takes precedence and the dmp2 tag is dropped. The fill stays valid, `settlement_fee_ok` is `null`, and `op_return_kind` reports `json:ds` (§8.3). | **optional** |
| 11 | Cancel | `op:"cancel"` with `cancel_id`, `cancel_type`, `canceller`, `reason`, `sig`, `ts` | `{"p":"dmp","v":"2","op":"cancel","list_id":…}` plus optional `asig`, with no `ts`. It must name the *current* list. It is advisory: a later fill still counts and is flagged `after_cancel`. Only moving the dog is authoritative (§9). The schema is `schemas/cancel-v2.schema.json`. | **must-change** to index v2 cancels; v1 cancels of v1 lists are unchanged |
| 12 | Compliance | Fee outputs required by the venue | `royalty_ok`, `listing_fee_ok`, `settlement_fee_ok`, `fee_split_ok`, `after_cancel` and `after_expiry` are **flags**. They never invalidate a sale (§8). | **must-change** if you reject sales with unpaid fees |
| 13 | Dust and fees | Unspecified | 0.01 DOGE soft dust / 0.001 hard, ≥ 1 DOGE/kB fee, seller net ≥ 100000 koinu (≥ 1 DOGE recommended) (§8.4) | optional (guidance) |

## v1-only pilot interop

A v1-only implementation can run a pilot alongside v2 indexers safely if it does the following:

1. **List only in v1 with an embedded `psdt`** in the canonical shape (dog on `in[1]`, `0x83`, seller
   on `out[1]`). v2 indexers read it as a v1 list, so the buyer, the sale and `settled` agree across
   implementations. Do not use `psdt_hash`.
2. **Ignore any op whose `v` is not `"1.0"` or absent.** A v2 order lacks `seller`, so a strict v1
   parser rejects it anyway. Do not "repair" it.
3. **Verify the PSDT signature** on v1 lists (row 9). An indexer that skips this disagrees with v2
   indexers about junk-signature lists.
4. **Track location with ord FIFO** (row 7) and treat any non-fill spend as cancel-by-move. Then fills
   built by any venue in any layout resolve the same way (row 8).
5. **One version per dog.** A v2 indexer will not let a v1 list supersede an active v2 order, and a
   v1-only indexer cannot see the v2 order. If a seller lists the same dog in both, the two indexers
   show different current listings. During a pilot, a seller relists in v2 or moves the dog to retire
   a v1 order.
6. **Fill v2 orders as plain transactions.** A v1-only wallet can fill a v2 order: use
   the order's `sig` on `in[1]` and its `out[1]`. To a v1 indexer the result is an ordinary transfer
   to the buyer, which is correct ownership even though it is not shown as a sale.

The two embedded-PSDT v1 mainnet lists (`54f111c3…6236i0` and `bd75ee39…c2d4i0`) sign the
dog at input 0. They are INVALID as orders and can never produce a sale (spec-v2 §15,
[IMPLEMENTERS.md](IMPLEMENTERS.md#v1-mainnet-lists)). If you built against `bd900e2`, your
indexer should already refuse to fill this shape. Check that it also refuses to *list* them.
