#!/usr/bin/env python3
"""Independent checker for the ÐMP 1.0 hardening sections of compact-orders.md:

  §4.1  exact (>= 128-bit) fee math, no wrap      vectors: fee_math[]
  §8.5  every non-empty OP_RETURN is a Dogetag    vectors: dogetag[]
  §17   directed (buyer-bound) orders, 0x81       vectors: directed_valid[], directed_invalid[], directed_fill[]
  §18   0xD2 compact carrier, strict framing      vectors: carrier[]
  §19   order-book state digest                   vectors: book_digest[]

  dmp_hardening.py check vectors/dmp_hardening_vectors.json
  dmp_hardening.py gen  > vectors/dmp_hardening_vectors.json   (regenerate; signs with the fixed public TEST keys below)

Written from the spec. Reuses the tx / base58 / DER helpers of dmp_v2_reconstruct.py (same folder).
REGTEST/TESTING TOOL. The only keys it signs with are the well-known test scalars 0x01..01 and
0x02..02. It never broadcasts anything.
"""
import hashlib, json, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dmp_v2_reconstruct import (  # noqa: E402
    CHAINS, B58, sha256d, hash160, varbytes, address_script, ser_tx, parse_tx, txid, dec_str,
    strict_der, parse_redeem, p2pkh, p2sh, push, _verifies,
)
import ecdsa  # noqa: E402

CHAIN = "dogecoin-regtest"
LEAD, MIN_DUST, MAX_ROYALTY, MAX_MARKET, DEFAULT_SHARE = 100_000, 100_000, 2500, 2000, 5000
DIRECTED_HT = 0x81
U64_MAX = 2**64 - 1

# ── §4.1 fee math: exact integers (Python ints are unbounded; the rule is "never wrap") ──
def split(price, royalty_bps, market_bps, share_bps, has_royalty_to, has_listing_to):
    if not 0 < price <= U64_MAX: raise ValueError("price out of range")
    if royalty_bps > MAX_ROYALTY or market_bps > MAX_MARKET or share_bps > 10000: raise ValueError("bps above cap")
    royalty = price * royalty_bps // 10000 if royalty_bps and has_royalty_to else 0
    market = price * market_bps // 10000
    listing = market * share_bps // 10000 if market and has_listing_to else 0
    net = price - royalty - market
    if net < 0 or net > U64_MAX: raise ValueError("fee math out of range")
    return dict(royalty=royalty, market=market, listing=listing, settlement=market - listing, net=net)

# ── §8.5 Dogetag: concatenation of every data push after OP_RETURN; non-empty => Dogetag ──
def script_pushes(s):
    """(ok, pushes). Data pushes only; OP_N / other opcodes contribute nothing (like dogex)."""
    i, out = 0, []
    while i < len(s):
        op = s[i]; i += 1
        if op == 0x00: out.append(b""); continue
        if 1 <= op <= 75: n = op
        elif op == 0x4C:
            if i + 1 > len(s): return False, out
            n = s[i]; i += 1
        elif op == 0x4D:
            if i + 2 > len(s): return False, out
            n = struct.unpack("<H", s[i:i + 2])[0]; i += 2
        elif op == 0x4E:
            if i + 4 > len(s): return False, out
            n = struct.unpack("<I", s[i:i + 4])[0]; i += 4
        else: continue
        if i + n > len(s): return False, out
        out.append(s[i:i + n]); i += n
    return True, out

def dogetag_payload(script):
    if not script or script[0] != 0x6A: return None
    _, pushes = script_pushes(script[1:])
    p = b"".join(pushes)
    return p or None

# ── §18 0xD2 carrier: exactly 6a 01 d2 01 <ver> <n> <payload[n]>, 1 <= n <= 75 ──
CARRIER_CODE, CARRIER_VERSION = 0xD2, 0x01
def parse_carrier(script):
    """None = not a 0xD2 candidate; ("void", why) = candidate that breaks §18; ("ok", ver, kind, body)."""
    if script[:3] != b"\x6a\x01\xd2": return None
    s = script
    if len(s) < 7 or s[3] != 0x01: return ("void", "version must be the direct push 01 <ver>")
    ver, n = s[4], s[5]
    if not 1 <= n <= 75: return ("void", "payload must be one direct push of 1..75 bytes")
    if len(s) != 6 + n: return ("void", "bytes after the payload push, or payload truncated")
    if ver != CARRIER_VERSION: return ("unknown-version", ver)
    return ("ok", ver, s[6], s[7:6 + n])

def first_op_return(outs):
    for o in outs:
        if o["script"][:1] == b"\x6a": return o["script"]
    return None

# ── §17 directed orders ──
def parse_directed(o, chain=CHAIN):
    if o.get("p") != "dmp" or o.get("v") != "2" or o.get("op") != "list": raise ValueError("not a compact list")
    if o.get("mode") != "directed": raise ValueError("not directed")
    if o.get("chain") != chain: raise ValueError("chain mismatch")
    if "items" in o and "inscription_id" not in o: raise ValueError("a batch cannot be directed")
    t, vout = o["utxo"].split(":")
    if len(t) != 64 or t != t.lower() or str(int(vout)) != vout: raise ValueError("utxo")
    price = dec_str(o.get("price"), "price")
    if "redeem_script" in o:
        redeem = bytes.fromhex(o["redeem_script"]); tpl = parse_redeem(redeem)
    else:
        pk = bytes.fromhex(o["pubkey"])
        if len(pk) != 33 or pk[0] not in (2, 3) or pk.hex() != o["pubkey"]: raise ValueError("pubkey")
        redeem, tpl = None, ("pkh", 1, [pk])
    sig_hex = o["sigs"] if tpl[0] == "multi" else [o["sig"]]
    sigs = []
    for h in sig_hex:
        sig = bytes.fromhex(h)
        if sig[-1] & 0x1F == 0x02: raise ValueError("sig hashtype is SIGHASH_NONE")
        if sig[-1] != DIRECTED_HT: raise ValueError("directed sig hashtype must be 0x81")
        strict_der(sig[:-1]); sigs.append(sig)
    if "buyer" not in o: raise ValueError("buyer required")
    buyer = address_script(o["buyer"], chain)
    postage = dec_str(o.get("postage"), "postage")
    if postage < MIN_DUST: raise ValueError("postage below dust")
    f = o.get("fees", {})
    rb = dec_str(f["royalty_bps"], "royalty_bps", 10000) if "royalty_bps" in f else 0
    mb = dec_str(f["market_bps"], "market_bps", 10000) if "market_bps" in f else 0
    share = dec_str(f["listing_share_bps"], "listing_share_bps", 10000) if "listing_share_bps" in f else DEFAULT_SHARE
    if rb and "royalty_to" not in f: raise ValueError("royalty_to required")
    if mb and ("listing_to" not in f or share != 10000): raise ValueError("directed market fee goes wholly to listing_to")
    s = split(price, rb, mb, share, "royalty_to" in f, "listing_to" in f)
    if s["net"] < MIN_DUST: raise ValueError("signed seller output below dust")
    if 0 < s["royalty"] < MIN_DUST or 0 < s["listing"] < MIN_DUST: raise ValueError("directed fee output below dust")
    outs = [dict(value=LEAD, script=buyer), dict(value=postage, script=buyer),
            dict(value=s["net"], script=address_script(o["pay_to"], chain))]
    if s["royalty"]: outs.append(dict(value=s["royalty"], script=address_script(f["royalty_to"], chain)))
    if s["listing"]: outs.append(dict(value=s["listing"], script=address_script(f["listing_to"], chain)))
    tx = dict(version=2, locktime=0,
              ins=[dict(prev=b"\x00" * 32, vout=0, script=b"", seq=0xFFFFFFFE),
                   dict(prev=bytes.fromhex(t)[::-1], vout=int(vout), script=b"", seq=0xFFFFFFFF)],
              outs=outs)
    return dict(o=o, txid=t, vout=int(vout), tpl=tpl, redeem=redeem, keys=tpl[2], sigs=sigs, split=s, tx=tx)

def sighash_all_acp(tx, index, script_code):
    t = dict(tx, ins=[dict(tx["ins"][index], script=script_code)])
    return sha256d(ser_tx(t) + struct.pack("<I", DIRECTED_HT))

def directed_digest(d):
    return sighash_all_acp(d["tx"], 1, p2pkh(d["keys"][0]) if d["redeem"] is None else d["redeem"])

def directed_psdt(d, parent_raw):
    if txid(parent_raw) != d["txid"]: raise ValueError("parent tx does not match utxo txid")
    parent = parse_tx(parent_raw)
    want = p2pkh(d["keys"][0]) if d["redeem"] is None else p2sh(d["redeem"])
    if parent["outs"][d["vout"]]["script"] != want: raise ValueError("dog output is not the owner script")
    digest = directed_digest(d)
    if d["redeem"] is not None: raise ValueError("vector generator covers P2PKH directed orders")
    if not _verifies(d["keys"][0], d["sigs"][0], digest): raise ValueError("seller signature does not verify")
    n_out = len(d["tx"]["outs"])
    psbt = b"psbt\xff" + varbytes(b"\x00") + varbytes(ser_tx(d["tx"])) + b"\x00"
    psbt += b"\x00"
    psbt += varbytes(b"\x00") + varbytes(parent_raw)
    psbt += varbytes(b"\x02" + d["keys"][0]) + varbytes(d["sigs"][0])
    psbt += varbytes(b"\x03") + varbytes(struct.pack("<I", DIRECTED_HT)) + b"\x00"
    psbt += b"\x00" * n_out
    return psbt, digest

def directed_is_fill(fill, d):
    spends = any(i["prev"] == bytes.fromhex(d["txid"])[::-1] and i["vout"] == d["vout"] for i in fill["ins"])
    return spends and fill["outs"] == d["tx"]["outs"]

# ── §19 order-book digest ──
def book_digest(height, block_hash, rows):
    lines = sorted(f'{r["listed_inscription_id"]}\t{r["list_inscription_id"]}\t{r["utxo"]}\t{r["price"]}\t{r["net"]}\t{r["mode"]}\n'.encode() for r in rows)
    pre = f"dmp-book-v1\n{height}\n{block_hash}\n{len(lines)}\n".encode() + b"".join(lines)
    return hashlib.sha256(pre).hexdigest()

# ── check ──
def check(path):
    v = json.load(open(path, encoding="utf-8")); bad = 0
    def fail(name, msg):
        nonlocal bad; bad += 1; print("FAIL", name, msg)
    for c in v["fee_math"]:
        try: got = split(int(c["price"]), c["royalty_bps"], c["market_bps"], c["listing_share_bps"], True, True)
        except ValueError as e: got = {"error": str(e)}
        want = c["expect"]
        if "error" in want: (None if "error" in got else fail(c["name"], got))
        elif {k: str(x) for k, x in got.items()} != want: fail(c["name"], got)
    for c in v["dogetag"]:
        outs = [dict(value=0, script=bytes.fromhex(s)) for s in c["outputs_spk_hex"]]
        tags = [dogetag_payload(o["script"]) for o in outs]
        if [t.hex() if t else None for t in tags] != c["expect"]["dogetag_payload_hex"]: fail(c["name"], tags)
    for c in v["carrier"]:
        r = parse_carrier(bytes.fromhex(c["spk_hex"]))
        got = "not-candidate" if r is None else r[0]
        if got != c["expect"]["result"]: fail(c["name"], r)
        if r and r[0] == "ok" and (r[2] != c["expect"]["kind"] or r[3].hex() != c["expect"]["body_hex"]): fail(c["name"], r)
        if (dogetag_payload(bytes.fromhex(c["spk_hex"])) is not None) != c["expect"]["is_dogetag"]: fail(c["name"], "dogetag")
    for c in v["directed_valid"]:
        try:
            d = parse_directed(c["order"]); psbt, digest = directed_psdt(d, bytes.fromhex(c["parent_tx_hex"]))
            if digest.hex() != c["sighash"] or psbt.hex() != c["psdt_hex"]: fail(c["name"], "sighash/psdt")
            if ser_tx(d["tx"]).hex() != c["template_tx_hex"]: fail(c["name"], "template")
            if {k: str(x) for k, x in d["split"].items()} != c["split"]: fail(c["name"], d["split"])
        except ValueError as e: fail(c["name"], e)
    for c in v["directed_invalid"]:
        try:
            d = parse_directed(c["order"])
            if "parent_tx_hex" in c: directed_psdt(d, bytes.fromhex(c["parent_tx_hex"]))
            fail(c["name"], "accepted")
        except ValueError: pass
    for c in v["directed_fill"]:
        d = parse_directed(c["order"]); fill = parse_tx(bytes.fromhex(c["fill_tx_hex"]))
        if txid(bytes.fromhex(c["fill_tx_hex"])) != c["fill_txid"]: fail(c["name"], "txid")
        if directed_is_fill(fill, d) != c["expect"]["is_fill"]: fail(c["name"], "is_fill")
    for c in v["book_digest"]:
        if book_digest(c["height"], c["block_hash"], c["rows"]) != c["digest"]: fail(c["name"], "digest")
    print("ALL MATCH" if not bad else f"{bad} failure(s)")
    return bad

# ── gen ──
def b58check(b):
    b = b + sha256d(b)[:4]; n = int.from_bytes(b, "big"); s = ""
    while n: n, r = divmod(n, 58); s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + s
def addr(h, chain=CHAIN): return b58check(bytes([CHAINS[chain][0]]) + h)
def sk(i): return ecdsa.SigningKey.from_string(bytes([i]) * 32, curve=ecdsa.SECP256k1)
def pub(i): return sk(i).get_verifying_key().to_string("compressed")
def sign(i, digest, ht):
    k = sk(i)
    for extra in range(256):
        der = k.sign_digest_deterministic(digest, hashfunc=hashlib.sha256, sigencode=ecdsa.util.sigencode_der_canonize,
                                          extra_entropy=b"" if extra == 0 else bytes([extra]))
        try: strict_der(der); return der + bytes([ht])
        except ValueError: continue
    raise RuntimeError("no strict signature")

def gen():
    out = {"spec": "dmp-spec compact-orders.md §4.1, §8.5, §17, §18, §19", "network": CHAIN,
           "generated_by": "reference/dmp_hardening.py gen", "keys": {"seller": pub(1).hex(), "other": pub(2).hex(),
           "seller_secret": "0101…01 (public TEST scalar)", "other_secret": "0202…02 (public TEST scalar)"}}
    out["fee_math"] = [
        dict(name="u64-max-price-max-fees", note="price·bps needs 77 bits; exact math, no wrap",
             price=str(U64_MAX), royalty_bps=2500, market_bps=2000, listing_share_bps=5000,
             expect={k: str(x) for k, x in split(U64_MAX, 2500, 2000, 5000, True, True).items()}),
        dict(name="u64-max-price-no-fees", price=str(U64_MAX), royalty_bps=0, market_bps=0, listing_share_bps=5000,
             expect={k: str(x) for k, x in split(U64_MAX, 0, 0, 5000, True, True).items()}),
        dict(name="odd-price-floor", price="1000000007", royalty_bps=333, market_bps=199, listing_share_bps=3333,
             expect={k: str(x) for k, x in split(1000000007, 333, 199, 3333, True, True).items()}),
        dict(name="price-above-u64", note="not representable: INVALID, never truncated", price=str(U64_MAX + 1),
             royalty_bps=0, market_bps=0, listing_share_bps=5000, expect={"error": "price out of range"}),
    ]
    def opret(*pushes):
        return (b"\x6a" + b"".join(push(p) for p in pushes)).hex()
    p2pkh_hex = lambda h: p2pkh_raw(h).hex()
    out["dogetag"] = [
        dict(name="plain-send-with-tag", note="a friend sends DOGE and writes a note: Dogetag",
             context="payment + change + OP_RETURN", outputs_spk_hex=[p2pkh_hex(b"\x09" * 20), opret(b"gm fren, enjoy the doge"), p2pkh_hex(b"\x07" * 20)],
             expect=dict(dogetag_payload_hex=[None, b"gm fren, enjoy the doge".hex(), None], dmp_role=[None, "none", None])),
        dict(name="multi-push-tag", note="pushes are concatenated", outputs_spk_hex=[opret(b"such ", b"wow")],
             expect=dict(dogetag_payload_hex=[b"such wow".hex()], dmp_role=["none"])),
        dict(name="tag-inside-dmp-fill", note="a §8.2 fill whose one OP_RETURN is a note: still a fill (op_return_kind other) and a Dogetag",
             outputs_spk_hex=[p2pkh_hex(b"\x09" * 20), p2pkh_hex(b"\x07" * 20), opret(b"thanks for the dog"), p2pkh_hex(b"\x09" * 20)],
             expect=dict(dogetag_payload_hex=[None, None, b"thanks for the dog".hex(), None], dmp_role=[None, None, "op_return_kind:other", None])),
        dict(name="dmp2-venue-tag-is-also-a-dogetag", outputs_spk_hex=[opret(b"dmp2", p2pkh_raw(b"\x05" * 20))],
             expect=dict(dogetag_payload_hex=[(b"dmp2" + p2pkh_raw(b"\x05" * 20)).hex()], dmp_role=["op_return_kind:dmp2"])),
        dict(name="tag-alongside-inscription-reveal", note="the reveal's envelope is in the scriptSig; its OP_RETURN output is a Dogetag",
             context="reveal tx: out[0] inscription, out[1] OP_RETURN", outputs_spk_hex=[p2pkh_hex(b"\x09" * 20), opret(b"minted with love")],
             expect=dict(dogetag_payload_hex=[None, b"minted with love".hex()], dmp_role=[None, "none"])),
        dict(name="dogetag-offer-unknown-kind", note="Ð:X marker + v1 + kind 0x7f (not defined): not an offer, still a Dogetag",
             outputs_spk_hex=[opret(bytes.fromhex("c3903a58") + b"\x01\x7f" + b"\x00" * 10)],
             expect=dict(dogetag_payload_hex=[(bytes.fromhex("c3903a58") + b"\x01\x7f" + b"\x00" * 10).hex()], dmp_role=["dogetag-offer:ignored"])),
        dict(name="void-d2-carrier", note="breaks §18 framing: void for ÐMP, still a Dogetag", outputs_spk_hex=["6a01d201010201ff00"],
             expect=dict(dogetag_payload_hex=["d20101ff"], dmp_role=["carrier:void"])),
        dict(name="empty-op-return", note="the only OP_RETURN that is not a Dogetag", outputs_spk_hex=["6a"],
             expect=dict(dogetag_payload_hex=[None], dmp_role=["none"])),
        dict(name="op-return-small-number-only", note="OP_RETURN OP_1 pushes no data bytes: empty payload, not a Dogetag",
             outputs_spk_hex=["6a51"], expect=dict(dogetag_payload_hex=[None], dmp_role=["none"])),
    ]
    out["carrier"] = [
        dict(name="d2-v1-minimal", spk_hex="6a01d2010102ff00", expect=dict(result="ok", kind=0xff, body_hex="00", is_dogetag=True)),
        dict(name="d2-v1-max-payload", spk_hex="6a01d201014b10" + "ab" * 74, expect=dict(result="ok", kind=0x10, body_hex="ab" * 74, is_dogetag=True)),
        dict(name="d2-version-as-op1", note="OP_1 instead of the direct push 01 01: void", spk_hex="6a01d25102ff00", expect=dict(result="void", is_dogetag=True)),
        dict(name="d2-code-pushdata1", note="code pushed with OP_PUSHDATA1: not a candidate (prefix differs), plain Dogetag", spk_hex="6a4c01d2010102ff00", expect=dict(result="not-candidate", is_dogetag=True)),
        dict(name="d2-payload-pushdata1", note="non-minimal payload push: void", spk_hex="6a01d201014c02ff00", expect=dict(result="void", is_dogetag=True)),
        dict(name="d2-trailing-push", note="extra push after the payload: void", spk_hex="6a01d2010102ff0001aa", expect=dict(result="void", is_dogetag=True)),
        dict(name="d2-unknown-version", note="version 0x02 is not defined: ignored", spk_hex="6a01d2010202ff00", expect=dict(result="unknown-version", is_dogetag=True)),
        dict(name="d0-dune-untouched", note="other protocol codes are not ÐMP candidates", spk_hex="6a01d0010205aabbccddee", expect=dict(result="not-candidate", is_dogetag=True)),
    ]
    # directed vectors
    seller_pk, other_pk = pub(1), pub(2)
    parent = dict(version=1, locktime=0, ins=[dict(prev=b"\x00" * 32, vout=0xFFFFFFFF, script=b"\x51", seq=0xFFFFFFFF)],
                  outs=[dict(value=100_000, script=p2pkh(seller_pk))])
    parent_raw = ser_tx(parent); ptxid = txid(parent_raw)
    def base(**kw):
        o = {"p": "dmp", "v": "2", "op": "list", "mode": "directed", "chain": CHAIN,
             "inscription_id": f"{ptxid}i0", "utxo": f"{ptxid}:0", "price": "1000000000",
             "pay_to": addr(b"\x07" * 20), "buyer": addr(b"\x09" * 20), "postage": "100000",
             "pubkey": seller_pk.hex(), "sig": "", "ts": 1790000000}
        o.update(kw); return o
    def signed(o, key=1):
        o = dict(o); o["sig"] = "300602010102010181"  # placeholder so the order parses; replaced below
        o["sig"] = sign(key, directed_digest(parse_directed(o)), DIRECTED_HT).hex(); return o
    fees = {"royalty_bps": "500", "royalty_to": addr(b"\x05" * 20), "market_bps": "200", "listing_to": addr(b"\x06" * 20), "listing_share_bps": "10000"}
    valid = []
    for name, o in [("directed-no-fees", base()), ("directed-royalty-and-listing", base(fees=fees)),
                    ("directed-with-expiry", base(fees={"royalty_bps": "250", "royalty_to": addr(b"\x05" * 20)}, expiry=1790086400))]:
        o = signed(o); d = parse_directed(o); psbt, digest = directed_psdt(d, parent_raw)
        valid.append(dict(name=name, order=o, parent_tx_hex=parent_raw.hex(), template_tx_hex=ser_tx(d["tx"]).hex(),
                          sighash=digest.hex(), psdt_hex=psbt.hex(), split={k: str(x) for k, x in d["split"].items()}))
    out["directed_valid"] = valid
    good = valid[1]["order"]
    inv = []
    o = dict(good); o["sig"] = good["sig"][:-2] + "83"
    inv.append(dict(name="hashtype-83-on-directed", reason="directed sig hashtype must be 0x81", order=o))
    o = dict(good); del o["buyer"]; inv.append(dict(name="missing-buyer", reason="buyer required", order=o))
    o = dict(good); o["fees"] = dict(fees, listing_share_bps="5000")
    inv.append(dict(name="listing-share-not-10000", reason="directed market fee goes wholly to listing_to", order=o))
    o = dict(good); o["price"] = "900000000"; o["fees"] = {"royalty_bps": "1", "royalty_to": addr(b"\x05" * 20)}
    inv.append(dict(name="royalty-output-below-dust", reason="directed fee output below dust", order=o))
    o = dict(good); o["postage"] = "99999"; inv.append(dict(name="postage-below-dust", reason="postage below dust", order=o))
    o = dict(good); o["buyer"] = addr(b"\x0a" * 20)
    inv.append(dict(name="buyer-swapped-after-signing", reason="seller signature does not verify", order=o, parent_tx_hex=parent_raw.hex()))
    o = signed(base(), key=2); inv.append(dict(name="signed-by-non-owner", reason="seller signature does not verify", order=o, parent_tx_hex=parent_raw.hex()))
    out["directed_invalid"] = inv
    # fills
    d = parse_directed(good)
    def fill_tx(outs, dog_index=1):
        lead_in = dict(prev=hashlib.sha256(b"lead").digest(), vout=0, script=b"", seq=0xFFFFFFFF)
        fund_in = dict(prev=hashlib.sha256(b"fund").digest(), vout=1, script=b"", seq=0xFFFFFFFF)
        dog_in = dict(prev=bytes.fromhex(d["txid"])[::-1], vout=d["vout"], script=push(d["sigs"][0]) + push(d["keys"][0]), seq=0xFFFFFFFF)
        ins = [lead_in, dog_in, fund_in] if dog_index == 1 else [lead_in, fund_in, dog_in]
        return ser_tx(dict(version=2, locktime=0, ins=ins, outs=outs))
    fills = []
    for name, raw, ok in [
        ("exact-pinned-outputs", fill_tx(d["tx"]["outs"]), True),
        ("dog-at-input-2", fill_tx(d["tx"]["outs"], dog_index=2), True),
        ("extra-change-output", fill_tx(d["tx"]["outs"] + [dict(value=5_000_000, script=p2pkh_raw(b"\x09" * 20))]), False),
        ("royalty-dropped", fill_tx([x for i, x in enumerate(d["tx"]["outs"]) if i != 3]), False),
    ]:
        fills.append(dict(name=name, order=good, fill_tx_hex=raw.hex(), fill_txid=txid(raw), dog_script_sig_hex=(push(d["sigs"][0]) + push(d["keys"][0])).hex(),
                          expect=dict(is_fill=ok)))
    out["directed_fill"] = fills
    rows = [dict(listed_inscription_id="b" * 64 + "i0", list_inscription_id="c" * 64 + "i0", utxo="d" * 64 + ":1", price="1000000000", net="930000000", mode="public"),
            dict(listed_inscription_id="a" * 64 + "i3", list_inscription_id="e" * 64 + "i0", utxo="f" * 64 + ":0", price="250000000", net="250000000", mode="directed")]
    out["book_digest"] = [
        dict(name="empty-book", height=5900000, block_hash="00" * 32, rows=[], digest=book_digest(5900000, "00" * 32, [])),
        dict(name="two-orders-any-input-order", height=5900001, block_hash="11" * 32, rows=rows, digest=book_digest(5900001, "11" * 32, rows)),
    ]
    print(json.dumps(out, indent=2, ensure_ascii=False))

def p2pkh_raw(h): return b"\x76\xa9\x14" + h + b"\x88\xac"

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["check"]: sys.exit(1 if check(a[1]) else 0)
    if a[:1] == ["gen"]: gen(); sys.exit(0)
    print(__doc__); sys.exit(2)
