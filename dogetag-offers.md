<!-- markdownlint-disable MD024 -->
# ÐMP DogeTag Offers — Lightweight Offer Signaling

Version: v0.1 (Draft)  
Status: Draft extension to ÐMP  
Last Updated: 2026-09-03  
Chain: Dogecoin

---

## 1. Introduction

ÐMP DogeTag Offers are a lightweight **signaling layer** for ÐMP buy interest using Dogecoin `OP_RETURN` outputs plus
a small DOGE output to the intended recipient. The goal is simple: let marketplaces, wallets, and individuals
signal buy interest to a Doginal owner even when that owner is not connected to a marketplace.

At scale, DogeTag Offers are the **preferred default** for chatty bids/offers (ÐMP write budget / MUST-111).
They do **not** replace a provenance-grade ÐMP `offer`, `accept`, or `settle` when parties choose the inscription
path. They are discoverable pings that may lead to a full ÐMP offer flow — or to a direct fill without ever
inscribing negotiation chatter. The DOGE output is intentional anti-spam friction and may accumulate in the
recipient wallet whether or not the recipient responds.

---

## 2. Design Goals

- **Lightweight:** Fit in standard Dogecoin `OP_RETURN` policy where possible.
- **Non-custodial:** No marketplace escrow and no required central relay.
- **Recipient-visible:** Wallets can detect inbound DogeTag outputs and parse offer intent.
- **Anti-spam:** Every signal costs the sender real DOGE and sends a small amount to the recipient.
- **Composable:** A full ÐMP `offer` MAY reference the DogeTag txid later.

---

## 3. Wire Format

DogeTag Offers use an `OP_RETURN` output with the Dogenals Era 2 DXD marker. The branded marker is `Ð:𝕏`;
senders MUST fall back to `Ð:X` when the stylized marker would push the total payload above 76 bytes.

| Offset | Size | Field | Description |
| --- | ---: | --- | --- |
| 0 | 7 or 4 | marker | UTF-8 `Ð:𝕏` (`c3 90 3a f0 9d 95 8f`) or fallback `Ð:X` (`c3 90 3a 58`) |
| +0 | 1 | version | `0x01` |
| +1 | 1 | kind | `0x01` = buy offer |
| +2 | 1 | flags | Bitfield, see §3.2 |
| +3 | 1 | asset_type | `0x01` inscription, `0x02` collection |
| +4 | 16 | asset_hash16 | First 16 bytes of `SHA256(asset_id_utf8)` |
| +20 | 8 | price_koinu | uint64 little-endian |
| +28 | 4 | expiry_height_delta | uint32 little-endian, relative to confirmation height |
| +32 | 4 | nonce | uint32 little-endian |

Payload length: **43 bytes** with `Ð:𝕏`, or **40 bytes** with `Ð:X`.

This binary payload is the canonical compact form. Wallets and marketplaces **MUST NOT** inscribe a JSON
DogeTag replacement merely for readability; decoded JSON belongs in APIs, indexes, examples, and UI state.

### 3.1 Asset id hash

- For an inscription target, `asset_id_utf8` is the ÐMP inscription id string: `{64 hex}i{vout}`.
- For a collection target, `asset_id_utf8` is the ÐMP `collection_id`.
- Because only 16 bytes are carried in the DogeTag, wallets **SHOULD** match candidates from their indexed
  wallet inventory. Ambiguous matches **MUST** be shown as ambiguous or ignored.

### 3.2 Flags

| Bit | Meaning |
| ---: | --- |
| 0 | Sender intends to inscribe a full ÐMP `offer` if recipient responds |
| 1 | Sound/notification hint requested |
| 2 | Private contact available in a linked Ðignal message |
| 3-7 | Reserved; **MUST** be ignored if unknown |

---

## 4. Transaction Shape

A valid DogeTag Offer transaction **MUST** include:

1. One `OP_RETURN` output whose payload begins with `Ð:𝕏` or `Ð:X`.
2. At least one spendable DOGE output to the recipient address.
3. A miner fee paid by the sender.

The recipient output amount is the **attention amount**.

### 4.1 Attention amount

- Minimum attention amount: **100,000 koinu** (0.001 DOGE).
- Wallets **MAY** configure a higher display threshold.
- Indexers **MUST** expose the actual amount sent to the recipient.

### 4.2 Offer price

`price_koinu` is the intended purchase price. It is **not** escrowed and **MUST NOT** be treated as a payment.
Actual settlement remains ÐMP `settle`.

---

## 5. Verification Rules

- MUST-001: `OP_RETURN` payload marker equals `Ð:𝕏` or `Ð:X`.
- MUST-002: `version` equals `0x01`.
- MUST-003: `kind` equals `0x01`.
- MUST-004: `asset_type` is recognized.
- MUST-005: `price_koinu` is greater than zero.
- MUST-006: recipient output amount is at least the minimum attention amount.
- MUST-007: `expiry_height_delta` is non-zero and **SHOULD** be <= 43,200 blocks (~30 days).
- MUST-008: an expired DogeTag Offer **MUST** be hidden from active-offer views.
- MUST-009: a full ÐMP `offer`, if later inscribed, **MAY** include `tag_txid`; indexers **SHOULD** link it.

---

## 6. Wallet and Marketplace Behavior

- Wallets **SHOULD** scan inbound transactions for DogeTag attention outputs.
- Wallets **SHOULD** play optional sound effects only if the user enabled DogeTag notifications.
- Wallets **MUST** make clear that DogeTag Offers are **signals**, not settled trades.
- Marketplaces **MAY** convert a DogeTag into a full ÐMP `offer` flow.
- Indexers **SHOULD** group repeated DogeTags from the same sender to the same recipient/asset.

---

## 7. Anti-Spam and Fairness

DogeTag Offers intentionally make the sender pay both miners and recipients.

- Senders cannot spam for free; every DogeTag transfers spendable DOGE to the recipient.
- Wallets **SHOULD** let users set minimum attention amounts.
- Indexers **SHOULD** rate-limit notifications for repeated low-value tags from one sender.
- Marketplaces **MUST NOT** rank DogeTag offers above full ÐMP offers unless they disclose the ranking rule.

---

## 8. Optional Ðignal Link

If flag bit 2 is set, the sender MAY separately create a Ðignal message that
contains richer encrypted context. The DogeTag itself carries no plaintext message body.

---

## 9. Examples

### 9.1 Decoded DogeTag Offer

```json
{
  "marker": "Ð:𝕏",
  "version": 1,
  "kind": "buy_offer",
  "flags": {
    "full_dmp_offer_intended": true,
    "sound_hint": true,
    "dogewhisper_link": false
  },
  "asset_type": "inscription",
  "asset_hash16": "00112233445566778899aabbccddeeff",
  "price_koinu": "25000000000",
  "expiry_height_delta": 10080,
  "nonce": 12345,
  "attention_amount_koinu": "1000000"
}
```

### 9.2 Full ÐMP offer linking a DogeTag

```json
{
  "p": "dmp",
  "v": "1.0",
  "op": "offer",
  "offer_target_type": "inscription",
  "inscription_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaai0",
  "buyer": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
  "price": "25000000000",
  "offer_fee": "1000000",
  "fee_recipient": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
  "tag_txid": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "expiry": 1700010000,
  "chain": "dogecoin",
  "ts": 1700000000
}
```

---

## 10. Security Considerations

- DogeTags are public and link sender/recipient behavior.
- The 16-byte asset hash is a compact hint, not a global unique id in isolation.
- A DogeTag price is not escrow; never display it as guaranteed funds.
- Sound hints are untrusted; wallets must let users disable them.
- Dust and standardness policy may change; wallets should use configurable thresholds.
- If a Ðignal link exists, wallets **MUST** treat it as encrypted negotiation context only; it is not an offer acceptance, escrow, or settlement.
- Wallet notification behavior **SHOULD** follow the Dogenals wallet-notifications guide.
- Decoded payloads **SHOULD** validate against [schemas/dmp-offer-signal-decoded.json](schemas/dmp-offer-signal-decoded.json); binary fixtures are in [vectors/dmp-offer-signal-vectors.json](vectors/dmp-offer-signal-vectors.json).

---

## 11. Changelog

- **v0.1 (2026-04-24):** Initial DogeTag Offers draft: binary OP_RETURN signal, attention amount, expiry,
  ÐMP offer link, optional Ðignal flag.
