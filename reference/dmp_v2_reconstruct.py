#!/usr/bin/env python3
"""Independent ÐMP v2 compact-order reconstructor (compact-orders.md §3–§8, incl. §5.4 P2SH, §7.2 asig).

Written from the spec only: no dogex, dojak or bitcoinjs code. Uses hashlib and the
`ecdsa` package for signature verification; tx/PSBT serialization, base58 and the
legacy SIGHASH_SINGLE|ANYONECANPAY digest are implemented here.

  dmp_v2_reconstruct.py vectors <vectors.json>
  dmp_v2_reconstruct.py state <dmp_v2_state_vectors.json>      (§6.1, §7.1, §8 location/layout, §9, §10)
  dmp_v2_reconstruct.py v1 <dmp_v1_psdt_vectors.json>           (§2 v1 PSDT hardening, §15)
  dmp_v2_reconstruct.py order <order.json> (--parent-hex HEX | --rpc URL --rpc-auth user:pass)
REGTEST/TESTING TOOL. It never signs or broadcasts anything.
"""
import base64, hashlib, json, struct, sys, urllib.request
import ecdsa
from ecdsa.util import sigdecode_der

N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
CHAINS = {"dogecoin": (0x1E, 0x16), "dogecoin-testnet": (0x71, 0xC4), "dogecoin-regtest": (0x6F, 0xC4)}
LEAD, MIN_NET, SIGHASH = 100_000, 100_000, 0x83
MAX_ROYALTY, MAX_MARKET, DEFAULT_SHARE = 2500, 2000, 5000

def sha256d(b): return hashlib.sha256(hashlib.sha256(b).digest()).digest()
def hash160(b): return hashlib.new("ripemd160", hashlib.sha256(b).digest()).digest()
def varint(n):
    if n < 0xFD: return bytes([n])
    if n <= 0xFFFF: return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF: return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)
def varbytes(b): return varint(len(b)) + b

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def b58check_decode(s):
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    raw = b"\x00" * (len(s) - len(s.lstrip("1"))) + raw
    data, chk = raw[:-4], raw[-4:]
    if sha256d(data)[:4] != chk: raise ValueError("bad checksum")
    return data

def address_script(addr, chain):
    d = b58check_decode(addr)
    if len(d) != 21: raise ValueError("bad address length")
    pkh, sh = CHAINS[chain]
    if d[0] == pkh: return b"\x76\xa9\x14" + d[1:] + b"\x88\xac"
    if d[0] == sh: return b"\xa9\x14" + d[1:] + b"\x87"
    raise ValueError("address is not P2PKH/P2SH on this chain")

# ── transactions ────────────────────────────────────────────────────────────
class R:
    def __init__(self, b): self.b, self.i = b, 0
    def take(self, n): v = self.b[self.i:self.i + n]; self.i += n; return v
    def u32(self): return struct.unpack("<I", self.take(4))[0]
    def vi(self):
        f = self.take(1)[0]
        return f if f < 0xFD else struct.unpack({0xFD: "<H", 0xFE: "<I", 0xFF: "<Q"}[f], self.take({0xFD: 2, 0xFE: 4, 0xFF: 8}[f]))[0]
def parse_tx(raw):
    r = R(raw); v = struct.unpack("<i", r.take(4))[0]
    ins = [dict(prev=r.take(32), vout=r.u32(), script=r.take(r.vi()), seq=r.u32()) for _ in range(r.vi())]
    outs = [dict(value=struct.unpack("<Q", r.take(8))[0], script=r.take(r.vi())) for _ in range(r.vi())]
    lt = r.u32()
    assert r.i == len(raw), "trailing bytes"
    return dict(version=v, ins=ins, outs=outs, locktime=lt)
def ser_tx(t):
    b = struct.pack("<i", t["version"]) + varint(len(t["ins"]))
    for i in t["ins"]: b += i["prev"] + struct.pack("<I", i["vout"]) + varbytes(i["script"]) + struct.pack("<I", i["seq"])
    b += varint(len(t["outs"]))
    for o in t["outs"]: b += struct.pack("<Q", o["value"]) + varbytes(o["script"])
    return b + struct.pack("<I", t["locktime"])
def txid(raw): return sha256d(raw)[::-1].hex()

# ── order rules (spec-v2 §3.2) ──────────────────────────────────────────────
def dec_str(v, name, maxv=None):
    if not isinstance(v, str) or not v.isdigit() or (len(v) > 1 and v[0] == "0") or len(v) > 20: raise ValueError(f"{name} must be a decimal string")
    n = int(v)
    if maxv is not None and n > maxv: raise ValueError(f"{name} out of range")
    return n

def strict_der(sig):
    # BIP66 rules, then low-S.
    if len(sig) < 8 or len(sig) > 72 or sig[0] != 0x30 or sig[1] != len(sig) - 2: raise ValueError("sig is not strict DER")
    lr = sig[3]
    if sig[2] != 0x02 or lr == 0 or 5 + lr >= len(sig): raise ValueError("sig is not strict DER")
    ls = sig[5 + lr]
    if sig[4 + lr] != 0x02 or ls == 0 or lr + ls + 6 != len(sig): raise ValueError("sig is not strict DER")
    r, s = sig[4:4 + lr], sig[6 + lr:]
    for x in (r, s):
        if x[0] & 0x80 or (len(x) > 1 and x[0] == 0 and not x[1] & 0x80): raise ValueError("sig is not strict DER")
    if int.from_bytes(s, "big") > N // 2: raise ValueError("sig must be low-S")
    return sig

def parse_order(o, chain):
    if o.get("p") != "dmp" or o.get("v") != "2" or o.get("op") != "list": raise ValueError("not a v2 list")
    if o.get("chain") != chain: raise ValueError("chain mismatch")
    if "psdt_hash" in o: raise ValueError("psdt_hash is venue-only")
    t, vout = o["utxo"].split(":")
    if len(t) != 64 or t != t.lower() or str(int(vout)) != vout: raise ValueError("utxo")
    price = dec_str(o.get("price"), "price")
    if price <= 0: raise ValueError("price")
    if "pubkey" in o and "redeem_script" in o: raise ValueError("pubkey must be absent when redeem_script is present")
    if "redeem_script" in o:
        rs = o["redeem_script"]
        if not isinstance(rs, str) or bytes.fromhex(rs).hex() != rs: raise ValueError("redeem_script must be lowercase hex")
        redeem = bytes.fromhex(rs); tpl = parse_redeem(redeem)
    else:
        pk = bytes.fromhex(o["pubkey"])
        if len(pk) != 33 or pk[0] not in (2, 3) or pk.hex() != o["pubkey"]: raise ValueError("pubkey")
        redeem, tpl = None, ("pkh", 1, [pk])
    multi = tpl[0] == "multi"
    if multi:
        if "sig" in o: raise ValueError("multisig orders carry sigs, not sig")
        if not isinstance(o.get("sigs"), list): raise ValueError("sigs required (array) for a multisig redeem_script")
        if len(o["sigs"]) != tpl[1]: raise ValueError("sigs must hold exactly m signatures")
        sig_hex = o["sigs"]
        if "asig" in o: raise ValueError("multisig orders authorize with asigs, not asig")
    else:
        if "sigs" in o: raise ValueError("sigs is only for multisig redeem_script orders")
        if "asigs" in o: raise ValueError("asigs is only for multisig orders")
        sig_hex = [o["sig"]]
    sigs = []
    for h in sig_hex:
        if not isinstance(h, str): raise ValueError("sig must be a hex string")
        sig = bytes.fromhex(h)
        if sig.hex() != h: raise ValueError("sig hex")
        if sig[-1] != SIGHASH: raise ValueError("sig hashtype must be 0x83")
        strict_der(sig[:-1]); sigs.append(sig)
    f = o.get("fees", {})
    if not isinstance(f, dict): raise ValueError("fees")
    rb = dec_str(f["royalty_bps"], "royalty_bps", 10000) if "royalty_bps" in f else 0
    mb = dec_str(f["market_bps"], "market_bps", 10000) if "market_bps" in f else 0
    share = dec_str(f["listing_share_bps"], "listing_share_bps", 10000) if "listing_share_bps" in f else DEFAULT_SHARE
    if rb > MAX_ROYALTY or mb > MAX_MARKET: raise ValueError("fee above cap")
    if rb and "royalty_to" not in f: raise ValueError("royalty_to required")
    for k in ("royalty_to", "listing_to"):
        if k in f: address_script(f[k], chain)
    if not isinstance(o.get("ts"), int) or ("expiry" in o and not isinstance(o["expiry"], int)): raise ValueError("ts/expiry must be integers")
    royalty = price * rb // 10000 if rb and f.get("royalty_to") else 0
    market = price * mb // 10000
    listing = market * share // 10000 if market and f.get("listing_to") else 0
    net = price - royalty - market
    if net < MIN_NET: raise ValueError("signed seller output below dust")
    return dict(o=o, txid=t, vout=int(vout), price=price, tpl=tpl, redeem=redeem, keys=tpl[2], sigs=sigs, pay=address_script(o["pay_to"], chain),
                split=dict(royalty=royalty, market=market, listing=listing, settlement=market - listing, net=net), fees=f, chain=chain)

def template(d):
    return dict(version=2, locktime=0,
                ins=[dict(prev=b"\x00" * 32, vout=0, script=b"", seq=0xFFFFFFFE),
                     dict(prev=bytes.fromhex(d["txid"])[::-1], vout=d["vout"], script=b"", seq=0xFFFFFFFF)],
                outs=[dict(value=LEAD, script=d["pay"]), dict(value=d["split"]["net"], script=d["pay"])])

def sighash_single_acp(tx, index, script_code):
    # Legacy digest: ANYONECANPAY keeps only the signing input; SINGLE keeps outputs[0..=index]
    # with the earlier ones blanked to (-1, empty script).
    t = dict(version=tx["version"], locktime=tx["locktime"],
             ins=[dict(tx["ins"][index], script=script_code)],
             outs=[dict(value=0xFFFFFFFFFFFFFFFF, script=b"") for _ in range(index)] + [tx["outs"][index]])
    return sha256d(ser_tx(t) + struct.pack("<I", SIGHASH))

def p2pkh(pk): return b"\x76\xa9\x14" + hash160(pk) + b"\x88\xac"
def p2sh(redeem): return b"\xa9\x14" + hash160(redeem) + b"\x87"

# ---- spec-v2 §5.4 P2SH-held dogs ----
def parse_redeem(s):
    """("pk", 1, [k]) for <pk> OP_CHECKSIG; ("multi", m, keys) for OP_m <pk..> OP_n OP_CHECKMULTISIG."""
    bad = "unsupported redeem_script (supported: <pk> OP_CHECKSIG, or m-of-n OP_CHECKMULTISIG with n <= 15)"
    if len(s) > 520: raise ValueError("redeem_script larger than 520 bytes")
    def key(k):
        if len(k) != 33 or k[0] not in (2, 3): raise ValueError("redeem_script key is not a valid public key")
        x = int.from_bytes(k[1:], "big")
        if x >= _P or pow((x ** 3 + 7) % _P, (_P - 1) // 2, _P) != 1: raise ValueError("redeem_script key is not a valid public key")
        return k
    if s[:1] == b"\x21":
        if len(s) != 35 or s[34] != 0xAC: raise ValueError(bad)
        return ("pk", 1, [key(s[1:34])])
    if not s or not 0x51 <= s[0] <= 0x5F: raise ValueError(bad)
    m, i, keys = s[0] - 0x50, 1, []
    while i < len(s) and s[i] == 0x21:
        if i + 34 > len(s): raise ValueError(bad)
        k = key(s[i + 1:i + 34])
        if k in keys: raise ValueError("redeem_script repeats a key")
        keys.append(k); i += 34
    n = len(keys)
    if not 1 <= n <= 15 or len(s) != i + 2 or s[i] != 0x50 + n or s[i + 1] != 0xAE: raise ValueError(bad)
    if m > n: raise ValueError("redeem_script requires more signatures than it has keys")
    return ("multi", m, keys)

def push(b):
    n = len(b)
    return (bytes([n]) if n <= 75 else bytes([0x4C, n]) if n <= 255 else b"\x4d" + struct.pack("<H", n)) + b

def dog_script_sig(d):
    if d["redeem"] is None: return push(d["sigs"][0]) + push(d["keys"][0])
    ss = (b"\x00" if d["tpl"][0] == "multi" else b"") + b"".join(push(x) for x in d["sigs"]) + push(d["redeem"])
    if len(ss) > 1650: raise ValueError("scriptSig larger than 1650 bytes")
    return ss

def _verifies(k, sig, digest):
    try: return ecdsa.VerifyingKey.from_string(k, curve=ecdsa.SECP256k1).verify_digest(sig[:-1], digest, sigdecode=sigdecode_der)
    except ecdsa.BadSignatureError: return False

def match_sigs(d, digest):
    """OP_CHECKMULTISIG walk: keys in script order, each sig consumes keys until one verifies it."""
    out, k = [], 0
    for sig in d["sigs"]:
        while True:
            if k >= len(d["keys"]): raise ValueError("seller signature does not verify" if d["tpl"][0] != "multi" else "sigs do not satisfy the redeem_script")
            k += 1
            if _verifies(d["keys"][k - 1], sig, digest): out.append(d["keys"][k - 1]); break
    return out

def rebuild(d, parent_raw):
    if txid(parent_raw) != d["txid"]: raise ValueError("parent tx does not match utxo txid")
    parent = parse_tx(parent_raw)
    want = p2pkh(d["keys"][0]) if d["redeem"] is None else p2sh(d["redeem"])
    if d["vout"] >= len(parent["outs"]) or parent["outs"][d["vout"]]["script"] != want:
        raise ValueError("dog output is not P2PKH of pubkey (not the current owner key)" if d["redeem"] is None else "dog output is not P2SH of redeem_script")
    tx = template(d)
    digest = sighash_single_acp(tx, 1, p2pkh(d["keys"][0]) if d["redeem"] is None else d["redeem"])
    signers = match_sigs(d, digest)
    # PSBT: magic, global {00: unsigned tx}, in0 {}, in1 {00 parent, 02<pk> sig (ascending pk), 03 sighash[, 04 redeem]}, out0 {}, out1 {}
    psbt = b"psbt\xff" + varbytes(b"\x00") + varbytes(ser_tx(tx)) + b"\x00"
    psbt += b"\x00"
    psbt += varbytes(b"\x00") + varbytes(parent_raw)
    for pk, sig in sorted(zip(signers, d["sigs"])):
        psbt += varbytes(b"\x02" + pk) + varbytes(sig)
    psbt += varbytes(b"\x03") + varbytes(struct.pack("<I", SIGHASH))
    if d["redeem"] is not None: psbt += varbytes(b"\x04") + varbytes(d["redeem"])
    psbt += b"\x00"
    psbt += b"\x00\x00"
    return psbt, digest

def fill_tag(tx):
    for o in tx["outs"]:
        s = o["script"]
        if len(s) >= 6 and s[0] == 0x6A and s[1] == 4 and s[2:6] == b"dmp2" and len(s) > 7 and s[6] == len(s) - 7:
            return s[7:]
    return None

def compliance(fill_raw, d):
    tx = parse_tx(fill_raw)
    seller_ok = (len(tx["ins"]) > 1 and tx["ins"][1]["prev"] == bytes.fromhex(d["txid"])[::-1] and tx["ins"][1]["vout"] == d["vout"]
                 and len(tx["outs"]) > 1 and tx["outs"][1] == dict(value=d["split"]["net"], script=d["pay"]))
    paid = lambda script: sum(o["value"] for i, o in enumerate(tx["outs"]) if i != 1 and o["script"] == script)
    s, f, c = d["split"], d["fees"], dict(seller_paid_ok=seller_ok, royalty_ok=None, listing_fee_ok=None, settlement_fee_ok=None)
    if s["royalty"]: c["royalty_ok"] = paid(address_script(f["royalty_to"], d["chain"])) >= s["royalty"]
    if s["listing"]: c["listing_fee_ok"] = paid(address_script(f["listing_to"], d["chain"])) >= s["listing"]
    venue = fill_tag(tx)
    if venue is not None and s["settlement"]: c["settlement_fee_ok"] = paid(venue) >= s["settlement"]
    c["fee_split_ok"] = seller_ok and False not in (c["royalty_ok"], c["listing_fee_ok"], c["settlement_fee_ok"])
    return c

# ---- spec-v2 §7.2 asig (independent: own canonicalizer + own pubkey recovery) ----
ASIG_TAG = "dmp-v2-asig:"
MAGIC = b"Dogecoin Signed Message:\n"
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798, 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)

def _canon(v):
    if isinstance(v, str):
        if any(not (0x20 <= ord(c) <= 0x7E) or c in '"\\' for c in v): raise ValueError("asig: bad string")
        return '"' + v + '"'
    if isinstance(v, int) and not isinstance(v, bool):
        if not 0 <= v <= 2**53 - 1: raise ValueError("asig: integer out of range")
        return str(v)
    if isinstance(v, list):
        return "[" + ",".join(_canon(x) for x in v) + "]"
    if isinstance(v, dict):
        ks = sorted(v, key=lambda k: k.encode())
        return "{" + ",".join(_canon(k) + ":" + _canon(v[k]) for k in ks) + "}"
    raise ValueError("asig: only strings, integers, arrays and objects")

def asig_canonical(op): return _canon({k: x for k, x in op.items() if k not in ("asig", "asigs", "psdt")})
def asig_digest(canonical):
    m = (ASIG_TAG + canonical).encode("ascii")
    return sha256d(varbytes(MAGIC) + varbytes(m))

def _add(a, b):
    if a is None: return b
    if b is None: return a
    if a[0] == b[0] and (a[1] + b[1]) % _P == 0: return None
    l = ((3 * a[0] * a[0]) * pow(2 * a[1], -1, _P) if a == b else (b[1] - a[1]) * pow(b[0] - a[0], -1, _P)) % _P
    x = (l * l - a[0] - b[0]) % _P
    return (x, (l * (a[0] - x) - a[1]) % _P)
def _mul(k, pt):
    r = None
    while k:
        if k & 1: r = _add(r, pt)
        pt, k = _add(pt, pt), k >> 1
    return r
def _compress(pt): return bytes([2 + (pt[1] & 1)]) + pt[0].to_bytes(32, "big")

def recover_asig(a, op):
    """Key a canonical, low-S compact asig recovers to over the canonical op."""
    if not isinstance(a, str): raise ValueError("asig must be a base64 string")
    try: raw = base64.b64decode(a, validate=True)
    except Exception: raise ValueError("asig not base64")
    if len(raw) != 65 or base64.b64encode(raw).decode() != a: raise ValueError("asig must be canonical base64 of 65 bytes")
    if not 31 <= raw[0] <= 34: raise ValueError("asig header must be 31..34")
    r, s_ = int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big")
    if not (0 < r < _N and 0 < s_ < _N): raise ValueError("asig r/s out of range")
    if s_ > _N // 2: raise ValueError("asig must be low-S")
    e = int.from_bytes(asig_digest(asig_canonical(op)), "big")
    recid = raw[0] - 31
    x = r + (recid >> 1) * _N
    if x >= _P: raise ValueError("asig recovery failed")
    y = pow((x ** 3 + 7) % _P, (_P + 1) // 4, _P)
    if (y & 1) != (recid & 1): y = _P - y
    R = (x, y)
    ri = pow(r, -1, _N)
    Q = _add(_mul(s_ * ri % _N, R), _mul((-e * ri) % _N, _G))
    if Q is None: raise ValueError("asig recovery failed")
    pk = _compress(Q)
    # cross-check with the ecdsa library verify (non-recovery path)
    from ecdsa.util import sigdecode_string
    ecdsa.VerifyingKey.from_string(pk, curve=ecdsa.SECP256k1).verify_digest(raw[1:], asig_digest(asig_canonical(op)), sigdecode=sigdecode_string)
    return pk

def verify_asig(op, pk):
    if recover_asig(op.get("asig"), op) != pk: raise ValueError("asig does not recover/verify for the order key")

def verify_asigs(op, keys, m):
    """Multisig: exactly m asigs, recovering distinct keys of the script in strictly increasing key position."""
    a = op.get("asigs")
    if not isinstance(a, list): raise ValueError("asigs must be an array of base64 strings")
    if len(a) != m: raise ValueError("asigs must hold exactly m signatures")
    nxt = 0
    for x in a:
        pk = recover_asig(x, op)
        if pk not in keys: raise ValueError("asigs signer is not a key of the redeem_script")
        pos = keys.index(pk)
        if pos < nxt: raise ValueError("asigs must be by distinct keys, in redeem_script key order")
        nxt = pos + 1

def verify_auth(op, tpl):
    """§7.2 for an op about an order with template tpl: asig (single key) or asigs (m of n)."""
    if tpl[0] == "multi":
        if "asig" in op: raise ValueError("multisig orders authorize with asigs, not asig")
        verify_asigs(op, tpl[2], tpl[1])
    else:
        if "asigs" in op: raise ValueError("asigs is only for multisig orders")
        verify_asig(op, tpl[2][0])
def has_auth(op): return "asig" in op or "asigs" in op

# ---- spec-v2 §4.2 duplicate keys, §6.1 newer-ts-wins ----
def _no_dup_hook(pairs):
    seen = set()
    for k, _ in pairs:
        if k in seen: raise ValueError(f"duplicate JSON key {k!r}")
        seen.add(k)
    return dict(pairs)

def loads_v2(text):
    """Strict v2 parse: a duplicate object key at any depth makes the op INVALID."""
    return json.loads(text, object_pairs_hook=_no_dup_hook)

def supersedes(new, cur):
    """new may replace the indexed order cur only on a different outpoint or a strictly newer ts."""
    return new["utxo"] != cur["utxo"] or int(new["ts"]) > int(cur["ts"])

def check_vectors(path):
    v = json.load(open(path)); chain = v.get("network", "dogecoin-regtest"); bad = 0
    for case in v["valid"]:
        d = parse_order(case["order"], chain)
        psbt, digest = rebuild(d, bytes.fromhex(case["parent_tx_hex"]))
        if "psdt" in case["order"] and base64.b64decode(case["order"]["psdt"]) != psbt: raise SystemExit(f"{case['name']}: embedded psdt differs")
        fill = bytes.fromhex(case["fill_tx_hex"]); c = compliance(fill, d)
        ss = dog_script_sig(d)
        ok = (psbt.hex() == case["psdt_hex"] and digest.hex() == case["sighash"] and txid(fill) == case["fill_txid"]
              and c["seller_paid_ok"] and c["fee_split_ok"] == case["compliance"]["fee_split_ok"]
              and ss.hex() == case["dog_script_sig_hex"] and parse_tx(fill)["ins"][1]["script"] == ss)
        if has_auth(case["order"]):
            verify_auth(case["order"], d["tpl"])
            ok = ok and asig_canonical(case["order"]) == case["asig_canonical"] and asig_digest(case["asig_canonical"]).hex() == case["asig_digest"]
        if d["tpl"] and d["tpl"][0] == "multi" and "asigs" not in case["order"]:
            ok = False  # §7: a multisig list is authorized only by asigs (no reveal path)
        bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} valid   {case['name']:<26} psdt {len(psbt)} B sha256 {hashlib.sha256(psbt).hexdigest()[:16]}… fill {txid(fill)[:16]}… fee_split_ok={c['fee_split_ok']}")
    for case in v["valid"]:
        loads_v2(case["order_json"])
    for case in v["invalid"]:
        try:
            if "order_json" in case: loads_v2(case["order_json"])
            d = parse_order(case["order"], chain); rebuild(d, bytes.fromhex(case["parent_tx_hex"]))
            if has_auth(case["order"]): verify_auth(case["order"], d["tpl"])
            err = None
        except (ValueError, KeyError, ecdsa.BadSignatureError) as e:
            err = str(e) or type(e).__name__
        bad += err is None
        print(f"{'OK  ' if err else 'FAIL'} invalid {case['name']:<26} rejected: {err}")
    for case in v.get("ordering", []):
        got = supersedes(case["new"], case["current"]); ok = got == case["supersedes"]; bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} order   {case['name']:<26} supersedes={got}")
    for case in v.get("cancel", []):
        tpl = parse_redeem(bytes.fromhex(case["order_redeem_script"])) if "order_redeem_script" in case else ("pkh", 1, [bytes.fromhex(case["order_pubkey"])])
        try: verify_auth(case["cancel"], tpl); err = None
        except (ValueError, ecdsa.BadSignatureError) as e: err = str(e) or type(e).__name__
        ok = (err is None) == case["valid"]; bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} cancel  {case['name']:<26} {'accepted' if err is None else 'rejected: ' + err}")
    print("ALL MATCH" if not bad else f"{bad} MISMATCHES"); return bad


# ---- spec-v2 §8.1 inscription location (ord sat flow, FIFO) ----
def locate(in_values, inscriptions, out_values):
    """inscriptions: [(id, input_index, offset_in_input)]. Returns {id: (vout, offset) | None (lost to fee)}."""
    starts, acc = [], 0
    for v in in_values: starts.append(acc); acc += v
    res = {}
    for ins_id, i, off in inscriptions:
        if off >= in_values[i]: raise ValueError("offset outside its input")
        a, base = starts[i] + off, 0
        res[ins_id] = None
        for vout, v in enumerate(out_values):
            if base <= a < base + v: res[ins_id] = (vout, a - base); break
            base += v
    return res

def op_return_kind(tx):
    """Informative (§8.3): what the fill's first OP_RETURN is. dmp2 venue tag, a JSON tag such as ds, or other."""
    for o in tx["outs"]:
        s = o["script"]
        if not s or s[0] != 0x6A: continue
        if fill_tag(dict(outs=[o])) is not None: return "dmp2"
        data = s[2:2 + s[1]] if len(s) > 1 and s[1] <= 75 else s[3:3 + s[2]] if len(s) > 2 and s[1] == 0x4C else b""
        try:
            j = json.loads(data)
            if isinstance(j, dict) and j: return "json:" + min(j)  # smallest key: independent of JSON library key order
        except ValueError: pass
        return "other"
    return None

def classify_spend(fill_raw, d, prevout_values, dog_offset):
    """§8.2: is this spend of the order utxo a fill (sale) or a cancel-by-move, and where does the dog land."""
    tx = parse_tx(fill_raw); dog_prev = (bytes.fromhex(d["txid"])[::-1], d["vout"])
    in_values, dog_in = [], None
    for i, x in enumerate(tx["ins"]):
        if (x["prev"], x["vout"]) == dog_prev: dog_in = i; in_values.append(d["dog_value"])
        else: in_values.append(prevout_values[f"{x['prev'][::-1].hex()}:{x['vout']}"])
    loc = locate(in_values, [("dog", dog_in, dog_offset)], [o["value"] for o in tx["outs"]])["dog"]
    shape = dog_in == 1 and len(tx["outs"]) > 1 and tx["outs"][1] == dict(value=d["split"]["net"], script=d["pay"])
    owner = tx["outs"][loc[0]]["script"] if loc else None
    order_owner = p2sh(d["redeem"]) if d["redeem"] is not None else p2pkh(d["keys"][0])
    sale = shape and owner is not None and owner != order_owner
    return dict(is_fill=shape, outcome="settle_pending" if sale else "cancelled_moved", dog=dict(vout=loc[0], offset=loc[1]) if loc else None,
                buyer_script=owner if sale else None, compliance=compliance(fill_raw, d) if sale else None, op_return_kind=op_return_kind(tx))

def script_address(script, chain):
    pkh, sh = CHAINS[chain]
    if len(script) == 25 and script[:3] == b"\x76\xa9\x14": v, h = pkh, script[3:23]
    elif len(script) == 23 and script[:2] == b"\xa9\x14": v, h = sh, script[2:22]
    else: return None
    raw = bytes([v]) + h; raw += sha256d(raw)[:4]
    n = int.from_bytes(raw, "big"); out = ""
    A = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    while n: n, r = divmod(n, 58); out = A[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\x00"))) + out

# ---- spec-v2 §7.1 reveal authorship ----
def _pushes(script):
    out, i = [], 0
    while i < len(script):
        op = script[i]; i += 1
        if 1 <= op <= 75: out.append(script[i:i + op]); i += op
        elif op == 0x4C: n = script[i]; out.append(script[i + 1:i + 1 + n]); i += 1 + n
        elif op == 0x4D: n = struct.unpack("<H", script[i:i + 2])[0]; out.append(script[i + 2:i + 2 + n]); i += 2 + n
        elif op == 0: out.append(b"")
        elif 0x51 <= op <= 0x60: out.append(bytes([op - 0x50]))
        else: return None  # a non-push opcode: not a doginals reveal scriptSig
    return out

def reveal_authors(reveal_raw):
    keys = []
    for x in parse_tx(reveal_raw)["ins"]:
        p = _pushes(x["script"])
        if not p or len(p) < 2 or not p[-2] or p[-2][-1] != 0x01: continue
        redeem = p[-1]
        if len(redeem) >= 35 and redeem[0] == 0x21 and redeem[34] == 0xAD and redeem[1:34] not in keys: keys.append(redeem[1:34])
    return keys

# ---- spec-v2 §6.1 / §9 / §10 state machine over abstract blocks ----
def run_state(steps, window=7200, depth=6):
    chain = []  # connected blocks, oldest first; state is a pure function of the chain (§10)
    def fold():
        rec, utxo, seen = None, "u1", {}
        for b in chain:
            h, t = b["height"], b["time"]
            if rec and rec["status"] == "listed" and "expiry" in rec["o"] and t >= rec["o"]["expiry"]: rec["status"] = "expired"
            for op in b["ops"]:
                if op["op"] == "list":
                    if abs(op["ts"] - t) > window or ("expiry" in op and op["expiry"] <= t) or op["utxo"] != utxo: continue
                    if rec and rec["status"] in ("listed", "cancelled", "expired") and not (op["utxo"] != rec["o"]["utxo"] or op["ts"] > rec["o"]["ts"]): continue
                    if rec and rec["status"] in ("settle_pending", "settled"): continue
                    rec = dict(o=op, status="listed"); seen[op["id"]] = op
                elif op["op"] == "cancel":
                    if rec and rec["o"]["id"] == op["list_id"] and rec["status"] == "listed": rec.update(status="cancelled", cancel_kind="inscription")
                elif op["op"] == "spend":
                    if op["kind"] == "fill" and rec and rec["status"] in ("listed", "cancelled", "expired") and rec.get("cancel_kind") != "moved":
                        rec.update(after_cancel=rec["status"] == "cancelled", after_expiry=rec["status"] == "expired", status="settle_pending", fill_height=h)
                        rec.pop("cancel_kind", None)
                    else:
                        if rec and rec["status"] in ("listed", "cancelled", "expired"): rec.update(status="cancelled", cancel_kind="moved")
                    utxo = op.get("new_utxo", "fill")
            if rec and rec["status"] == "settle_pending" and h - rec["fill_height"] + 1 >= depth: rec["status"] = "settled"
        return rec
    got = []
    for st in steps:
        if "connect" in st: chain.append(st["connect"])
        else:
            if not chain or chain[-1]["height"] != st["disconnect"]: raise ValueError("disconnect is not the tip")
            chain.pop()
        r = fold()
        view = dict(status=r["status"] if r else None)
        if r:
            view.update(current=r["o"]["id"])
            if "cancel_kind" in r: view["cancel_kind"] = r["cancel_kind"]
            if "after_cancel" in r: view.update(after_cancel=r["after_cancel"], after_expiry=r["after_expiry"])
        got.append(view)
    return got

def check_state_vectors(path):
    v = json.load(open(path)); chain = v.get("network", "dogecoin-regtest"); bad = 0
    def report(ok, kind, name, info):
        nonlocal bad; bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {kind:<7} {name:<34} {info}")
    for c in v["location"]:
        ins = [(x["id"], i, x["offset"]) for i, inp in enumerate(c["inputs"]) for x in inp["inscriptions"]]
        got = {k: (dict(vout=r[0], offset=r[1]) if r else None) for k, r in locate([i["value"] for i in c["inputs"]], ins, c["outputs"]).items()}
        report(got == c["expect"], "locate", c["name"], got)
    for c in v["genesis"]:
        got = None if c.get("complete") is False else dict(id=c["parts"][0] + "i0", location=f"{c['parts'][-1]}:0:0")
        report(got == c["expect"], "genesis", c["name"], got)
    for c in v["fill_layout"]:
        d = parse_order(c["order"], chain); rebuild(d, bytes.fromhex(c["parent_tx_hex"]))
        d["dog_value"] = parse_tx(bytes.fromhex(c["parent_tx_hex"]))["outs"][d["vout"]]["value"]
        r = classify_spend(bytes.fromhex(c["fill_tx_hex"]), d, c["prevout_values"], c["dog_offset_in_utxo"])
        e = c["expect"]
        comp = None if r["compliance"] is None else {k: r["compliance"][k] for k in ("seller_paid_ok", "royalty_ok", "listing_fee_ok", "settlement_fee_ok", "fee_split_ok")}
        ok = (r["is_fill"] == e["is_fill"] and r["outcome"] == e["outcome"] and r["dog"] == e["dog"] and comp == e["compliance"]
              and (script_address(r["buyer_script"], chain) if r["buyer_script"] else None) == e["buyer"] and r["op_return_kind"] == e["op_return_kind"]
              and txid(bytes.fromhex(c["fill_tx_hex"])) == c["fill_txid"])
        report(ok, "layout", c["name"], f"{r['outcome']} dog={r['dog']} tag={r['op_return_kind']}")
    for c in v["reveal_authorship"]:
        got = bytes.fromhex(c["order_pubkey"]) in reveal_authors(bytes.fromhex(c["reveal_tx_hex"]))
        report(got == c["authorized"], "reveal", c["name"], f"authorized={got}")
    for c in v["state"]:
        got = run_state(c["steps"], v["constants"]["ts_window_s"], v["constants"]["settle_depth"])
        want = [st["expect"] for st in c["steps"]]
        ok = all(all(g.get(k) == w[k] for k in w) and (w["status"] is not None or g["status"] is None) for g, w in zip(got, want))
        report(ok, "state", c["name"], " → ".join(g["status"] or "none" for g in got))
    print("ALL MATCH" if not bad else f"{bad} MISMATCHES"); return bad

# ---- v1 list PSDT check (spec-v2 §2 v1 hardening, §15). P2PKH dog prevout only.
def _psbt_maps(b, i):
    def rd(i):
        n = b[i]; i += 1
        if n == 0xFD: n = int.from_bytes(b[i:i + 2], "little"); i += 2
        elif n == 0xFE: n = int.from_bytes(b[i:i + 4], "little"); i += 4
        return n, i
    m = []
    while True:
        kl, i = rd(i)
        if kl == 0: return m, i
        k = b[i:i + kl]; i += kl; vl, i = rd(i); m.append((k, b[i:i + vl])); i += vl

def v1_psdt_check(psdt_b64):
    """Return (classification, detail): ok | invalid_sig | postage_unsafe | unsupported."""
    b = base64.b64decode(psdt_b64)
    if b[:5] != b"psbt\xff": return "unsupported", "not a PSBT"
    g, i = _psbt_maps(b, 5); utx = dict(g).get(b"\x00")
    if utx is None: return "unsupported", "no unsigned tx"
    t = parse_tx(utx); ins = []
    for _ in t["ins"]:
        m, i = _psbt_maps(b, i); ins.append(m)
    signed = [n for n, m in enumerate(ins) if any(k[:1] == b"\x02" for k, _ in m)]
    if len(signed) != 1: return "invalid_sig", "must sign exactly the dog"
    n = signed[0]; m = ins[n]
    parent = next((v for k, v in m if k == b"\x00"), None)
    if parent is None or n >= len(t["outs"]): return "invalid_sig", "missing parent tx or same-index output"
    if txid(parent) != t["ins"][n]["prev"][::-1].hex(): return "invalid_sig", "parent tx does not match prevout"
    spk = parse_tx(parent)["outs"][t["ins"][n]["vout"]]["script"]
    for k, sig in ((k[1:], v) for k, v in m if k[:1] == b"\x02"):
        if sig[-1] != SIGHASH: return "invalid_sig", "hashtype is not 0x83"
        try: strict_der(sig[:-1])
        except ValueError as e: return "invalid_sig", str(e)
        if p2pkh(k) != spk: return "unsupported" if spk[:2] == b"\xa9\x14" else "invalid_sig", "key does not own the dog prevout"
        if not _verifies(k, sig, sighash_single_acp(t, n, spk)): return "invalid_sig", "signature does not verify"
    if n == 0: return "postage_unsafe", "dog signed at input 0: its sat always lands in locked output 0"
    return "ok", "dog at input %d" % n

def check_v1_vectors(path):
    bad = 0
    for c in json.load(open(path))["v1_lists"]:
        got, why = v1_psdt_check(c["psdt"])
        ok = got == c["expect"]; bad += not ok
        print(("ok   " if ok else "FAIL ") + c["name"], got, "-", why)
    print("ALL MATCH" if not bad else "%d MISMATCH" % bad)
    return bad

def main(a):
    if a[:1] == ["vectors"]: sys.exit(1 if check_vectors(a[1]) else 0)
    if a[:1] == ["v1"]: sys.exit(1 if check_v1_vectors(a[1]) else 0)
    if a[:1] == ["state"]: sys.exit(1 if check_state_vectors(a[1]) else 0)
    if a[:1] == ["order"]:
        o = loads_v2(open(a[1]).read() if a[1] != "-" else sys.stdin.read())
        chain = o.get("chain")
        if "--parent-hex" in a: parent = bytes.fromhex(a[a.index("--parent-hex") + 1])
        else:
            url, auth = a[a.index("--rpc") + 1], a[a.index("--rpc-auth") + 1]
            req = urllib.request.Request(url, json.dumps({"id": 0, "method": "getrawtransaction", "params": [o["utxo"].split(":")[0], 0]}).encode(),
                                         {"Authorization": "Basic " + base64.b64encode(auth.encode()).decode(), "content-type": "application/json"})
            parent = bytes.fromhex(json.load(urllib.request.urlopen(req))["result"])
        d = parse_order(o, chain); psbt, digest = rebuild(d, parent)
        if has_auth(o): verify_auth(o, d["tpl"])
        print(json.dumps(dict(psbt_hex=psbt.hex(), sha256=hashlib.sha256(psbt).hexdigest(), sighash=digest.hex(), seller_net_koinu=d["split"]["net"],
                              dog_script_sig_hex=dog_script_sig(d).hex())))
        return
    print(__doc__); sys.exit(2)

if __name__ == "__main__": main(sys.argv[1:])
