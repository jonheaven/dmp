#!/usr/bin/env python3
"""Reference checker for the ÐMP collection registry (collection-registry.md, spec revision 1.1).

  collection_registry.py check vectors/collection_registry_vectors.json   # recompute and compare
  collection_registry.py gen > vectors/collection_registry_vectors.json   # regenerate the vectors
  collection_registry.py root ids.txt                                     # root of a list (one id per line)
  collection_registry.py chunk ids.txt out_dir                            # write text chunks for a list

Written from the spec. Pure functions only: chain facts (inscriber, holder, heights) are inputs.
TESTING TOOL. The only keys it signs with are the public test scalars 0x01..01, 0x02..02 and
0x03..03. It never touches the network.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import ecdsa
from ecdsa.util import sigencode_string_canonize

CANONICAL_ID = re.compile(r"^[0-9a-f]{64}i(0|[1-9][0-9]*)$")
ROOT_RE = re.compile(r"^[0-9a-f]{64}$")
COUNT_RE = re.compile(r"^[1-9][0-9]*$")
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")
ROYALTY_RE = re.compile(r"^([0-9]|[1-9][0-9]{1,2}|1[0-9]{3}|2[0-4][0-9]{2}|2500)$")

MAX_CHUNK_BYTES = 32_768
MAX_CHUNKS = 256
MAX_MEMBERS = 100_000
CHUNK_WINDOW = 1_440
IMMUTABLE_PATCH_KEYS = ("slug", "chain", "type", "parent_inscription_id", "creator_address")
MUTABLE_PATCH_KEYS = ("name", "description", "image", "links", "royalty_address", "royalty_bps",
                      "criteria", "retired")

# ── ids, root, chunks ─────────────────────────────────────────────────────────────────────────

def is_canonical_id(s: Any) -> bool:
    return isinstance(s, str) and CANONICAL_ID.match(s) is not None


def canonical_list(ids: List[str]) -> bytes:
    for i in ids:
        if not is_canonical_id(i):
            raise ValueError(f"non-canonical id {i!r}")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate id")
    return "\n".join(sorted(ids)).encode("ascii")


def members_root(ids: List[str]) -> str:
    return hashlib.sha256(canonical_list(ids)).hexdigest()


class ChunkError(Exception):
    pass


def parse_chunk(body: bytes) -> List[str]:
    if len(body) > MAX_CHUNK_BYTES:
        raise ChunkError("too_large")
    if body[:1] == b"{":
        try:
            obj = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ChunkError("bad_json")
        if not isinstance(obj, dict) or obj.get("p") != "dmp" or obj.get("op") != "collection-chunk":
            raise ChunkError("not_a_chunk")
        if "v" in obj and obj["v"] != "1.0":
            raise ChunkError("bad_version")
        ids = obj.get("ids")
        if not isinstance(ids, list) or not ids:
            raise ChunkError("no_ids")
    else:
        text = body.decode("ascii", errors="strict") if all(b < 0x80 for b in body) else None
        if text is None:
            raise ChunkError("bad_text")
        if text.endswith("\n"):
            text = text[:-1]
        if not text:
            raise ChunkError("no_ids")
        ids = text.split("\n")
    for i in ids:
        if not is_canonical_id(i):
            raise ChunkError("bad_id")
    if len(set(ids)) != len(ids):
        raise ChunkError("duplicate_id")
    return list(ids)


def text_chunks(ids: List[str], max_bytes: int = MAX_CHUNK_BYTES) -> List[bytes]:
    """Sorted ids, each followed by LF, greedily packed into bodies of at most max_bytes."""
    out: List[bytes] = []
    cur: List[bytes] = []
    size = 0
    for i in sorted(ids):
        line = (i + "\n").encode("ascii")
        if cur and size + len(line) > max_bytes:
            out.append(b"".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line)
    if cur:
        out.append(b"".join(cur))
    return out

# ── canonical JSON and Dogecoin signed messages ───────────────────────────────────────────────

def strip_sigs(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: strip_sigs(x) for k, x in v.items() if k not in ("sig", "sig_msg")}
    if isinstance(v, list):
        return [strip_sigs(x) for x in v]
    return v


def canonical_message(obj: Dict[str, Any]) -> str:
    return json.dumps(strip_sigs(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compact_size(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "little")
    if n <= 0xFFFFFFFF:
        return b"\xfe" + n.to_bytes(4, "little")
    return b"\xff" + n.to_bytes(8, "little")


def message_hash(message: str) -> bytes:
    data = message.encode("utf-8")
    payload = b"\x19Dogecoin Signed Message:\n" + _compact_size(len(data)) + data
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58check(payload: bytes) -> str:
    raw = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    n = int.from_bytes(raw, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    pad = len(raw) - len(raw.lstrip(b"\0"))
    return "1" * pad + s


def hash160(b: bytes) -> bytes:
    return hashlib.new("ripemd160", hashlib.sha256(b).digest()).digest()


def p2pkh_address(pubkey: bytes, version: int = 0x1E) -> str:
    return b58check(bytes([version]) + hash160(pubkey))


def _point_bytes(vk: ecdsa.VerifyingKey) -> bytes:
    return vk.to_string("compressed")


def test_key(byte: int) -> Tuple[ecdsa.SigningKey, str]:
    sk = ecdsa.SigningKey.from_string(bytes([byte]) * 32, curve=ecdsa.SECP256k1)
    return sk, p2pkh_address(_point_bytes(sk.get_verifying_key()))


def sign_message(sk: ecdsa.SigningKey, message: str) -> str:
    digest = message_hash(message)
    sig = sk.sign_digest_deterministic(digest, hashfunc=hashlib.sha256, sigencode=sigencode_string_canonize)
    want = _point_bytes(sk.get_verifying_key())
    for recid, cand in enumerate(ecdsa.VerifyingKey.from_public_key_recovery_with_digest(
            sig, digest, ecdsa.SECP256k1, hashfunc=hashlib.sha256)):
        if _point_bytes(cand) == want:
            return base64.b64encode(bytes([27 + 4 + recid]) + sig).decode()
    raise RuntimeError("recovery id not found")


def _recover(digest: bytes, r: int, s: int, recid: int):
    """SEC 1 §4.1.6 public key recovery for one recovery id. Returns a VerifyingKey or None."""
    curve = ecdsa.SECP256k1
    n = curve.order
    G = curve.generator
    p = curve.curve.p()
    if not (0 < r < n and 0 < s < n):
        return None
    x = r + (recid >> 1) * n
    if x >= p:
        return None
    alpha = (pow(x, 3, p) + 7) % p
    beta = pow(alpha, (p + 1) // 4, p)
    if (beta * beta) % p != alpha:
        return None
    y = beta if (beta & 1) == (recid & 1) else p - beta
    R = ecdsa.ellipticcurve.PointJacobi(curve.curve, x, y, 1, n)
    e = int.from_bytes(digest, "big")
    Q = (R * s + G * ((-e) % n)) * pow(r, -1, n)
    try:
        return ecdsa.VerifyingKey.from_public_point(Q.to_affine(), curve=curve)
    except Exception:
        return None


def verify_message(address: str, sig_b64: str, message: str) -> bool:
    """Dogecoin Core `verifymessage`: header 27..34, strict recovery id, P2PKH address match."""
    try:
        raw = base64.b64decode(sig_b64, validate=True)
    except (ValueError, TypeError):
        return False
    if len(raw) != 65 or raw[0] < 27 or raw[0] > 34:
        return False
    recid = (raw[0] - 27) & 3
    compressed = bool((raw[0] - 27) & 4)
    r = int.from_bytes(raw[1:33], "big")
    s = int.from_bytes(raw[33:65], "big")
    vk = _recover(message_hash(message), r, s, recid)
    if vk is None:
        return False
    pub = vk.to_string("compressed") if compressed else b"\x04" + vk.to_string("raw")
    return p2pkh_address(pub) == address


# ── manifests ─────────────────────────────────────────────────────────────────────────────────

def committed_manifest_errors(m: Dict[str, Any]) -> List[str]:
    """Shape and signature rules of collection-registry §4 (status `invalid` at once if any)."""
    errs: List[str] = []
    if m.get("p") != "dmp" or m.get("op") != "collection" or m.get("v", "1.0") != "1.0":
        errs.append("not_a_collection")
    if not isinstance(m.get("slug"), str) or not SLUG_RE.match(m["slug"]):
        errs.append("bad_slug")
    if m.get("type") != "fixed":
        errs.append("type_must_be_fixed")
    c = m.get("criteria")
    if not isinstance(c, dict) or c.get("mode") != "explicit":
        errs.append("mode_must_be_explicit")
        c = {}
    if not isinstance(c.get("members_root"), str) or not ROOT_RE.match(c["members_root"]):
        errs.append("bad_members_root")
    cnt = c.get("members_count")
    if not isinstance(cnt, str) or not COUNT_RE.match(cnt) or int(cnt) > MAX_MEMBERS:
        errs.append("bad_members_count")
    ch = c.get("members_chunks")
    if (not isinstance(ch, list) or not 1 <= len(ch) <= MAX_CHUNKS
            or not all(is_canonical_id(x) for x in ch) or len(set(ch)) != len(ch)):
        errs.append("bad_members_chunks")
    if "inscription_ids" in c or "signed_list" in m:
        errs.append("inline_list_with_root")
    if m.get("supply_locked") is True and m.get("supply") != cnt:
        errs.append("supply_mismatch")
    if "royalty_bps" in m and not (isinstance(m["royalty_bps"], str) and ROYALTY_RE.match(m["royalty_bps"])):
        errs.append("MUST-054")
    creator = m.get("creator_address")
    if not isinstance(creator, str) or not isinstance(m.get("sig"), str) \
            or not verify_message(creator, m["sig"], canonical_message(m)):
        errs.append("bad_sig")
    return errs


def resolve(m: Dict[str, Any], H: int, chunks: Dict[str, Dict[str, Any]], at_height: int) -> Dict[str, Any]:
    """§4.2. chunks: id -> {"body": hex, "complete_height": int}; absent = not inscribed."""
    c = m["criteria"]
    deadline = H + CHUNK_WINDOW
    bodies: List[bytes] = []
    for cid in c["members_chunks"]:
        info = chunks.get(cid)
        if info is None or info["complete_height"] > deadline or info["complete_height"] > at_height:
            if at_height > deadline:
                return {"status": "invalid", "reason": "chunk_missing"}
            return {"status": "pending"}
        bodies.append(bytes.fromhex(info["body"]))
    seen: set = set()
    union: List[str] = []
    parsed: List[List[str]] = []
    for b in bodies:
        try:
            parsed.append(parse_chunk(b))
        except ChunkError:
            return {"status": "invalid", "reason": "chunk_invalid"}
    for ids in parsed:
        for i in ids:
            if i in seen:
                return {"status": "invalid", "reason": "duplicate_member"}
            seen.add(i)
            union.append(i)
    if len(union) != int(c["members_count"]):
        return {"status": "invalid", "reason": "count_mismatch"}
    if members_root(union) != c["members_root"]:
        return {"status": "invalid", "reason": "root_mismatch"}
    return {"status": "valid", "members": sorted(union)}

# ── tiers ─────────────────────────────────────────────────────────────────────────────────────

def tier(facts: Dict[str, Any]) -> Dict[str, Any]:
    """§5. facts: origin, H, parent?: {exists_before_H, holder_at_H_minus_1, inscriber},
    members?: [{id, inscriber, complete_height}] (None = member set unknown)."""
    S = facts["origin"]
    H = facts["H"]
    p = facts.get("parent")
    if p and p.get("exists_before_H") and p.get("holder_at_H_minus_1") == S:
        return {"tier": "verified", "verified_by": "parent_holder"}
    if p and p.get("exists_before_H") and p.get("inscriber") == S:
        return {"tier": "verified", "verified_by": "parent_inscriber"}
    members = facts.get("members")
    if members:
        k = sum(1 for x in members if x.get("inscriber") == S and x.get("complete_height", H) < H)
        if 2 * k > len(members):
            return {"tier": "verified", "verified_by": "member_inscriber"}
    return {"tier": "community", "verified_by": None}

# ── conflicts ─────────────────────────────────────────────────────────────────────────────────

def rank_key(m: Dict[str, Any]) -> Tuple[int, List[int]]:
    return (0 if m["tier"] == "verified" else 1, list(m["position"]))


def conflicts(manifests: List[Dict[str, Any]]) -> Dict[str, Any]:
    """§6. manifests: {id, slug, tier, position:[height, tx_index, n], status, retired, members}."""
    live = [m for m in manifests if m["status"] == "valid" and not m.get("retired")]
    live.sort(key=rank_key)
    slugs: Dict[str, str] = {}
    primary: Dict[str, str] = {}
    for m in live:
        slugs.setdefault(m["slug"], m["id"])
        for x in m.get("members", []):
            primary.setdefault(x, m["id"])
    return {"slug_owner": dict(sorted(slugs.items())), "primary": dict(sorted(primary.items()))}

# ── updates ───────────────────────────────────────────────────────────────────────────────────

def check_update(state: Dict[str, Any], u: Dict[str, Any]) -> Dict[str, Any]:
    """§7. state: {root_id, head, signer, retired}. Returns accept/reject and the new signer."""
    if u.get("p") != "dmp" or u.get("op") != "collection-update":
        return {"accepted": False, "reason": "not_an_update"}
    if state.get("retired"):
        return {"accepted": False, "reason": "retired"}
    if u.get("collection_id") != state["root_id"]:
        return {"accepted": False, "reason": "wrong_collection"}
    if u.get("supersedes") != state["head"]:
        return {"accepted": False, "reason": "stale_supersedes"}
    patch = u.get("patch")
    if not isinstance(patch, dict):
        return {"accepted": False, "reason": "bad_patch"}
    if any(k in patch for k in IMMUTABLE_PATCH_KEYS):
        return {"accepted": False, "reason": "immutable_key"}
    if "royalty_bps" in patch and not (isinstance(patch["royalty_bps"], str) and ROYALTY_RE.match(patch["royalty_bps"])):
        return {"accepted": False, "reason": "MUST-054"}
    if "retired" in patch and patch["retired"] is not True:
        return {"accepted": False, "reason": "bad_retired"}
    msg = canonical_message(u)
    if not isinstance(u.get("sig"), str) or not verify_message(state["signer"], u["sig"], msg):
        return {"accepted": False, "reason": "bad_sig"}
    signer = state["signer"]
    h = u.get("handover")
    if h is not None:
        if not isinstance(h, dict) or not isinstance(h.get("to"), str) or not isinstance(h.get("sig"), str):
            return {"accepted": False, "reason": "bad_handover"}
        if not verify_message(h["to"], h["sig"], msg):
            return {"accepted": False, "reason": "bad_handover_sig"}
        signer = h["to"]
    return {"accepted": True, "signer": signer, "retired": patch.get("retired") is True}

# ── cost ──────────────────────────────────────────────────────────────────────────────────────

def estimate_cost(body_sizes: List[int], fee_rate_koinu_per_kb: int = 1_000_000) -> Dict[str, int]:
    """Informative §9 estimate. ~1,450 body bytes per Doginals transaction plus one commit."""
    txs = 0
    fee = 0
    for b in body_sizes:
        n = -(-b // 1450) + 1
        txs += n
        fee += -(-((b + 330 * n) * fee_rate_koinu_per_kb) // 1000)
        fee += 1_000_000 + 100_000  # soft-dust fee and postage on the final reveal
    return {"inscriptions": len(body_sizes), "transactions": txs, "koinu": fee}

# ── vectors ───────────────────────────────────────────────────────────────────────────────────

def fake_id(n: int, idx: int = 0) -> str:
    return hashlib.sha256(f"registry-member-{n}".encode()).hexdigest() + f"i{idx}"


def gen() -> Dict[str, Any]:
    skA, A = test_key(1)
    skB, B = test_key(2)
    skC, C = test_key(3)
    ids_small = [
        "b" * 64 + "i9",
        "b" * 64 + "i10",
        "a" * 64 + "i0",
        "0123456789abcdef" * 4 + "i2",
    ]
    root_cases = [
        {"name": "byte order, i10 before i9", "ids": ids_small},
        {"name": "single member", "ids": ["c" * 64 + "i0"]},
    ]
    for rc in root_cases:
        rc["canonical_list"] = canonical_list(rc["ids"]).decode()
        rc["members_root"] = members_root(rc["ids"])

    good_text = ("a" * 64 + "i0\n" + "b" * 64 + "i1\n").encode()
    chunk_cases = [
        {"name": "text, trailing LF", "body": good_text},
        {"name": "text, no trailing LF", "body": good_text[:-1]},
        {"name": "json form", "body": json.dumps({"p": "dmp", "op": "collection-chunk", "ids": ["a" * 64 + "i0"]}).encode()},
        {"name": "CRLF", "body": good_text.replace(b"\n", b"\r\n")},
        {"name": "uppercase hex", "body": ("A" * 64 + "i0\n").encode()},
        {"name": "leading zero index", "body": ("a" * 64 + "i01\n").encode()},
        {"name": "empty line", "body": ("a" * 64 + "i0\n\n" + "b" * 64 + "i1\n").encode()},
        {"name": "bare json array", "body": json.dumps(["a" * 64 + "i0"]).encode()},
        {"name": "duplicate id", "body": ("a" * 64 + "i0\n" + "a" * 64 + "i0\n").encode()},
        {"name": "too large", "body": b"".join((fake_id(n) + "\n").encode() for n in range(490))},
        {"name": "exactly 489 ids", "body": b"".join((fake_id(n) + "\n").encode() for n in range(489))},
    ]
    for cc in chunk_cases:
        try:
            ids = parse_chunk(cc["body"])
            cc["expect"] = {"ok": True, "count": len(ids)}
        except ChunkError as e:
            cc["expect"] = {"ok": False, "reason": str(e)}
        cc["body_hex"] = cc.pop("body").hex()

        # 150 members in 3 small text chunks (any size up to 32,768 bytes is allowed).
    members = [fake_id(n) for n in range(150)]
    bodies = text_chunks(members, 4_000)
    chunk_ids = [hashlib.sha256(b"chunk" + bytes([i])).hexdigest() + "i0" for i in range(len(bodies))]
    manifest = {
        "p": "dmp", "v": "1.0", "op": "collection", "chain": "dogecoin",
        "slug": "registry-test-dogs", "name": "Registry Test Dögs",
        "creator_address": A, "royalty_address": A, "royalty_bps": "500",
        "type": "fixed", "supply": "150", "supply_locked": True,
        "criteria": {"mode": "explicit", "members_root": members_root(members),
                     "members_count": "150", "members_chunks": chunk_ids},
        "description": "Test vector. Not a real collection.",
        "links": {"website": "https://doginals.lol"},
        "ts": 1795000000,
    }
    manifest["sig"] = sign_message(skA, canonical_message(manifest))
    H = 5_200_000
    chunk_map = {cid: {"body": b.hex(), "complete_height": H - 1} for cid, b in zip(chunk_ids, bodies)}
    late = dict(chunk_map)
    late[chunk_ids[2]] = {"body": bodies[2].hex(), "complete_height": H + CHUNK_WINDOW + 1}
    swapped = dict(chunk_map)
    swapped[chunk_ids[2]] = {"body": (bodies[2][:-67] + (fake_id(5000) + "\n").encode()).hex(),
                             "complete_height": H - 1}
    short = dict(chunk_map)
    short[chunk_ids[2]] = {"body": bodies[2][:-67].hex(), "complete_height": H - 1}
    dup = dict(chunk_map)
    dup[chunk_ids[2]] = {"body": (bodies[2][:-67] + (sorted(members)[0] + "\n").encode()).hex(), "complete_height": H - 1}
    bad = dict(chunk_map)
    bad[chunk_ids[1]] = {"body": bodies[1].replace(b"\n", b"\r\n", 1).hex(), "complete_height": H - 1}
    resolution = []
    for name, cmap, at in [
        ("all chunks before H", chunk_map, H),
        ("one chunk not yet inscribed", {k: v for k, v in chunk_map.items() if k != chunk_ids[1]}, H + 10),
        ("one chunk still missing after the window", {k: v for k, v in chunk_map.items() if k != chunk_ids[1]}, H + CHUNK_WINDOW + 1),
        ("one chunk lands after the window", late, H + CHUNK_WINDOW + 5),
        ("a chunk with a different id", swapped, H),
        ("a chunk missing one id", short, H),
        ("the same id in two chunks", dup, H),
        ("a malformed chunk", bad, H),
    ]:
        r = resolve(manifest, H, cmap, at)
        resolution.append({"name": name, "at_height": at, "chunks": cmap,
                           "expect": {"status": r["status"], "reason": r.get("reason"),
                                      "member_count": len(r.get("members", []))}})

    tampered = json.loads(json.dumps(manifest))
    tampered["criteria"]["members_count"] = "149"
    inline_too = json.loads(json.dumps(manifest))
    inline_too["signed_list"] = {"inscription_ids": members[:1]}
    inline_too["sig"] = sign_message(skA, canonical_message(inline_too))
    manifest_cases = [
        {"name": "valid committed manifest", "manifest": manifest},
        {"name": "count edited after signing", "manifest": tampered},
        {"name": "inline list next to a root", "manifest": inline_too},
    ]
    for mc in manifest_cases:
        mc["canonical_message"] = canonical_message(mc["manifest"])
        mc["expect_errors"] = committed_manifest_errors(mc["manifest"])

    tier_cases = []
    def tc(name, facts):
        tier_cases.append({"name": name, "facts": facts, "expect": tier(facts)})
    mem = lambda who, n_creator, n_other, h=H - 10: (
        [{"id": fake_id(i), "inscriber": who, "complete_height": h} for i in range(n_creator)]
        + [{"id": fake_id(10_000 + i), "inscriber": C, "complete_height": h} for i in range(n_other)])
    tc("parent holder", {"origin": A, "H": H, "parent": {"exists_before_H": True, "holder_at_H_minus_1": A, "inscriber": C}})
    tc("parent inscriber, parent sold", {"origin": A, "H": H, "parent": {"exists_before_H": True, "holder_at_H_minus_1": C, "inscriber": A}})
    tc("parent created in block H does not count", {"origin": A, "H": H, "parent": {"exists_before_H": False, "holder_at_H_minus_1": None, "inscriber": A}})
    tc("member majority 6 of 10", {"origin": A, "H": H, "members": mem(A, 6, 4)})
    tc("exactly half is not a majority", {"origin": A, "H": H, "members": mem(A, 5, 5)})
    tc("first member only (collector)", {"origin": A, "H": H, "members": mem(A, 1, 9)})
    tc("members inscribed in block H do not count", {"origin": A, "H": H, "members": mem(A, 6, 4, H)})
    tc("community signer", {"origin": B, "H": H, "members": mem(A, 10, 0)})

    X, Y = fake_id(1), fake_id(2)
    conflict_cases = []
    def cfc(name, ms):
        conflict_cases.append({"name": name, "manifests": ms, "expect": conflicts(ms)})
    base = lambda id_, slug, t, pos, members_, status="valid", retired=False: {
        "id": id_, "slug": slug, "tier": t, "position": pos, "status": status,
        "retired": retired, "members": members_}
    m1, m2, m3 = ("1" * 64 + "i0"), ("2" * 64 + "i0"), ("3" * 64 + "i0")
    cfc("verified beats an earlier community claim",
        [base(m1, "dogs", "community", [100, 1, 0], [X, Y]), base(m2, "dogs", "verified", [200, 5, 0], [X])])
    cfc("earliest verified wins",
        [base(m2, "dogs", "verified", [200, 5, 0], [X]), base(m3, "dogs", "verified", [300, 1, 0], [X, Y])])
    cfc("same block, lower tx index wins",
        [base(m1, "dogs", "community", [100, 7, 0], [X]), base(m2, "dogs", "community", [100, 3, 0], [Y])])
    cfc("pending and retired manifests take no part",
        [base(m1, "dogs", "verified", [100, 1, 0], [X], retired=True),
         base(m2, "dogs", "verified", [150, 1, 0], [X], status="pending"),
         base(m3, "dogs", "community", [300, 1, 0], [X])])

    root_id = m1
    upd = {"p": "dmp", "v": "1.0", "op": "collection-update", "chain": "dogecoin",
           "collection_id": root_id, "update_of": root_id, "supersedes": root_id,
           "patch": {"description": "Now with docs"}, "ts": 1795000100}
    upd["sig"] = sign_message(skA, canonical_message(upd))
    stale = dict(upd, supersedes="4" * 64 + "i0")
    stale["sig"] = sign_message(skA, canonical_message(stale))
    wrong = dict(upd)
    wrong["sig"] = sign_message(skB, canonical_message(upd))
    slugpatch = dict(upd, patch={"slug": "other"})
    slugpatch["sig"] = sign_message(skA, canonical_message(slugpatch))
    hand = {"p": "dmp", "v": "1.0", "op": "collection-update", "chain": "dogecoin",
            "collection_id": root_id, "update_of": root_id, "supersedes": root_id,
            "patch": {}, "handover": {"to": B}, "ts": 1795000200}
    hmsg = canonical_message(hand)
    hand["sig"] = sign_message(skA, hmsg)
    hand["handover"]["sig"] = sign_message(skB, hmsg)
    hand_unaccepted = json.loads(json.dumps(hand))
    hand_unaccepted["handover"]["sig"] = sign_message(skC, hmsg)
    retire = dict(upd, patch={"retired": True})
    retire["sig"] = sign_message(skA, canonical_message(retire))
    state = {"root_id": root_id, "head": root_id, "signer": A, "retired": False}
    update_cases = []
    for name, u, st in [
        ("metadata patch", upd, state),
        ("stale supersedes", stale, state),
        ("signed by someone else", wrong, state),
        ("slug is immutable", slugpatch, state),
        ("handover signed by both keys", hand, state),
        ("handover the new key never signed", hand_unaccepted, state),
        ("retire", retire, state),
        ("old signer after handover", upd, dict(state, signer=B)),
    ]:
        update_cases.append({"name": name, "state": st, "update": u,
                             "canonical_message": canonical_message(u), "expect": check_update(st, u)})

    cost = {"name": "10,000 members at 0.01 DOGE/kB",
            "members": 10_000,
            "chunk_body_bytes": [len(b) for b in text_chunks([fake_id(n) for n in range(10_000)])]}
    cost["chunks"] = len(cost["chunk_body_bytes"])
    cost["manifest_body_bytes"] = 1_900
    cost["fee_rate_koinu_per_kb"] = 1_000_000
    cost["expect"] = estimate_cost(cost["chunk_body_bytes"] + [cost["manifest_body_bytes"]], cost["fee_rate_koinu_per_kb"])

    return {
        "spec": "collection-registry.md (ÐMP spec revision 1.1)",
        "keys": {"A": {"secret": "01" * 32, "address": A},
                 "B": {"secret": "02" * 32, "address": B},
                 "C": {"secret": "03" * 32, "address": C}},
        "constants": {"max_chunk_bytes": MAX_CHUNK_BYTES, "max_chunks": MAX_CHUNKS,
                      "max_members": MAX_MEMBERS, "chunk_window": CHUNK_WINDOW},
        "root": root_cases,
        "chunk_parse": chunk_cases,
        "manifest": manifest_cases,
        "manifest_H": H,
        "manifest_members_root": manifest["criteria"]["members_root"],
        "chunk_bodies_hex": [b.hex() for b in bodies],
        "resolution": resolution,
        "tier": tier_cases,
        "conflict": conflict_cases,
        "update": update_cases,
        "cost": cost,
    }


def check(path: str) -> int:
    v = json.load(open(path, encoding="utf-8"))
    fails = 0

    def eq(name, got, want):
        nonlocal fails
        if got != want:
            fails += 1
            print(f"FAIL {name}: got {got!r} want {want!r}")

    for rc in v["root"]:
        eq(rc["name"], canonical_list(rc["ids"]).decode(), rc["canonical_list"])
        eq(rc["name"], members_root(rc["ids"]), rc["members_root"])
    for cc in v["chunk_parse"]:
        try:
            got = {"ok": True, "count": len(parse_chunk(bytes.fromhex(cc["body_hex"])))}
        except ChunkError as e:
            got = {"ok": False, "reason": str(e)}
        eq(cc["name"], got, cc["expect"])
    for mc in v["manifest"]:
        eq(mc["name"], canonical_message(mc["manifest"]), mc["canonical_message"])
        eq(mc["name"], committed_manifest_errors(mc["manifest"]), mc["expect_errors"])
    m = v["manifest"][0]["manifest"]
    for rc in v["resolution"]:
        r = resolve(m, v["manifest_H"], rc["chunks"], rc["at_height"])
        eq(rc["name"], {"status": r["status"], "reason": r.get("reason"),
                        "member_count": len(r.get("members", []))}, rc["expect"])
    for tc in v["tier"]:
        eq(tc["name"], tier(tc["facts"]), tc["expect"])
    for cc in v["conflict"]:
        eq(cc["name"], conflicts(cc["manifests"]), cc["expect"])
    for uc in v["update"]:
        eq(uc["name"], canonical_message(uc["update"]), uc["canonical_message"])
        eq(uc["name"], check_update(uc["state"], uc["update"]), uc["expect"])
    c = v["cost"]
    eq("cost", estimate_cost(c["chunk_body_bytes"] + [c["manifest_body_bytes"]], c["fee_rate_koinu_per_kb"]), c["expect"])
    total = (len(v["root"]) + len(v["chunk_parse"]) + len(v["manifest"]) + len(v["resolution"])
             + len(v["tier"]) + len(v["conflict"]) + len(v["update"]) + 1)
    print(f"{total - fails}/{total} vector groups ok" if not fails else f"{fails} failures")
    return 1 if fails else 0


def main(argv: List[str]) -> int:
    if len(argv) >= 2 and argv[1] == "gen":
        print(json.dumps(gen(), indent=1, ensure_ascii=False))
        return 0
    if len(argv) >= 3 and argv[1] == "check":
        return check(argv[2])
    if len(argv) >= 3 and argv[1] == "root":
        ids = [l.strip() for l in open(argv[2], encoding="ascii") if l.strip()]
        print(members_root(ids), len(ids))
        return 0
    if len(argv) >= 4 and argv[1] == "chunk":
        ids = [l.strip() for l in open(argv[2], encoding="ascii") if l.strip()]
        os.makedirs(argv[3], exist_ok=True)
        for n, body in enumerate(text_chunks(ids)):
            with open(os.path.join(argv[3], f"chunk-{n:03d}.txt"), "wb") as f:
                f.write(body)
        print(members_root(ids), len(ids))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
