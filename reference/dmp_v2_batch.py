#!/usr/bin/env python3
"""ÐMP v2 batch-list vectors (compact-orders.md §16).

  python reference/dmp_v2_batch.py            # write vectors + §16.15 example bodies, then check
  python reference/dmp_v2_batch.py check vectors/dmp_v2_batch_vectors.json

Regtest keys are the integers 1, 2, 3… (test keys, not mainnet). Signatures are RFC6979.
`reason` strings name the §16.6 check that failed. They are informative, not a wire format.
"""
import base64, hashlib, json, os, sys
from ecdsa import SECP256k1, SigningKey
from ecdsa.util import sigencode_der_canonize, sigencode_string_canonize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dmp_v2_reconstruct import (  # noqa: E402
    ASIG_TAG, B58, N, address_script, asig_canonical, asig_digest, compliance, hash160,
    loads_v2, p2pkh, p2sh, parse_order, parse_redeem, push, rebuild, recover_asig,
    ser_tx, sha256d, sighash_single_acp, supersedes, template, txid, verify_asigs,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VEC = os.path.join(ROOT, "vectors", "dmp_v2_batch_vectors.json")
CHAIN = "dogecoin-regtest"
NTIME = 1790000000
TS = 1790000000
EXPIRY = 1790086400


def b58check(payload):
    raw = payload + sha256d(payload)[:4]
    n = int.from_bytes(raw, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * pad + (s or "")


def priv(i):
    return i.to_bytes(32, "big")


def pub_of(p):
    pt = SigningKey.from_string(p, curve=SECP256k1).verifying_key.pubkey.point
    return bytes([2 + (pt.y() & 1)]) + int(pt.x()).to_bytes(32, "big")


def addr_of(pub):
    return b58check(bytes([0x6F]) + hash160(pub))


def sign_rs(p, digest):
    sk = SigningKey.from_string(p, curve=SECP256k1)
    return sk.sign_digest_deterministic(digest, hashfunc=hashlib.sha256, sigencode=sigencode_string_canonize)


def sign_der83(p, digest):
    sk = SigningKey.from_string(p, curve=SECP256k1)
    der = sk.sign_digest_deterministic(digest, hashfunc=hashlib.sha256, sigencode=sigencode_der_canonize)
    return (der + bytes([0x83])).hex()


def sign_asig(p, pub, op):
    digest = asig_digest(asig_canonical(op))
    rs = sign_rs(p, digest)
    trial = dict(op)
    for recid in range(4):
        b64 = base64.b64encode(bytes([31 + recid]) + rs).decode()
        trial["asig"] = b64
        try:
            if recover_asig(b64, trial) == pub:
                return b64
        except (ValueError, Exception):
            continue
    raise RuntimeError("asig recovery failed")


def sign_asigs(keys, op):
    """keys: list of (priv, pub) in redeem-script order; sign the first m."""
    out = []
    trial = dict(op)
    for p, pub in keys:
        digest = asig_digest(asig_canonical(op))
        rs = sign_rs(p, digest)
        got = None
        for recid in range(4):
            b64 = base64.b64encode(bytes([31 + recid]) + rs).decode()
            trial["asigs"] = [b64]
            try:
                if recover_asig(b64, trial) == pub:
                    got = b64
                    break
            except (ValueError, Exception):
                continue
        if got is None:
            raise RuntimeError("asigs recovery failed")
        out.append(got)
    return out


def net_of(price, fees):
    fees = fees or {}
    rb = int(fees["royalty_bps"]) if "royalty_bps" in fees else 0
    mb = int(fees["market_bps"]) if "market_bps" in fees else 0
    royalty = price * rb // 10000 if rb and fees.get("royalty_to") else 0
    market = price * mb // 10000
    return price - royalty - market, royalty, market


def item_digest(utxo, pay_to, price, fees, pub, redeem=None):
    txid_hex, vout = utxo.split(":")
    net, royalty, market = net_of(int(price), fees)
    d = dict(txid=txid_hex, vout=int(vout), pay=address_script(pay_to, CHAIN), split=dict(net=net))
    code = redeem if redeem is not None else p2pkh(pub)
    return sighash_single_acp(template(d), 1, code), net, royalty, market


def emit_body(op):
    c = asig_canonical(op)
    if "asig" in op:
        tail = ',"asig":"' + op["asig"] + '"}'
    elif "asigs" in op:
        arr = "[" + ",".join('"' + a + '"' for a in op["asigs"]) + "]"
        tail = ',"asigs":' + arr + "}"
    else:
        return c
    return c[:-1] + tail


class Seq:
    def __init__(self):
        self.n = 0

    def parent(self, script):
        self.n += 1
        prev = hashlib.sha256(b"dmp-batch-parent" + self.n.to_bytes(4, "little")).digest()
        raw = ser_tx(dict(version=1, locktime=0,
                          ins=[dict(prev=prev, vout=0, script=b"\x51", seq=0xFFFFFFFF)],
                          outs=[dict(value=50_000_000_000, script=script)]))
        return raw, txid(raw)

    def insc(self):
        self.n += 1
        return hashlib.sha256(b"dmp-batch-insc" + self.n.to_bytes(4, "little")).hexdigest() + "i0"


def flip_sig(h):
    """A strict-DER low-S signature over the wrong scalar. I6 must reject it; I2 must not."""
    der = bytes.fromhex(h)[:-1]
    lr = der[3]
    rb = der[4:4 + lr]
    s = int.from_bytes(der[6 + lr:], "big")
    sv = (s + 1) % N
    if sv == 0 or sv > N // 2:
        sv = 1
    sb = sv.to_bytes(32, "big").lstrip(b"\x00") or b"\x00"
    if sb[0] & 0x80:
        sb = b"\x00" + sb
    body = b"\x02" + bytes([len(rb)]) + rb + b"\x02" + bytes([len(sb)]) + sb
    return (b"\x30" + bytes([len(body)]) + body + b"\x83").hex()


class World:
    def __init__(self):
        self.seq = Seq()
        self.seller = priv(1)
        self.seller_pub = pub_of(self.seller)
        self.other = priv(2)
        self.other_pub = pub_of(self.other)
        self.pay_priv = priv(8)
        self.pay = addr_of(pub_of(self.pay_priv))
        self.pay2 = addr_of(pub_of(priv(6)))
        self.listing = addr_of(pub_of(priv(9)))
        self.seller_script = p2pkh(self.seller_pub)
        self.other_script = p2pkh(self.other_pub)
        self.multi = [(priv(i), pub_of(priv(i))) for i in (3, 4, 5)]
        pubs = b"".join(b"\x21" + pk for _, pk in self.multi)
        self.multi_redeem = bytes([0x52]) + pubs + bytes([0x53, 0xAE])
        self.p2sh_redeem = b"\x21" + self.seller_pub + b"\xac"
        self.fees = {"market_bps": "200", "listing_to": self.listing}
        self.header = {
            "p": "dmp", "v": "2", "op": "list", "chain": CHAIN,
            "pubkey": self.seller_pub.hex(), "pay_to": self.pay, "ts": TS,
        }

    def dog(self, script, price, pay_to, fees, signer, pub, redeem=None, insc=None, utxo=None, parent_raw=None, extra=None, bad_sig=False):
        if parent_raw is None:
            parent_raw, tx = self.seq.parent(script)
            utxo = tx + ":0"
        if insc is None:
            insc = self.seq.insc()
        digest, net, royalty, market = item_digest(utxo, pay_to, price, fees, pub, redeem)
        if redeem is not None and signer == "multi":
            sigs = [sign_der83(p, digest) for p, _pk in self.multi[:2]]
            sig = None
        else:
            sig = sign_der83(signer, digest)
            sigs = None
            if bad_sig:
                sig = flip_sig(sig)
        item = {"inscription_id": insc, "utxo": utxo}
        if sigs is not None:
            item["sigs"] = sigs
        else:
            item["sig"] = sig
        if extra:
            item.update(extra)
        meta = dict(parent_tx_hex=parent_raw.hex(), net=net, royalty=royalty, market=market,
                    digest=digest, price=price, pay_to=pay_to, fees=fees, insc=insc, utxo=utxo)
        return item, meta


def resolve(header, item):
    o = {"p": header["p"], "v": header["v"], "op": header["op"], "chain": header["chain"], "ts": header["ts"]}
    for k in ("pubkey", "redeem_script"):
        if k in header:
            o[k] = header[k]
    for k in ("inscription_id", "utxo", "sig", "sigs"):
        if k in item:
            o[k] = item[k]
    if "price" in item:
        o["price"] = item["price"]
    elif "price" in header:
        o["price"] = header["price"]
    if "pay_to" in item:
        o["pay_to"] = item["pay_to"]
    elif "pay_to" in header:
        o["pay_to"] = header["pay_to"]
    if "fees" in item:
        if item["fees"]:
            o["fees"] = item["fees"]
    elif header.get("fees"):
        o["fees"] = header["fees"]
    if "expiry" in header:
        o["expiry"] = header["expiry"]
    return o


# priv lookup for the keys this file creates
_PRIVS = {pub_of(priv(i)): priv(i) for i in range(1, 10)}


def priv_for_pub(pub):
    return _PRIVS[pub]


def seal_single(header, items, signer_priv, signer_pub):
    op = dict(header)
    op["items"] = items
    op["asig"] = sign_asig(signer_priv, signer_pub, op)
    return op


def seal_multi(header, items, keys):
    op = dict(header)
    op["items"] = items
    op["asigs"] = sign_asigs(keys, op)
    return op


def pack(name, op, metas, result, ntime=NTIME, locations=None, current=None, extra=None, reasons=None):
    body = emit_body(op)
    parsed = json.loads(body)
    if asig_canonical(parsed) != asig_canonical(op):
        raise RuntimeError(name + " emit is not canonical")
    case = {
        "name": name,
        "result": result,
        "block_ntime": ntime,
        "body_bytes": len(body.encode()),
        "batch_json": body,
        "batch": parsed,
        "asig_canonical": asig_canonical(op),
        "asig_digest": asig_digest(asig_canonical(op)).hex(),
    }
    if "asig" in op:
        case["asig_integrity"] = True
    rows = []
    for i, (item, meta) in enumerate(zip(parsed["items"], metas)):
        if not isinstance(item, dict):
            continue
        row = {"n": i, "expect": "listed"}
        if reasons and i in reasons:
            row["expect"] = "rejected"
            row["reason"] = reasons[i]
        if meta is None:
            rows.append(row)
            continue
        row.update({
            "parent_tx_hex": meta["parent_tx_hex"],
            "net": meta["net"], "royalty": meta["royalty"], "market": meta["market"],
        })
        if row["expect"] == "listed" and "price" in resolve(parsed, item):
            resolved = resolve(parsed, item)
            # drop a bad sig from rebuild; listed items verify
            try:
                d = parse_order(resolved, CHAIN)
                psbt, digest = rebuild(d, bytes.fromhex(meta["parent_tx_hex"]))
                row["resolved"] = resolved
                row["psdt_hex"] = psbt.hex()
                row["sighash"] = digest.hex()
                row["list_id_suffix"] = ":" + str(i)
            except (ValueError, KeyError) as e:
                row["resolved"] = resolved
                row["rebuild_error"] = str(e)
        elif "inscription_id" in item:
            row["resolved"] = resolve(parsed, item) if "price" in item or "price" in parsed else None
        rows.append(row)
    case["items"] = rows
    if locations is not None:
        case["locations"] = locations
    if current is not None:
        case["current"] = current
    if extra:
        case.update(extra)
    return case


def write_examples():
    """§16.15 placeholder bodies. Digests are of these exact strings; signatures verify against nothing."""
    pubkey = "02" + "ab" * 32
    pay = "DEXAMPLEPAYADDRESSXXXXXXXXXXXXXXXX"
    listing = "DEXAMPLEMARKETADDRESSXXXXXXXXXXXXX"
    pay2 = "DEXAMPLEPAYADDRESSNUMBER2XXXXXXXXX"
    pay3 = "DEXAMPLEPAYADDRESSNUMBER3XXXXXXXXX"
    asig = "A" * 87 + "="

    def sig(b):
        return "30" + (b * 70) + "83"

    def item(ch, uh, sh, vout, extra=None):
        d = {"inscription_id": ch * 64 + "i0", "utxo": uh * 64 + ":" + vout, "sig": sig(sh)}
        if extra:
            d.update(extra)
        return d

    shared = {
        "p": "dmp", "v": "2", "op": "list", "chain": "dogecoin", "pubkey": pubkey, "pay_to": pay,
        "price": "1000000000", "fees": {"market_bps": "200", "listing_to": listing},
        "ts": 1792632460, "expiry": 1792718860,
        "items": [item("1", "a", "e1", "0"), item("2", "b", "e2", "0"), item("3", "c", "e3", "1")],
        "asig": asig,
    }
    per = {
        "p": "dmp", "v": "2", "op": "list", "chain": "dogecoin", "pubkey": pubkey, "pay_to": pay,
        "fees": {"market_bps": "200", "listing_to": listing}, "ts": 1792632460,
        "items": [
            item("1", "a", "e1", "0", {"price": "1000000000"}),
            item("2", "b", "e2", "0", {"price": "2500000000", "pay_to": pay2}),
            item("3", "c", "e3", "1", {"price": "10000000000", "pay_to": pay3}),
        ],
        "asig": asig,
    }
    ex = os.path.join(ROOT, "EXAMPLES")
    out = {}
    for name, op, fname in (("shared", shared, "batch-list-shared-price.json"), ("per_item", per, "batch-list-per-item-price.json")):
        body = emit_body(op)
        c = asig_canonical(op)
        open(os.path.join(ex, fname), "w", encoding="utf-8", newline="\n").write(body)
        out[name] = {"body_bytes": len(body), "canonical_bytes": len(c), "message_bytes": len(ASIG_TAG) + len(c),
                     "digest": asig_digest(c).hex(), "canonical": c, "body_file": "EXAMPLES/" + fname}
    open(os.path.join(ex, "batch-list-digests.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(out, indent=2) + "\n")
    assert out["shared"]["digest"] == "07aa4b53f28e15bc9a1d828e9f6d3dafe40565aa83a84a84473e7706962795b9"
    assert out["shared"]["body_bytes"] == 1368 and out["shared"]["canonical_bytes"] == 1270
    assert out["per_item"]["digest"] == "cd55017f3c11c578171446f2532b331fbd01a50c379eec0d6f2342bbd0d164c5"
    assert out["per_item"]["body_bytes"] == 1483 and out["per_item"]["canonical_bytes"] == 1385


def build():
    w = World()
    cases = []

    def add_dogs(header, specs, reasons=None, result="valid", **kw):
        items, metas, locs = [], [], {}
        for spec in specs:
            item, meta = w.dog(**spec["dog"])
            if spec.get("stamp"):
                item.update(spec["stamp"])
            items.append(item)
            metas.append(meta)
            loc = spec.get("location")
            locs[item["inscription_id"]] = {
                "utxo": item["utxo"] if not loc or loc[0] is None else loc[0],
                "owner": loc[1] if loc else "header",
            }
        if header.get("redeem_script", "").startswith("52"):
            op = seal_multi(header, items, w.multi[:2])
        else:
            signer = w.seller
            pub = w.seller_pub
            if "redeem_script" in header and "pubkey" not in header:
                pub = bytes.fromhex(header["redeem_script"][2:68])
            elif "pubkey" in header:
                pub = bytes.fromhex(header["pubkey"])
            op = seal_single(header, items, priv_for_pub(pub), pub)
        cases.append(pack(kw.get("name"), op, metas, result, locations=locs, reasons=reasons,
                          current=kw.get("current"), ntime=kw.get("ntime", NTIME), extra=kw.get("extra")))
        return cases[-1]

    # --- valid ---
    h = dict(w.header)
    h["price"] = "1000000000"
    h["fees"] = w.fees
    h["expiry"] = EXPIRY
    shared_specs = []
    for _ in range(3):
        shared_specs.append({"dog": dict(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=w.fees, signer=w.seller, pub=w.seller_pub)})
    shared = add_dogs(h, shared_specs, name="shared-price-expiry")

    # per-item prices, no header price, no expiry; items 1 and 2 override pay_to
    h2 = dict(w.header)
    h2["fees"] = w.fees
    specs = []
    prices = ["1000000000", "2500000000", "10000000000"]
    pays = [w.pay, w.pay2, w.pay2]
    # item 0 inherits pay_to; items 1 and 2 override. Use distinct pay for item 2.
    pay3 = addr_of(pub_of(priv(7)))
    pays = [None, w.pay2, pay3]
    for i in range(3):
        extra = {"price": prices[i]}
        pay = pays[i] or w.pay
        if pays[i]:
            extra["pay_to"] = pays[i]
        specs.append({"dog": dict(script=w.seller_script, price=prices[i], pay_to=pay, fees=w.fees, signer=w.seller, pub=w.seller_pub),
                      "stamp": extra})
    add_dogs(h2, specs, name="per-item-prices")

    # one batch: inherit, price override, pay_to override, fees override, fees {}
    h3 = dict(w.header)
    h3["price"] = "1000000000"
    h3["fees"] = w.fees
    h3["expiry"] = EXPIRY
    fee_override = {"market_bps": "100", "listing_to": w.listing, "listing_share_bps": "3000"}
    rows = [
        ("1000000000", w.pay, w.fees, None),
        ("2000000000", w.pay, w.fees, {"price": "2000000000"}),
        ("1000000000", w.pay2, w.fees, {"pay_to": w.pay2}),
        ("1000000000", w.pay, fee_override, {"fees": fee_override}),
        ("1000000000", w.pay, {}, {"fees": {}}),
    ]
    specs = []
    for price, pay, fees, stamp in rows:
        specs.append({"dog": dict(script=w.seller_script, price=price, pay_to=pay, fees=fees, signer=w.seller, pub=w.seller_pub), "stamp": stamp})
    add_dogs(h3, specs, name="per-item-overrides")

    h4 = dict(w.header)
    h4["price"] = "500000000"
    specs = []
    for _ in range(2):
        specs.append({"dog": dict(script=w.seller_script, price="500000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)})
    add_dogs(h4, specs, name="two-items")

    h5 = dict(w.header)
    h5["price"] = "1000000000"
    specs = []
    for _ in range(50):
        specs.append({"dog": dict(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)})
    add_dogs(h5, specs, name="fifty-items")

    h6 = {"p": "dmp", "v": "2", "op": "list", "chain": CHAIN, "redeem_script": w.p2sh_redeem.hex(),
          "pay_to": w.pay, "price": "1000000000", "ts": TS}
    specs = []
    for _ in range(2):
        specs.append({"dog": dict(script=p2sh(w.p2sh_redeem), price="1000000000", pay_to=w.pay, fees=None,
                                  signer=w.seller, pub=w.seller_pub, redeem=w.p2sh_redeem)})
    add_dogs(h6, specs, name="p2sh-single-key")

    h7 = {"p": "dmp", "v": "2", "op": "list", "chain": CHAIN, "redeem_script": w.multi_redeem.hex(),
          "pay_to": w.pay, "price": "1000000000", "fees": w.fees, "ts": TS}
    specs = []
    for _ in range(2):
        specs.append({"dog": dict(script=p2sh(w.multi_redeem), price="1000000000", pay_to=w.pay, fees=w.fees,
                                  signer="multi", pub=w.multi[0][1], redeem=w.multi_redeem)})
    add_dogs(h7, specs, name="multisig-2of3")

    # one bad owner, others listed
    specs = [
        {"dog": dict(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub),
         "stamp": {"price": "1000000000"}},
        {"dog": dict(script=w.other_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub),
         "location": (None, "other"), "stamp": {"price": "1000000000"}},
        {"dog": dict(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub),
         "stamp": {"price": "1000000000"}},
    ]
    add_dogs(h4, specs, name="one-wrong-owner", result="partial", reasons={1: "I5-wrong-owner"})

    # --- item rejects ---
    specs = []
    # build two items then we will clone utxo — easier to custom-build
    item_a, meta_a = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    item_b, meta_b = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub,
                           utxo=item_a["utxo"], parent_raw=bytes.fromhex(meta_a["parent_tx_hex"]), insc=w.seq.insc())
    item_c, meta_c = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    hp = dict(w.header)
    hp["price"] = "1000000000"
    op = seal_single(hp, [item_a, item_b, item_c], w.seller, w.seller_pub)
    locs = {item_a["inscription_id"]: {"utxo": item_a["utxo"], "owner": "header"},
            item_b["inscription_id"]: {"utxo": item_b["utxo"], "owner": "header"},
            item_c["inscription_id"]: {"utxo": item_c["utxo"], "owner": "header"}}
    cases.append(pack("duplicate-utxo", op, [meta_a, meta_b, meta_c], "partial", locations=locs,
                      reasons={0: "I3-duplicate-utxo", 1: "I3-duplicate-utxo"}))

    item_a, meta_a = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    item_b, meta_b = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    item_c, meta_c = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub,
                           insc=item_a["inscription_id"])
    # item_c has a different utxo but the same inscription id. Its sig is over its own utxo.
    op = seal_single(hp, [item_a, item_b, item_c], w.seller, w.seller_pub)
    locs = {}
    for it in (item_a, item_b, item_c):
        locs[it["inscription_id"]] = {"utxo": it["utxo"], "owner": "header"}
    # item_a and item_c share an id; the location map can only hold one. I3 fires on the raw strings
    # before location, so both copies are rejected regardless. Point the id at item_a's utxo.
    locs[item_a["inscription_id"]] = {"utxo": item_a["utxo"], "owner": "header"}
    cases.append(pack("duplicate-inscription-id", op, [meta_a, meta_b, meta_c], "partial", locations=locs,
                      reasons={0: "I3-duplicate-inscription-id", 2: "I3-duplicate-inscription-id"}))

    item_ok, meta_ok = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    # no price anywhere for item 2: header has no price; item omits price. Sign a dummy price then strip? 
    # The item has no price and must not be signed for a price it doesn't commit... sig doesn't cover the
    # price field, it covers net. With no price, I2 fails before I6. Use a structurally signed sig over
    # a 10 DOGE net so the only failure is the missing price. Strip price from the item.
    item_np, meta_np = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    h_np = dict(w.header)  # no price
    op = seal_single(h_np, [item_ok, item_np], w.seller, w.seller_pub)
    # item_ok needs a price on the item because the header has none
    # I sealed before stamping price onto item_ok. Fix: stamp then reseal.
    item_ok = dict(item_ok)
    item_ok["price"] = "1000000000"
    op = seal_single(h_np, [item_ok, item_np], w.seller, w.seller_pub)
    locs = {item_ok["inscription_id"]: {"utxo": item_ok["utxo"], "owner": "header"},
            item_np["inscription_id"]: {"utxo": item_np["utxo"], "owner": "header"}}
    cases.append(pack("no-price", op, [meta_ok, meta_np], "partial", locations=locs, reasons={1: "I2-no-price"}))

    item_ok, meta_ok = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    item_dust, meta_dust = w.dog(script=w.seller_script, price="99999", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    item_dust = dict(item_dust)
    item_dust["price"] = "99999"
    h_d = dict(w.header)
    h_d["price"] = "1000000000"
    op = seal_single(h_d, [item_ok, item_dust], w.seller, w.seller_pub)
    locs = {item_ok["inscription_id"]: {"utxo": item_ok["utxo"], "owner": "header"},
            item_dust["inscription_id"]: {"utxo": item_dust["utxo"], "owner": "header"}}
    cases.append(pack("net-below-dust", op, [meta_ok, meta_dust], "partial", locations=locs, reasons={1: "I2-net-below-dust"}))

    item_ok, meta_ok = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    item_moved, meta_moved = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    elsewhere, _ = w.seq.parent(w.seller_script)
    h_m = dict(w.header)
    h_m["price"] = "1000000000"
    op = seal_single(h_m, [item_moved, item_ok], w.seller, w.seller_pub)
    locs = {item_moved["inscription_id"]: {"utxo": txid(elsewhere) + ":0", "owner": "header"},
            item_ok["inscription_id"]: {"utxo": item_ok["utxo"], "owner": "header"}}
    cases.append(pack("dog-not-at-utxo", op, [meta_moved, meta_ok], "partial", locations=locs, reasons={0: "I4-dog-not-at-utxo"}))

    item_ok, meta_ok = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    item_bad, meta_bad = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub, bad_sig=True)
    op = seal_single(h_m, [item_ok, item_bad], w.seller, w.seller_pub)
    locs = {item_ok["inscription_id"]: {"utxo": item_ok["utxo"], "owner": "header"},
            item_bad["inscription_id"]: {"utxo": item_bad["utxo"], "owner": "header"}}
    cases.append(pack("bad-sig", op, [meta_ok, meta_bad], "partial", locations=locs, reasons={1: "I6-bad-sig"}))

    item_e, meta_e = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    item_t, meta_t = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    item_ok, meta_ok = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    item_e = dict(item_e); item_e["expiry"] = EXPIRY
    item_t = dict(item_t); item_t["ts"] = TS
    op = seal_single(h_m, [item_e, item_t, item_ok], w.seller, w.seller_pub)
    locs = {it["inscription_id"]: {"utxo": it["utxo"], "owner": "header"} for it in (item_e, item_t, item_ok)}
    cases.append(pack("reserved-key-in-item", op, [meta_e, meta_t, meta_ok], "partial", locations=locs,
                      reasons={0: "I1-reserved-key", 1: "I1-reserved-key"}))

    # ordering
    cur_item, cur_meta = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    other_item, other_meta = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    op = seal_single(h_m, [cur_item, other_item], w.seller, w.seller_pub)
    locs = {cur_item["inscription_id"]: {"utxo": cur_item["utxo"], "owner": "header"},
            other_item["inscription_id"]: {"utxo": other_item["utxo"], "owner": "header"}}
    current = {cur_item["inscription_id"]: {"utxo": cur_item["utxo"], "ts": TS, "status": "listed"},
               other_item["inscription_id"]: {"utxo": other_item["utxo"], "ts": TS, "status": "listed"}}
    cases.append(pack("equal-ts-single-first", op, [cur_meta, other_meta], "partial", locations=locs, current=current,
                      reasons={0: "I7-not-newer", 1: "I7-not-newer"},
                      extra={"note": "A single order with this ts was applied first. Equal ts does not replace it."}))

    # batch item applied first; a same-ts single does not supersede
    resolved = resolve(json.loads(emit_body(op)), cur_item)
    cases.append({
        "name": "equal-ts-batch-first",
        "result": "ordering",
        "current": {"inscription_id": cur_item["inscription_id"], "utxo": cur_item["utxo"], "ts": TS, "list_id_suffix": ":0"},
        "challenger": {"inscription_id": cur_item["inscription_id"], "utxo": cur_item["utxo"], "ts": TS},
        "supersedes": False,
        "note": "The batch item was applied first. A single order with the same ts and utxo does not replace it.",
    })

    older_a, meta_a = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    older_b, meta_b = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    h_old = dict(h_m)
    h_old["ts"] = TS - 10
    # re-sign items at the same utxo but the sig does not cover ts, so the existing sigs remain valid
    op = seal_single(h_old, [older_a, older_b], w.seller, w.seller_pub)
    locs = {older_a["inscription_id"]: {"utxo": older_a["utxo"], "owner": "header"},
            older_b["inscription_id"]: {"utxo": older_b["utxo"], "owner": "header"}}
    current = {older_a["inscription_id"]: {"utxo": older_a["utxo"], "ts": TS, "status": "listed"},
               older_b["inscription_id"]: {"utxo": older_b["utxo"], "ts": TS, "status": "cancelled"}}
    cases.append(pack("older-batch-noop", op, [meta_a, meta_b], "partial", locations=locs, current=current,
                      reasons={0: "I7-not-newer", 1: "I7-not-newer"},
                      extra={"note": "Re-inscribing an older batch does not revive or replace a newer record, including a cancelled one."}))

    keep, meta_keep = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    fresh, meta_fresh = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    h_new = dict(h_m)
    h_new["ts"] = TS + 100
    # sig does not cover ts; resigning the batch asig is enough. Item sigs stay valid.
    op = seal_single(h_new, [keep, fresh], w.seller, w.seller_pub)
    untouched_id = w.seq.insc()
    locs = {keep["inscription_id"]: {"utxo": keep["utxo"], "owner": "header"},
            fresh["inscription_id"]: {"utxo": fresh["utxo"], "owner": "header"}}
    current = {keep["inscription_id"]: {"utxo": keep["utxo"], "ts": TS, "status": "listed"},
               untouched_id: {"utxo": "11" * 32 + ":0", "ts": TS, "status": "listed"}}
    cases.append(pack("newer-subset", op, [meta_keep, meta_fresh], "valid", locations=locs, current=current,
                      extra={"untouched": [untouched_id],
                             "note": "The newer batch replaces only the inscription it contains. The other listing stays."}))

    # --- whole-batch invalid ---
    def invalid(name, op, reason, ntime=NTIME, order_json=None, signed_body=None):
        body = order_json if order_json is not None else emit_body(op)
        case = {"name": name, "result": "invalid", "reason": reason, "block_ntime": ntime, "body_bytes": len(body.encode()),
                "batch_json": body}
        if signed_body is not None:
            case["signed_body"] = signed_body
        if order_json is None and "asig" in op:
            case["asig_integrity"] = recover_asig(op["asig"], op) == bytes.fromhex(op.get("pubkey", w.seller_pub.hex() if "pubkey" in op else ""))
            # p2sh path uses redeem; integrity checked in checker via recover against known key when pubkey present
            if "pubkey" in op:
                case["asig_integrity"] = recover_asig(op["asig"], op).hex() == op["pubkey"]
        cases.append(case)
        return case

    # items + top-level inscription_id → single order, items ignored
    one, meta = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    single = {
        "p": "dmp", "v": "2", "op": "list", "chain": CHAIN, "pubkey": w.seller_pub.hex(),
        "inscription_id": one["inscription_id"], "utxo": one["utxo"], "price": "1000000000",
        "pay_to": w.pay, "sig": one["sig"], "ts": TS,
        "items": [one, dict(one, inscription_id=w.seq.insc())],
    }
    single["asig"] = sign_asig(w.seller, w.seller_pub, single)
    d = parse_order({k: v for k, v in single.items() if k != "items"}, CHAIN)
    psbt, digest = rebuild(d, bytes.fromhex(meta["parent_tx_hex"]))
    cases.append({
        "name": "items-plus-inscription-id",
        "result": "single-order",
        "reason": "items is an ignored unknown key; this is not a batch",
        "batch": single,
        "batch_json": emit_body(single),
        "parent_tx_hex": meta["parent_tx_hex"],
        "psdt_hex": psbt.hex(),
        "sighash": digest.hex(),
        "note": "Detection (§16.3): both keys present ⇒ single order. The single order itself is valid.",
    })

    a, ma = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    b, mb = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    bare = seal_single(h_m, [a, b], w.seller, w.seller_pub)
    missing = dict(bare)
    del missing["asig"]
    cases.append({"name": "missing-asig", "result": "invalid", "reason": "B3-missing-asig", "block_ntime": NTIME,
                  "batch": missing, "batch_json": json.dumps(missing, separators=(",", ":"))})
    cases.append({"name": "reveal-authorship-without-asig", "result": "invalid", "reason": "B3-missing-asig",
                  "block_ntime": NTIME, "reveal_authored_by_order_key": True,
                  "batch": missing, "batch_json": json.dumps(missing, separators=(",", ":")),
                  "note": "A reveal signed by the order key does not authorize a batch (§16.6 B4). There is no §7.1 fallback."})

    swapped = dict(bare)
    swapped["items"] = [bare["items"][1], bare["items"][0]]
    # asig is still the original. emit_body would re-sign? No, seal already set asig; we keep it.
    invalid("asig-reordered-items", swapped, "B4-asig", signed_body=emit_body(bare))

    edited = json.loads(json.dumps(bare))
    edited["price"] = "1000000001"
    invalid("asig-edited-price", edited, "B4-asig", signed_body=emit_body(bare))

    only, _mo = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
    invalid("one-item", seal_single(h_m, [only], w.seller, w.seller_pub), "B2-item-count")
    invalid("empty-items", seal_single(h_m, [], w.seller, w.seller_pub), "B2-item-count")
    many = []
    for _i in range(51):
        it, _m = w.dog(script=w.seller_script, price="1000000000", pay_to=w.pay, fees=None, signer=w.seller, pub=w.seller_pub)
        many.append(it)
    invalid("fifty-one-items", seal_single(h_m, many, w.seller, w.seller_pub), "B2-item-count")

    not_arr = dict(h_m)
    not_arr["items"] = {"no": "array"}
    not_arr = seal_single(not_arr, not_arr["items"], w.seller, w.seller_pub) if False else None
    op_na = dict(h_m)
    op_na["items"] = {"no": "array"}
    op_na["asig"] = sign_asig(w.seller, w.seller_pub, op_na)
    invalid("items-not-array", op_na, "B2-items-not-array")

    exp = seal_single(dict(h_m, expiry=NTIME), [a, b], w.seller, w.seller_pub)
    # a,b sigs still valid (expiry is not in the item sig). Need a fresh asig over the expiry header.
    invalid("expiry-not-after-ntime", exp, "B6-expiry", ntime=NTIME)
    late = seal_single(dict(h_m, ts=NTIME + 7201, expiry=NTIME + 8000), [a, b], w.seller, w.seller_pub)
    invalid("ts-outside-window", late, "B5-ts-window", ntime=NTIME)

    # duplicate key inside the first item
    raw = emit_body(bare)
    needle = '"sig":"'
    at = raw.find(needle)
    endq = raw.find('"', at + len(needle))
    dup = raw[:endq + 1] + "," + raw[at:endq + 1] + raw[endq + 1:]
    try:
        loads_v2(dup)
        raise RuntimeError("duplicate key was accepted")
    except ValueError:
        pass
    cases.append({"name": "duplicate-key-in-item", "result": "invalid", "reason": "B1-duplicate-key",
                  "block_ntime": NTIME, "batch_json": dup, "body_bytes": len(dup.encode())})

    # body over 32768
    pad_op = dict(bare)
    # grow pad so emit length is 32769
    pad_op["pad"] = ""
    pad_op["asig"] = sign_asig(w.seller, w.seller_pub, pad_op)
    base = len(emit_body(pad_op).encode())
    # adding one x increases canonical by 1 and body by 1, but asig changes and its length stays 88
    # so re-sign after choosing the length. Overhead is stable.
    need = 32769 - base
    pad_op["pad"] = "x" * need
    pad_op.pop("asig")
    pad_op["asig"] = sign_asig(w.seller, w.seller_pub, pad_op)
    blob = emit_body(pad_op)
    if len(blob.encode()) != 32769:
        # asig insertion is outside canonical; pad length is inside. Adjust.
        delta = 32769 - len(blob.encode())
        pad_op["pad"] = "x" * (need + delta)
        pad_op.pop("asig")
        pad_op["asig"] = sign_asig(w.seller, w.seller_pub, pad_op)
        blob = emit_body(pad_op)
    if len(blob.encode()) != 32769:
        raise RuntimeError("pad length " + str(len(blob.encode())))
    cases.append({"name": "body-over-32768", "result": "invalid", "reason": "B2-too-large", "block_ntime": NTIME,
                  "body_bytes": len(blob.encode()), "batch_json": blob, "asig_integrity": True,
                  "note": "32768 is the maximum. 32769 is INVALID. There is no first-50 truncation."})

    forbidden = dict(bare)
    forbidden["utxo"] = a["utxo"]
    forbidden["sig"] = a["sig"]
    forbidden["psdt"] = base64.b64encode(b"not-a-real-psdt").decode()
    forbidden.pop("asig", None)
    forbidden["asig"] = sign_asig(w.seller, w.seller_pub, forbidden)
    invalid("top-level-utxo-sig-psdt", forbidden, "B2-forbidden-key")

    # fill of item 1 on the shared-price batch, plus cancels and consolidation
    shared_op = shared["batch"]
    item1 = shared["items"][1]
    resolved = item1["resolved"]
    sig = bytes.fromhex(resolved["sig"])
    pub = w.seller_pub
    pay_script = address_script(resolved["pay_to"], CHAIN)
    prev = bytes.fromhex(resolved["utxo"].split(":")[0])[::-1]
    vout = int(resolved["utxo"].split(":")[1])
    fill = ser_tx(dict(version=2, locktime=0, ins=[
        dict(prev=b"\x11" * 32, vout=0, script=b"", seq=0xFFFFFFFE),
        dict(prev=prev, vout=vout, script=push(sig) + push(pub), seq=0xFFFFFFFF),
    ], outs=[
        dict(value=100_000, script=pay_script),
        dict(value=item1["net"], script=pay_script),
    ]))
    cons_ins = []
    for row in shared["items"]:
        txh, vo = row["resolved"]["utxo"].split(":")
        cons_ins.append(dict(prev=bytes.fromhex(txh)[::-1], vout=int(vo), script=b"\x51", seq=0xFFFFFFFF))
    consolidation = ser_tx(dict(version=1, locktime=0, ins=cons_ins, outs=[dict(value=100_000, script=w.seller_script)]))
    batch_id = hashlib.sha256(b"dmp-batch-id-shared-price-expiry").hexdigest() + "i0"

    def cancel(list_id, items):
        op = {"p": "dmp", "v": "2", "op": "cancel", "list_id": list_id}
        if items is not None:
            op["items"] = items
        op["asig"] = sign_asig(w.seller, w.seller_pub, op)
        return op

    shared["batch_id"] = batch_id
    shared["fill"] = {"item": 1, "fill_tx_hex": fill.hex(),
                      "expect": {"0": "listed", "1": "filled", "2": "listed"}}
    shared["cancels"] = [
        {"name": "cancel-all", "cancel": cancel(batch_id, None), "result": "valid", "expect_items": [0, 1, 2]},
        {"name": "cancel-item-1", "cancel": cancel(batch_id, [1]), "result": "valid", "expect_items": [1]},
        {"name": "cancel-index-out-of-range", "cancel": cancel(batch_id, [0, 3]), "result": "invalid", "reason": "items-out-of-range"},
        {"name": "cancel-suffix", "cancel": cancel(batch_id + ":0", None), "result": "invalid", "reason": "list-id-suffix"},
    ]
    shared["consolidation_tx_hex"] = consolidation.hex()
    shared["consolidation_expect"] = "every item cancel_kind moved"
    shared["reorg_expect"] = "disconnecting the completing-reveal block removes every item this batch created"

    doc = {
        "spec": "dmp-spec compact-orders.md §16",
        "network": CHAIN,
        "generated_by": "reference/dmp_v2_batch.py",
        "keys": {
            "note": "Regtest test keys. priv is the integer, 32-byte big-endian. Not for mainnet.",
            "seller_priv": 1,
            "seller": w.seller_pub.hex(),
            "other_priv": 2,
            "other": w.other_pub.hex(),
            "pay_to": w.pay,
            "pay_to_2": w.pay2,
            "listing_to": w.listing,
            "p2sh_single_redeem_script": w.p2sh_redeem.hex(),
            "multisig_2of3": {
                "redeem_script": w.multi_redeem.hex(),
                "keys": [pk.hex() for _p, pk in w.multi],
                "privs": [3, 4, 5],
            },
        },
        "cases": cases,
    }
    return doc


RESERVED = {"ts", "expiry", "pubkey", "redeem_script", "chain", "p", "v", "op", "asig", "asigs", "psdt", "psdt_hash", "items"}
FORBIDDEN_TOP = {"inscription_id", "utxo", "sig", "sigs", "psdt", "psdt_hash"}


def check_dup_strings(items, field):
    seen = {}
    bad = set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        v = it.get(field)
        if not isinstance(v, str):
            continue
        if v in seen:
            bad.add(seen[v])
            bad.add(i)
        else:
            seen[v] = i
    return bad


def classify(op):
    if isinstance(op, dict) and "items" in op and "inscription_id" not in op and op.get("op") == "list":
        return "batch"
    return "single"


def batch_error(op, raw, ntime):
    """Return a reason if the whole batch is invalid, else None. Order is §16.6 B1–B6."""
    if raw is not None:
        try:
            loads_v2(raw)
        except ValueError as e:
            if "duplicate" in str(e):
                return "B1-duplicate-key"
            return "B1-duplicate-key"
    if not isinstance(op, dict):
        return "B2-shape"
    if classify(op) != "batch":
        return "not-a-batch"
    if FORBIDDEN_TOP & set(op):
        return "B2-forbidden-key"
    items = op.get("items")
    if not isinstance(items, list):
        return "B2-items-not-array"
    if not 2 <= len(items) <= 50:
        return "B2-item-count"
    if len(raw.encode()) > 32768:
        return "B2-too-large"
    if "pubkey" in op and "redeem_script" in op:
        return "B3-owner"
    if "redeem_script" in op and op["redeem_script"].startswith("52"):
        if "asigs" not in op or "asig" in op:
            return "B3-missing-asig"
    else:
        if "asig" not in op or "asigs" in op:
            return "B3-missing-asig"
    try:
        if "asig" in op:
            pub = bytes.fromhex(op["pubkey"]) if "pubkey" in op else bytes.fromhex(op["redeem_script"][2:68])
            if recover_asig(op["asig"], op) != pub:
                return "B4-asig"
        else:
            _kind, m, keys = parse_redeem(bytes.fromhex(op["redeem_script"]))
            verify_asigs(op, keys, m)
    except (ValueError, Exception):
        return "B4-asig"
    ts = op.get("ts")
    if not isinstance(ts, int) or abs(ts - ntime) > 7200:
        return "B5-ts-window"
    if "expiry" in op and (not isinstance(op["expiry"], int) or not op["expiry"] > ntime):
        return "B6-expiry"
    return None


def item_error(op, items, i, locations, current, parents):
    item = items[i]
    if not isinstance(item, dict):
        return "I1-reserved-key"
    if RESERVED & set(item):
        return "I1-reserved-key"
    resolved = resolve(op, item)
    if "price" not in resolved or "pay_to" not in resolved:
        return "I2-no-price"
    try:
        d = parse_order(resolved, CHAIN)
    except ValueError as e:
        msg = str(e)
        if "dust" in msg:
            return "I2-net-below-dust"
        return "I2-" + msg
    # I3 is evaluated on raw strings of every item, including ones that fail other checks.
    if i in check_dup_strings(items, "utxo"):
        return "I3-duplicate-utxo"
    if i in check_dup_strings(items, "inscription_id"):
        return "I3-duplicate-inscription-id"
    loc = (locations or {}).get(item.get("inscription_id"))
    if loc is None or loc.get("utxo") != item.get("utxo"):
        return "I4-dog-not-at-utxo"
    parent = (parents or {}).get(i)
    if parent:
        try:
            rebuild(d, bytes.fromhex(parent))
        except ValueError as e:
            msg = str(e)
            if "owner" in msg or "P2PKH" in msg or "P2SH" in msg:
                return "I5-wrong-owner"
            return "I6-bad-sig"
    elif loc.get("owner") == "other":
        return "I5-wrong-owner"
    cur = (current or {}).get(item.get("inscription_id"))
    if cur is not None and not supersedes({"utxo": item["utxo"], "ts": op["ts"]}, cur):
        return "I7-not-newer"
    return None


def check(path):
    doc = json.load(open(path, encoding="utf-8"))
    bad = 0

    def fail(name, msg):
        nonlocal bad
        bad += 1
        print(f"FAIL {name}: {msg}")

    for case in doc["cases"]:
        name = case["name"]
        if case["result"] == "ordering":
            got = supersedes(case["challenger"], case["current"])
            if got != case["supersedes"]:
                fail(name, f"supersedes {got}")
            else:
                print(f"OK   {name}")
            continue
        raw = case.get("batch_json")
        op = case.get("batch")
        if op is None and raw and case["result"] != "invalid":
            op = json.loads(raw)
        if case["result"] == "single-order":
            if classify(op) != "single":
                fail(name, "classified as batch")
            else:
                d = parse_order({k: v for k, v in op.items() if k != "items"}, doc["network"])
                psbt, digest = rebuild(d, bytes.fromhex(case["parent_tx_hex"]))
                if psbt.hex() != case["psdt_hex"] or digest.hex() != case["sighash"]:
                    fail(name, "psdt")
                elif recover_asig(op["asig"], op) != bytes.fromhex(op["pubkey"]):
                    fail(name, "asig")
                else:
                    print(f"OK   {name}")
            continue
        if case["result"] == "invalid":
            if case.get("reason") == "B1-duplicate-key":
                try:
                    loads_v2(raw)
                    fail(name, "duplicate accepted")
                except ValueError:
                    print(f"OK   {name}")
                continue
            if op is None:
                op = json.loads(raw)
            # size uses the raw body
            err = batch_error(op, raw, case["block_ntime"])
            if case.get("signed_body"):
                signed = json.loads(case["signed_body"])
                try:
                    pub = bytes.fromhex(signed["pubkey"])
                    ok_signed = recover_asig(signed["asig"], signed) == pub
                    ok_bad = True
                    try:
                        ok_bad = recover_asig(op["asig"], op) != pub
                    except (ValueError, Exception):
                        ok_bad = True
                    if not (ok_signed and ok_bad):
                        fail(name, "asig integrity")
                        continue
                except (ValueError, Exception) as e:
                    fail(name, str(e))
                    continue
            if err != case["reason"]:
                fail(name, f"reason {err} != {case['reason']}")
            else:
                print(f"OK   {name} ({err})")
            continue
        if op is None:
            op = json.loads(raw)
        err = batch_error(op, raw, case["block_ntime"])
        if err:
            fail(name, "batch rejected: " + err)
            continue
        before = bad
        if "asig" in op:
            pub = bytes.fromhex(op["pubkey"]) if "pubkey" in op else bytes.fromhex(op["redeem_script"][2:68])
            if recover_asig(op["asig"], op) != pub or asig_digest(asig_canonical(op)).hex() != case["asig_digest"]:
                fail(name, "asig")
                continue
        items = op["items"]
        for row in case["items"]:
            i = row["n"]
            parents = {row["n"]: row.get("parent_tx_hex") for row in case["items"]}
            got = item_error(op, items, i, case.get("locations"), case.get("current"), parents)
            if row["expect"] == "listed":
                if got:
                    fail(name, f"item {i} rejected {got}")
                    continue
                if "psdt_hex" in row:
                    d = parse_order(row["resolved"], CHAIN)
                    psbt, digest = rebuild(d, bytes.fromhex(row["parent_tx_hex"]))
                    if psbt.hex() != row["psdt_hex"] or digest.hex() != row["sighash"]:
                        fail(name, f"item {i} psdt")
            else:
                if got != row["reason"]:
                    fail(name, f"item {i} reason {got} != {row['reason']}")
        if case.get("fill"):
            from dmp_v2_reconstruct import compliance, parse_tx
            row = case["items"][case["fill"]["item"]]
            d = parse_order(row["resolved"], CHAIN)
            c = compliance(bytes.fromhex(case["fill"]["fill_tx_hex"]), d)
            if not c["seller_paid_ok"]:
                fail(name, "fill is not a fill of the selected item")
            for j, other in enumerate(case["items"]):
                if j == case["fill"]["item"] or other["expect"] != "listed":
                    continue
                od = parse_order(other["resolved"], CHAIN)
                oc = compliance(bytes.fromhex(case["fill"]["fill_tx_hex"]), od)
                if oc["seller_paid_ok"]:
                    fail(name, f"fill also fills item {j}")
        if bad == before:
            print(f"OK   {name}")
    # cancel + consolidation checked against the shared case
    for case in doc["cases"]:
        if "cancels" not in case:
            continue
        n = len(case["batch"]["items"])
        for c in case["cancels"]:
            op = c["cancel"]
            try:
                pub = bytes.fromhex(case["batch"]["pubkey"])
                recover_asig(op["asig"], op)
                sig_ok = recover_asig(op["asig"], op) == pub
            except (ValueError, Exception):
                sig_ok = False
            lid = op.get("list_id", "")
            structural = None
            if ":" in lid.split("i", 1)[-1] or (isinstance(lid, str) and lid.count(":") and lid.rsplit(":", 1)[-1].isdigit() and len(lid) > 66):
                structural = "list-id-suffix"
            # a batch id is 64 hex + i + index, no extra colon. Suffix form is <id>:<n> with id containing 'i'.
            if lid.count(":") >= 1 and lid.rpartition(":")[0].endswith(tuple("0123456789abcdef")) is False:
                pass
            if ":" in lid[64:]:
                structural = "list-id-suffix"
            items = op.get("items")
            if structural is None and items is not None:
                if not isinstance(items, list) or not items or items != sorted(items) or len(set(items)) != len(items):
                    structural = "items-malformed"
                elif any((not isinstance(x, int)) or x < 0 or x >= n for x in items):
                    structural = "items-out-of-range"
            if c["result"] == "invalid":
                if not sig_ok or structural != c["reason"]:
                    fail(c["name"], f"sig_ok={sig_ok} structural={structural}")
                else:
                    print(f"OK   {c['name']}")
            else:
                if not sig_ok or structural is not None:
                    fail(c["name"], f"sig_ok={sig_ok} structural={structural}")
                else:
                    print(f"OK   {c['name']}")
        if "consolidation_tx_hex" not in case:
            continue
        from dmp_v2_reconstruct import compliance
        raw = bytes.fromhex(case["consolidation_tx_hex"])
        for row in case["items"]:
            d = parse_order(row["resolved"], CHAIN)
            if compliance(raw, d)["seller_paid_ok"]:
                fail(case["name"], "consolidation looked like a fill")
        print(f"OK   {case['name']} consolidation")
    print("ALL MATCH" if not bad else f"{bad} MISMATCHES")
    return bad


def main():
    write_examples()
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        sys.exit(check(sys.argv[2] if len(sys.argv) > 2 else VEC))
    doc = build()
    os.makedirs(os.path.dirname(VEC), exist_ok=True)
    json.dump(doc, open(VEC, "w", encoding="utf-8", newline="\n"), indent=2)
    open(VEC, "a", encoding="utf-8").write("\n")
    print(f"wrote {VEC} ({os.path.getsize(VEC)} bytes, {len(doc['cases'])} cases)")
    sys.exit(check(VEC))


if __name__ == "__main__":
    main()
