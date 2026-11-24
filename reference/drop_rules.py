#!/usr/bin/env python3
"""Reference checker for ÐMP drop rules (drop-rules.md, draft registry revision 1.2).

  drop_rules.py check vectors/drop_rules_vectors.json   # recompute and compare
  drop_rules.py gen > vectors/drop_rules_vectors.json   # regenerate the vectors
  drop_rules.py seed <child id> <block hash>            # one child's seed

Written from the spec. Pure functions only: chain facts (heights, funding outputs, inscriber) are
inputs. No keys, no network. Manifest signatures are the registry's concern (collection_registry.py);
these functions run on manifests that are already valid.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

CANONICAL_ID = re.compile(r"^[0-9a-f]{64}i(0|[1-9][0-9]*)$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
KOINU_RE = re.compile(r"^(0|[1-9][0-9]{0,16})$")
DEC_RE = re.compile(r"^(0|[1-9][0-9]*)$")

SEED_RULE = "child-blockhash-v1"
SEED_DELAY_DEFAULT = 6
SEED_DELAY_MIN = 3
SEED_DELAY_MAX = 144
MAX_SUPPLY = 100_000
MAX_CAP = 100_000
MAX_FEE_BPS = 2_500
FUNDING_WINDOW = 30
MAX_HEIGHT = 0xFFFF_FFFF

P2PKH_VERSION = 0x1E
P2SH_VERSION = 0x16
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


# ── addresses ────────────────────────────────────────────────────────────────────────────────

def b58decode_check(s: str) -> Optional[bytes]:
    if not isinstance(s, str) or not s or any(c not in B58 for c in s):
        return None
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    raw = b"\x00" * (len(s) - len(s.lstrip("1"))) + raw
    if len(raw) < 5:
        return None
    payload, check = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != check:
        return None
    return payload


def b58encode_check(payload: bytes) -> str:
    data = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(data) - len(data.lstrip(b"\x00"))) + out


def address_key(addr: Any) -> Optional[str]:
    """`p2pkh:<hash160 hex>` / `p2sh:<hash160 hex>`, or None. Addresses compare by type and hash160."""
    payload = b58decode_check(addr) if isinstance(addr, str) else None
    if payload is None or len(payload) != 21:
        return None
    kind = {P2PKH_VERSION: "p2pkh", P2SH_VERSION: "p2sh"}.get(payload[0])
    return f"{kind}:{payload[1:].hex()}" if kind else None


# ── mint rules (§2) ──────────────────────────────────────────────────────────────────────────

def _dec(v: Any, lo: int, hi: int) -> Optional[int]:
    if not isinstance(v, str) or not DEC_RE.match(v):
        return None
    n = int(v)
    return n if lo <= n <= hi else None


def _koinu(v: Any) -> Optional[int]:
    return int(v) if isinstance(v, str) and KOINU_RE.match(v) else None


def parse_mint(manifest: Dict[str, Any], M: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(rules, None) or (None, reason). Checks run in the order of drop-rules.md §2."""
    mint = manifest.get("mint")
    criteria = manifest.get("criteria")
    if (
        not isinstance(mint, dict)
        or manifest.get("type") != "fixed"
        or not isinstance(criteria, dict)
        or criteria.get("mode") != "parent"
        or manifest.get("supply_locked") is not True
    ):
        return None, "mint_shape"
    supply = _dec(manifest.get("supply"), 1, MAX_SUPPLY)
    if supply is None:
        return None, "mint_supply"
    if mint.get("v") != "1":
        return None, "mint_version"
    if mint.get("seed") != SEED_RULE:
        return None, "mint_seed"
    delay = SEED_DELAY_DEFAULT
    if "seed_delay" in mint:
        delay = _dec(mint["seed_delay"], SEED_DELAY_MIN, SEED_DELAY_MAX)
        if delay is None:
            return None, "mint_seed_delay"
    opens = _dec(mint.get("opens_at_height"), 1, MAX_HEIGHT)
    if opens is None or opens <= M:
        return None, "mint_opens"
    closes = None
    if "closes_at_height" in mint and mint["closes_at_height"] is not None:
        closes = _dec(mint["closes_at_height"], 1, MAX_HEIGHT)
        if closes is None or closes <= opens:
            return None, "mint_closes"
    price = _koinu(mint.get("price_koinu"))
    if price is None:
        return None, "mint_price"
    pay_to = None
    if price > 0 or "pay_to" in mint:
        pay_to = address_key(mint.get("pay_to"))
        if pay_to is None:
            return None, "mint_pay_to"
    fee_to = bps = fee_min = None
    has_fee = any(k in mint for k in ("studio_fee_to", "studio_fee_bps", "studio_fee_min_koinu"))
    if has_fee:
        fee_to = address_key(mint.get("studio_fee_to"))
        bps = _dec(mint.get("studio_fee_bps"), 0, MAX_FEE_BPS)
        fee_min = _koinu(mint.get("studio_fee_min_koinu"))
        if fee_to is None or bps is None or fee_min is None:
            return None, "mint_studio_fee"
    cap = None
    if "max_per_inscriber" in mint:
        cap = _dec(mint["max_per_inscriber"], 1, MAX_CAP)
        if cap is None:
            return None, "mint_cap"
    for k in ("brain", "recipe"):
        if k in mint and not (isinstance(mint[k], str) and CANONICAL_ID.match(mint[k])):
            return None, "mint_ref"
    if mint.get("signer") is not None:
        return None, "mint_signer"
    return {
        "supply": supply,
        "seed_delay": delay,
        "opens": opens,
        "closes": closes,
        "price": price,
        "pay_to": pay_to,
        "fee_to": fee_to,
        "fee_bps": bps or 0,
        "fee_min": fee_min or 0,
        "cap": cap,
    }, None


def studio_fee(price: int, bps: int, fee_min: int) -> int:
    return max(price * bps // 10_000, fee_min)


def owed(rules: Dict[str, Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if rules["price"] > 0:
        out[rules["pay_to"]] = out.get(rules["pay_to"], 0) + rules["price"]
    if rules["fee_to"] is not None:
        fee = studio_fee(rules["price"], rules["fee_bps"], rules["fee_min"])
        if fee > 0:
            out[rules["fee_to"]] = out.get(rules["fee_to"], 0) + fee
    return out


# ── seed (§5) ────────────────────────────────────────────────────────────────────────────────

def seed(child_id: str, block_hash: str) -> str:
    if not CANONICAL_ID.match(child_id) or not HEX64.match(block_hash):
        raise ValueError("canonical child id and 64 lowercase hex block hash required")
    return hashlib.sha256(f"dmp-drop-seed|1|{child_id}|{block_hash}".encode("utf-8")).hexdigest()


# ── membership (§3, §4) ──────────────────────────────────────────────────────────────────────

class Ledger:
    """Indexer state across drops: members per drop, per inscriber, and `used` per funding tx."""

    def __init__(self) -> None:
        self.minted: Dict[str, int] = {}
        self.by_inscriber: Dict[Tuple[str, str], int] = {}
        self.used: Dict[Tuple[str, str], int] = {}


def evaluate(ledger: Ledger, drop_id: str, rules: Optional[Dict[str, Any]], M: int, child: Dict[str, Any]) -> Dict[str, Any]:
    """One child, in position order. Updates the ledger when it becomes a member."""
    if rules is None:
        return {"member": False, "reason": None}
    hc = child["hc"]
    if not child.get("single_tx", True):
        return {"member": False, "reason": "multi_tx"}
    if hc < rules["opens"]:
        return {"member": False, "reason": "not_open"}
    if rules["closes"] is not None and hc >= rules["closes"]:
        return {"member": False, "reason": "closed"}
    need = owed(rules)
    funding = child.get("funding")
    if need:
        if not funding or not (M < funding["height"] <= hc and hc - funding["height"] <= FUNDING_WINDOW):
            return {"member": False, "reason": "unpaid"}
        paid: Dict[str, int] = {}
        for out in funding.get("outputs", []):
            k = address_key(out["address"])
            if k is not None:
                paid[k] = paid.get(k, 0) + int(out["koinu"])
        txid = funding["txid"]
        for addr, amount in need.items():
            if paid.get(addr, 0) - ledger.used.get((txid, addr), 0) < amount:
                return {"member": False, "reason": "unpaid"}
    inscriber = address_key(child.get("inscriber")) if child.get("inscriber") else None
    if rules["cap"] is not None:
        if inscriber is None:
            return {"member": False, "reason": "no_inscriber"}
        if ledger.by_inscriber.get((drop_id, inscriber), 0) >= rules["cap"]:
            return {"member": False, "reason": "inscriber_cap"}
    if ledger.minted.get(drop_id, 0) >= rules["supply"]:
        return {"member": False, "reason": "sold_out"}
    if need:
        for addr, amount in need.items():
            key = (funding["txid"], addr)
            ledger.used[key] = ledger.used.get(key, 0) + amount
    if inscriber is not None:
        ledger.by_inscriber[(drop_id, inscriber)] = ledger.by_inscriber.get((drop_id, inscriber), 0) + 1
    ledger.minted[drop_id] = ledger.minted.get(drop_id, 0) + 1
    return {"member": True, "member_no": ledger.minted[drop_id]}


def run_scenario(sc: Dict[str, Any]) -> List[Dict[str, Any]]:
    ledger = Ledger()
    parsed = {did: parse_mint(d["manifest"], d["M"]) for did, d in sc["drops"].items()}
    out = []
    for child in sc["children"]:
        rules, _ = parsed[child["drop"]]
        out.append(evaluate(ledger, child["drop"], rules, sc["drops"][child["drop"]]["M"], child))
    return out


# ── vectors ──────────────────────────────────────────────────────────────────────────────────

def _addr(version: int, n: int) -> str:
    return b58encode_check(bytes([version]) + bytes([n]) * 20)


# The 0x01…, 0x02… test-key addresses of collection_registry.py, and two synthetic ones.
CREATOR = "DGEX9JsfNuCCA3ovxAmUSM1GCea1BpY4Et"
STUDIO = "DSdeTLgR9ZChn46U89HyK4Quaj91EU2Zuq"
MINTER_A = "DB7NZUwffx4NMgCDnmAgVeh8fKBrWwg6f4"
MINTER_B = _addr(P2PKH_VERSION, 0x0B)
STUDIO_P2SH = _addr(P2SH_VERSION, 0x0C)


def fake_id(n: int, idx: int = 0) -> str:
    return hashlib.sha256(f"drop-vector-{n}".encode()).hexdigest() + f"i{idx}"


def fake_txid(n: int) -> str:
    return hashlib.sha256(f"drop-funding-{n}".encode()).hexdigest()


def base_manifest(**mint_over: Any) -> Dict[str, Any]:
    mint: Dict[str, Any] = {
        "v": "1",
        "seed": SEED_RULE,
        "opens_at_height": "1000",
        "price_koinu": "6900000000",
        "pay_to": CREATOR,
        "studio_fee_bps": "200",
        "studio_fee_min_koinu": "50000000",
        "studio_fee_to": STUDIO,
    }
    for k, v in mint_over.items():
        if v is None and k != "signer":
            mint.pop(k, None)
        else:
            mint[k] = v
    return {
        "p": "dmp", "v": "1.0", "op": "collection", "chain": "dogecoin",
        "slug": "drop-test", "name": "Drop Test", "creator_address": CREATOR,
        "royalty_address": CREATOR, "royalty_bps": "500",
        "type": "fixed", "supply": "3", "supply_locked": True,
        "parent_inscription_id": fake_id(1),
        "criteria": {"mode": "parent"},
        "mint": mint,
    }


def gen() -> Dict[str, Any]:
    M = 900
    manifest_cases = []

    def mc(name: str, manifest: Dict[str, Any], m: int = M) -> None:
        rules, reason = parse_mint(manifest, m)
        manifest_cases.append({"name": name, "M": m, "manifest": manifest, "reason": reason, "rules": rules})

    mc("valid paid drop with studio fee", base_manifest())
    mc("valid, all optional fields", base_manifest(seed_delay="3", closes_at_height="2000", max_per_inscriber="2",
                                                    brain=fake_id(2), recipe=fake_id(3), signer=None))
    mc("valid free drop, no fee", base_manifest(price_koinu="0", pay_to=None, studio_fee_to=None,
                                                 studio_fee_bps=None, studio_fee_min_koinu=None))
    mc("valid, fee to a P2SH address", base_manifest(studio_fee_to=STUDIO_P2SH))
    m = base_manifest(); m["mint"] = "yes"; mc("mint not an object", m)
    m = base_manifest(); m["criteria"] = {"mode": "explicit"}; mc("not parent mode", m)
    m = base_manifest(); m["supply_locked"] = False; mc("supply not locked", m)
    m = base_manifest(); m["supply"] = "0"; mc("supply zero", m)
    m = base_manifest(); m["supply"] = "100001"; mc("supply over 100000", m)
    mc("unknown version", base_manifest(v="2"))
    mc("unknown seed rule", base_manifest(seed="txid"))
    mc("seed delay below 3", base_manifest(seed_delay="2"))
    mc("seed delay above 144", base_manifest(seed_delay="145"))
    mc("seed delay not canonical", base_manifest(seed_delay="06"))
    mc("opens at manifest height", base_manifest(opens_at_height=str(M)))
    mc("opens missing", base_manifest(opens_at_height=None))
    mc("closes not after opens", base_manifest(closes_at_height="1000"))
    mc("price negative", base_manifest(price_koinu="-1"))
    mc("price as number", base_manifest(price_koinu=6900000000))
    mc("paid without pay_to", base_manifest(pay_to=None))
    mc("pay_to bad checksum", base_manifest(pay_to=CREATOR[:-1] + ("u" if CREATOR[-1] != "u" else "v")))
    mc("fee address without terms", base_manifest(studio_fee_bps=None))
    mc("fee terms without address", base_manifest(studio_fee_to=None))
    mc("fee bps over 2500", base_manifest(studio_fee_bps="2501"))
    mc("cap zero", base_manifest(max_per_inscriber="0"))
    mc("brain not canonical", base_manifest(brain="abc"))
    mc("signer set", base_manifest(signer=CREATOR))

    fee_cases = []
    for price, bps, fmin in [
        (6_900_000_000, 200, 50_000_000),   # 69 Ð → 1.38 Ð
        (1_000_000_000, 200, 50_000_000),   # 10 Ð → floor 0.5 Ð
        (0, 200, 50_000_000),               # free → 0.5 Ð
        (100_000_000, 200, 50_000_000),     # 1 Ð → 0.5 Ð
        (12_345_678_901, 250, 0),           # floor division
        (5_000_000_000, 0, 0),
    ]:
        fee_cases.append({"price_koinu": price, "bps": bps, "min_koinu": fmin, "fee": studio_fee(price, bps, fmin)})

    seed_cases = []
    for n in range(3):
        cid = fake_id(100 + n, n)
        bh = hashlib.sha256(f"block-{n}".encode()).hexdigest()
        seed_cases.append({"child_id": cid, "block_hash": bh, "seed": seed(cid, bh)})

    scenarios = []

    def sc(name: str, drops: Dict[str, Any], children: List[Dict[str, Any]]) -> None:
        s = {"name": name, "drops": drops, "children": children}
        s["want"] = run_scenario(s)
        scenarios.append(s)

    def pay(txid_n: int, height: int, *outs: Tuple[str, int]) -> Dict[str, Any]:
        return {"txid": fake_txid(txid_n), "height": height,
                "outputs": [{"address": a, "koinu": k} for a, k in outs]}

    price, fee = 6_900_000_000, 138_000_000
    D = fake_id(10)
    drop = {D: {"M": M, "manifest": base_manifest(max_per_inscriber="2")}}
    sc("paid drop: window, payment, cap, supply", drop, [
        {"drop": D, "child": fake_id(20), "hc": 999, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(1, 999, (CREATOR, price), (STUDIO, fee))},                     # not_open
        {"drop": D, "child": fake_id(21), "hc": 1000, "single_tx": False, "inscriber": MINTER_A,
         "funding": pay(2, 1000, (CREATOR, price), (STUDIO, fee))},                    # multi_tx
        {"drop": D, "child": fake_id(22), "hc": 1000, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(3, 1000, (CREATOR, price), (STUDIO, fee - 1))},                # unpaid (fee short)
        {"drop": D, "child": fake_id(23), "hc": 1001, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(4, 1000, (CREATOR, price), (STUDIO, fee))},                    # member 1
        {"drop": D, "child": fake_id(24), "hc": 1001, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(4, 1000, (CREATOR, price), (STUDIO, fee))},                    # unpaid: tx 4 used up
        {"drop": D, "child": fake_id(25), "hc": 1040, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(5, 1009, (CREATOR, price), (STUDIO, fee))},                    # unpaid: 31 blocks
        {"drop": D, "child": fake_id(26), "hc": 1040, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(6, 1010, (CREATOR, 2 * price), (STUDIO, 2 * fee))},            # member 2 (window edge)
        {"drop": D, "child": fake_id(27), "hc": 1040, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(6, 1010, (CREATOR, 2 * price), (STUDIO, 2 * fee))},            # inscriber_cap
        {"drop": D, "child": fake_id(28), "hc": 1040, "single_tx": True, "inscriber": MINTER_B,
         "funding": pay(6, 1010, (CREATOR, 2 * price), (STUDIO, 2 * fee))},            # member 3 (batch)
        {"drop": D, "child": fake_id(29), "hc": 1042, "single_tx": True, "inscriber": MINTER_B,
         "funding": pay(7, 1042, (CREATOR, price), (STUDIO, fee))},                    # sold_out
        {"drop": D, "child": fake_id(30), "hc": 1042, "single_tx": True, "inscriber": None,
         "funding": pay(8, 1042, (CREATOR, price), (STUDIO, fee))},                    # no_inscriber
    ])

    E = fake_id(11)
    same = base_manifest(pay_to=STUDIO, closes_at_height="1100")
    same["supply"] = "10"
    sc("pay_to equals studio_fee_to: amounts add; close height", {E: {"M": M, "manifest": same}}, [
        {"drop": E, "child": fake_id(40), "hc": 1050, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(10, 1050, (STUDIO, price))},                                   # unpaid: fee missing
        {"drop": E, "child": fake_id(41), "hc": 1050, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(11, 1050, (STUDIO, price), (STUDIO, fee))},                    # member 1 (two outputs sum)
        {"drop": E, "child": fake_id(42), "hc": 1100, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(12, 1100, (STUDIO, price + fee))},                             # closed
    ])

    A, B = fake_id(12), fake_id(13)
    free_a = base_manifest(price_koinu="0", pay_to=None)
    free_b = base_manifest(price_koinu="0", pay_to=None)
    free_b["slug"] = "drop-test-b"
    sc("shared studio address across drops: each koinu pays once", {A: {"M": M, "manifest": free_a}, B: {"M": M, "manifest": free_b}}, [
        {"drop": A, "child": fake_id(50), "hc": 1001, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(20, 1001, (STUDIO, 50_000_000))},                              # member 1 of A
        {"drop": B, "child": fake_id(51), "hc": 1001, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(20, 1001, (STUDIO, 50_000_000))},                              # unpaid: output used by A
        {"drop": B, "child": fake_id(52), "hc": 1002, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(21, 900, (STUDIO, 50_000_000))},                               # unpaid: F = M
    ])

    X = fake_id(14)
    bad = base_manifest(seed="txid")
    sc("invalid mint rules: no members, no reasons", {X: {"M": M, "manifest": bad}}, [
        {"drop": X, "child": fake_id(60), "hc": 1001, "single_tx": True, "inscriber": MINTER_A,
         "funding": pay(30, 1001, (CREATOR, price), (STUDIO, fee))},
    ])

    nothing = base_manifest(price_koinu="0", pay_to=None, studio_fee_to=None, studio_fee_bps=None, studio_fee_min_koinu=None)
    Y = fake_id(15)
    sc("nothing owed: no funding needed", {Y: {"M": M, "manifest": nothing}}, [
        {"drop": Y, "child": fake_id(70), "hc": 1001, "single_tx": True, "inscriber": MINTER_A, "funding": None},
    ])

    return {
        "spec": "drop-rules.md (draft registry revision 1.2)",
        "addresses": {"creator": CREATOR, "studio": STUDIO, "minter_a": MINTER_A, "minter_b": MINTER_B,
                      "studio_p2sh": STUDIO_P2SH},
        "manifest": manifest_cases,
        "fee": fee_cases,
        "seed": seed_cases,
        "scenarios": scenarios,
    }


def check(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        v = json.load(f)
    bad = 0
    groups = 0

    def eq(name: str, got: Any, want: Any) -> None:
        nonlocal bad, groups
        groups += 1
        if got != want:
            bad += 1
            print(f"FAIL {name}\n  got  {json.dumps(got, sort_keys=True)}\n  want {json.dumps(want, sort_keys=True)}")

    for c in v["manifest"]:
        rules, reason = parse_mint(c["manifest"], c["M"])
        eq(f"manifest: {c['name']}", [reason, rules], [c["reason"], c["rules"]])
    for c in v["fee"]:
        eq(f"fee {c['price_koinu']}/{c['bps']}/{c['min_koinu']}", studio_fee(c["price_koinu"], c["bps"], c["min_koinu"]), c["fee"])
    for c in v["seed"]:
        eq(f"seed {c['child_id']}", seed(c["child_id"], c["block_hash"]), c["seed"])
    for s in v["scenarios"]:
        eq(f"scenario: {s['name']}", run_scenario(s), s["want"])
    print(f"{groups - bad}/{groups} vector groups ok")
    return 1 if bad else 0


def main(argv: List[str]) -> int:
    if len(argv) >= 3 and argv[1] == "check":
        return check(argv[2])
    if len(argv) >= 2 and argv[1] == "gen":
        print(json.dumps(gen(), indent=2, ensure_ascii=False))
        return 0
    if len(argv) >= 4 and argv[1] == "seed":
        print(seed(argv[2], argv[3]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
