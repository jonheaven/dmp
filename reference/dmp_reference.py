#!/usr/bin/env python3
"""DMP v1.0 reference parser and validator.

This is the reference implementation — all other indexers must match this behavior
for core envelope parsing, required-field checks, state machine rules, and
provenance-gap flagging semantics.

Usage:
  python dmp_reference.py validate <file.json>
  python dmp_reference.py validate-raw '<json_string>'
  python dmp_reference.py test-vectors
  python dmp_reference.py demo-gap --ownership-changed [--has-valid-dmp-intent]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from math import floor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import ecdsa


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_VERSIONS = {"1.0"}
MAX_SOFT_SIZE_BYTES = 4096
INSCRIPTION_ID_RE = re.compile(r"^[0-9a-f]{64}i[0-9]+$")
TXID_RE = re.compile(r"^[0-9a-f]{64}$")
POSITIVE_INT_STRING_RE = re.compile(r"^[1-9][0-9]*$")
INTEGER_STRING_RE = re.compile(r"^[0-9]+$")
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")
VALID_AUCTION_MODES = {"time_based", "seller_can_accept_early", "no_early_accept"}
VALID_CANCEL_TYPES = {"list", "bid", "auction", "offer", "counteroffer"}
VALID_CANCEL_REASONS = frozenset({
    "seller_request", "expired", "buyer_breach", "admin_emergency", "other",
})
VALID_OFFER_TARGET_TYPES = {"inscription", "collection"}
VALID_TRANSFER_TYPES = {"gift", "airdrop", "migration", "burn", "other"}
VALID_VOTE_RESULTS = {"approved", "rejected"}
VALID_COLLECTION_TYPES = {"fixed", "dynamic"}
RECOMMENDED_CONFIRMATION_DEPTH = 6


def canonical_json(obj: Any) -> str:
    """Generate canonical JSON: sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'))


def compact_size(n: int) -> bytes:
    """Compact size encoding for length."""
    if n < 0xfd:
        return bytes([n])
    elif n <= 0xffff:
        return b'\xfd' + n.to_bytes(2, 'little')
    elif n <= 0xffffffff:
        return b'\xfe' + n.to_bytes(4, 'little')
    else:
        return b'\xff' + n.to_bytes(8, 'little')


def double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def base58_encode(data: bytes) -> str:
    """Simple base58 encode for Dogecoin addresses."""
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    val = int.from_bytes(data, 'big')
    s = ''
    while val > 0:
        val, idx = divmod(val, 58)
        s = alphabet[idx] + s
    return s


def build_signed_message(canonical: str) -> bytes:
    """Build the Dogecoin signed message payload."""
    prefix = b'\x19Dogecoin Signed Message:\n'
    canonical_bytes = canonical.encode('utf-8')
    len_bytes = compact_size(len(canonical_bytes))
    return prefix + len_bytes + canonical_bytes


def verify_dogecoin_signature(canonical: str, signature: str, address: str) -> bool:
    """Verify Dogecoin signed message signature."""
    try:
        sig_bytes = bytes.fromhex(signature)
        if len(sig_bytes) != 65:
            return False
        rec_id = sig_bytes[0] - 27
        if rec_id < 0 or rec_id > 3:
            return False
        r = int.from_bytes(sig_bytes[1:33], 'big')
        s = int.from_bytes(sig_bytes[33:65], 'big')
        msg_bytes = build_signed_message(canonical)
        msg_hash = double_sha256(msg_bytes)
        msg_hash_int = int.from_bytes(msg_hash, 'big')
        curve = ecdsa.SECP256k1
        sig = ecdsa.ecdsa.Signature(r, s)
        pubkey = ecdsa.ecdsa.recover_pubkey(curve, msg_hash_int, sig, rec_id)
        pubkey_bytes = b'\x04' + pubkey.pubkey.point.x().to_bytes(32, 'big') + pubkey.pubkey.point.y().to_bytes(32, 'big')
        sha = hashlib.sha256(pubkey_bytes).digest()
        rip = hashlib.new('ripemd160', sha).digest()
        version = b'\x1e'  # Dogecoin mainnet P2PKH
        checksum = hashlib.sha256(hashlib.sha256(version + rip).digest()).digest()[:4]
        addr = base58_encode(version + rip + checksum)
        return addr == address
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    level: str   # "error" | "warning" | "info"
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.code}: {self.message}"


@dataclass
class ParsedOp:
    """Result of parsing a single DMP inscription payload."""
    valid: bool
    op: Optional[str]
    version: Optional[str]
    payload: Dict[str, Any]
    issues: List[ValidationIssue] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Op rules: required fields and special checks per op
# ---------------------------------------------------------------------------

OP_RULES: Dict[str, Dict[str, Any]] = {
    "list": {
        "required": ["inscription_id", "price", "seller"],
        "positive_int_strings": ["price"],
    },
    "bid": {
        "required": ["price", "bidder"],
        "one_of": ["inscription_id", "collection_id"],
        "positive_int_strings": ["price"],
    },
    "settle": {
        "required": ["inscription_id", "seller", "buyer", "price", "settlement_txid"],
        "positive_int_strings": ["price"],
    },
    "cancel": {
        "required": ["cancel_id", "cancel_type"],
    },
    "collection": {
        "required": ["slug", "creator_address", "type"],
    },
    "collection-update": {
        "required": ["collection_id", "supersedes", "update_of", "patch"],
    },
    "vote": {
        "required": ["collection_id", "result", "vote_start", "vote_end"],
    },
    "auction": {
        "required": ["inscription_id", "seller", "auction_mode", "min_bid_increment", "start_ts", "expiry"],
        "positive_int_strings": ["min_bid_increment"],
    },
    "offer": {
        "required": ["offer_target_type", "buyer", "price", "currency", "offer_fee", "fee_recipient"],
        "conditional_target": True,
        "positive_int_strings": ["price", "offer_fee"],
    },
    "counteroffer": {
        "required": ["offer_id", "seller", "counter_price", "currency"],
        "positive_int_strings": ["counter_price"],
    },
    "accept": {
        "required": ["target_op", "target_id", "seller"],
    },
    "decline": {
        "required": ["target_op", "target_id", "seller"],
    },
    "transfer": {
        "required": ["inscription_id", "from_address", "to_address", "transfer_type", "transfer_txid"],
    },
}


# ---------------------------------------------------------------------------
# Core validators
# ---------------------------------------------------------------------------

def _add(issues: List[ValidationIssue], level: str, code: str, msg: str) -> None:
    issues.append(ValidationIssue(level, code, msg))


def validate_envelope(
    payload: Dict[str, Any],
    raw_text: str,
    issues: List[ValidationIssue],
) -> Optional[str]:
    """Validate the common DMP envelope. Returns op string or None on failure."""
    if len(raw_text.encode("utf-8")) > MAX_SOFT_SIZE_BYTES:
        _add(issues, "warning", "SIZE-SOFT-LIMIT",
             "Inscription exceeds 4 KB soft guideline for DMP v1.0.")

    for field_name in ("p", "op"):
        if field_name not in payload:
            _add(issues, "error", "MUST-BASE", f"Missing required top-level field: {field_name!r}")

    p = payload.get("p")
    if p not in ("dmp", "Ð:MP"):
        _add(issues, "error", "MUST-001", 'p must equal "dmp" (styled alias "Ð:MP" accepted).')

    v = payload.get("v", "1.0")
    if v not in SUPPORTED_VERSIONS:
        _add(issues, "error", "MUST-002",
             f"v {v!r} not recognized. Supported: {sorted(SUPPORTED_VERSIONS)}.")

    chain = payload.get("chain")
    if chain is not None and chain != "dogecoin":
        _add(issues, "error", "MUST-006",
             f'chain must equal "dogecoin" when present, got {chain!r}.')

    op = payload.get("op")
    if op not in OP_RULES:
        _add(issues, "error", "MUST-003", f"Unsupported op: {op!r}.")
        return None

    return op


def validate_id_patterns(payload: Dict[str, Any], issues: List[ValidationIssue]) -> None:
    """Validate inscription_id / txid / integer-string field formats."""
    inscription_id_fields = [
        "inscription_id", "collection_id", "list_id", "bid_id", "auction_id",
        "offer_id", "target_id", "cancel_id", "supersedes", "update_of",
    ]
    for key in inscription_id_fields:
        val = payload.get(key)
        if isinstance(val, str) and not INSCRIPTION_ID_RE.match(val):
            _add(issues, "error", "FORMAT-ID",
                 f"{key} must be <64-char-hex>i<vout>, got {val!r}.")

    stxid = payload.get("settlement_txid")
    if stxid is not None and not (isinstance(stxid, str) and TXID_RE.match(stxid)):
        _add(issues, "error", "FORMAT-TXID",
             f"settlement_txid must be 64-char lowercase hex, got {stxid!r}.")

    ttxid = payload.get("transfer_txid")
    if ttxid is not None and not (isinstance(ttxid, str) and TXID_RE.match(ttxid)):
        _add(issues, "error", "FORMAT-TXID",
             f"transfer_txid must be 64-char lowercase hex, got {ttxid!r}.")

    # All integer string fields (some allow zero, some require positive)
    int_fields = [
        "royalty_paid", "royalty_bps", "bid_fee",
        "quorum_bps", "votes_for", "votes_against", "votes_abstain",
    ]
    for key in int_fields:
        val = payload.get(key)
        if val is not None and not (isinstance(val, str) and INTEGER_STRING_RE.match(val)):
            _add(issues, "error", "FORMAT-INT-STRING",
                 f"{key} must be a decimal integer string, got {val!r}.")

    positive_int_fields = ["price", "offer_fee", "counter_price", "min_bid_increment",
                           "reserve_price", "start_price"]
    for key in positive_int_fields:
        val = payload.get(key)
        if val is not None and not (isinstance(val, str) and POSITIVE_INT_STRING_RE.match(val)):
            _add(issues, "error", "FORMAT-POS-INT",
                 f"{key} must be a positive integer string (no leading zeros, > 0), got {val!r}.")


def validate_op_rules(
    payload: Dict[str, Any],
    op: str,
    version: str,
    issues: List[ValidationIssue],
) -> None:
    """Validate op-specific required fields and semantic rules."""
    rules = OP_RULES.get(op, {})

    # launch draft-only ops
    if rules.get("v12_only") and version not in {"1.2"}:
        _add(issues, "error", "MUST-002",
             f'op "{op}" requires v: "1.2".')

    # Required fields
    for f in rules.get("required", []):
        if f not in payload:
            _add(issues, "error", "MUST-REQ",
                 f"Missing required field for op={op!r}: {f!r}")

    # one_of requirement (bid needs inscription_id or collection_id)
    one_of = rules.get("one_of")
    if one_of and not any(f in payload for f in one_of):
        _add(issues, "error", "MUST-ONE-OF",
             f"Op {op!r} requires at least one of: {', '.join(one_of)}")

    # Positive integer string requirements per op
    for f in rules.get("positive_int_strings", []):
        val = payload.get(f)
        if val is not None and not (isinstance(val, str) and POSITIVE_INT_STRING_RE.match(val)):
            _add(issues, "error", "FORMAT-POS-INT",
                 f"{f} must be a positive integer string for op={op!r}, got {val!r}.")

    # Op-specific checks
    if op == "list":
        _validate_list(payload, version, issues)
    elif op == "bid":
        _validate_bid(payload, issues)
    elif op == "settle":
        _validate_settle(payload, version, issues)
    elif op == "cancel":
        _validate_cancel(payload, version, issues)
    elif op == "collection":
        _validate_collection(payload, issues)
    elif op == "collection-update":
        _validate_collection_update(payload, issues)
    elif op == "vote":
        _validate_vote(payload, issues)
    elif op == "auction":
        _validate_auction(payload, issues)
    elif op == "offer":
        _validate_offer(payload, issues)
    elif op in {"accept", "decline"}:
        _validate_accept_decline(payload, op, issues)
    elif op == "counteroffer":
        _validate_counteroffer(payload, issues)
    elif op == "transfer":
        _validate_transfer(payload, issues)


def _validate_list(p: Dict, version: str, issues: List[ValidationIssue]) -> None:
    lt = p.get("listing_type")
    if lt is not None and lt not in {"fixed_price", "auction"}:
        _add(issues, "error", "FORMAT", f"listing_type must be fixed_price or auction, got {lt!r}.")

    am = p.get("auction_mode")
    if lt == "auction" or am is not None:
        if am not in VALID_AUCTION_MODES:
            _add(issues, "error", "MUST-016",
                 f"auction_mode must be one of {sorted(VALID_AUCTION_MODES)}, got {am!r}.")


def _validate_bid(p: Dict, issues: List[ValidationIssue]) -> None:
    bf = p.get("bid_fee")
    if bf is not None and "fee_recipient" not in p:
        _add(issues, "error", "MUST-024",
             "fee_recipient required when bid_fee is present.")


def _validate_settle(p: Dict, version: str, issues: List[ValidationIssue]) -> None:
    pf = p.get("platform_fee")
    pfr = p.get("platform_fee_recipient")
    if pf is not None and pfr is None:
        _add(issues, "error", "MUST-037",
             "platform_fee_recipient required when platform_fee is present.")
    if pfr is not None and pf is None:
        _add(issues, "warning", "FORMAT",
             "platform_fee_recipient present but platform_fee missing.")


def _validate_cancel(p: Dict, version: str, issues: List[ValidationIssue]) -> None:
    ct = p.get("cancel_type")
    if ct not in VALID_CANCEL_TYPES:
        _add(issues, "error", "FORMAT",
             f"cancel_type must be one of {sorted(VALID_CANCEL_TYPES)}, got {ct!r}.")

    reason = p.get("reason")
    if reason is None:
        _add(issues, "error", "MUST-106", "cancel op requires reason (MUST-106).")
    elif reason not in VALID_CANCEL_REASONS:
        _add(issues, "error", "MUST-106",
             f"cancel reason must be one of {sorted(VALID_CANCEL_REASONS)}, got {reason!r}.")

    if version == "1.2" and "canceller" not in p:
        _add(issues, "error", "MUST-044",
             'canceller field required for v: "1.2" cancel ops.')

    if "canceller" not in p:
        _add(issues, "warning", "MUST-041",
             "No canceller field — indexer must verify authorization from cancel tx inputs (UTXO method).")

    if "sig" in p:
        payload_copy = {k: v for k, v in p.items() if k not in ('sig', 'sig_msg')}
        canonical = canonical_json(payload_copy)
        if not verify_dogecoin_signature(canonical, p["sig"], p["canceller"]):
            _add(issues, "error", "SIG-VERIFY", "cancel sig does not verify to canceller.")


def _validate_collection(p: Dict, issues: List[ValidationIssue]) -> None:
    t = p.get("type")
    if t not in VALID_COLLECTION_TYPES:
        _add(issues, "error", "FORMAT",
             f"collection type must be fixed or dynamic, got {t!r}.")

    slug = p.get("slug")
    if slug is not None and not SLUG_RE.match(slug):
        _add(issues, "error", "MUST-056",
             f"slug must match ^[a-z0-9-]{{1,64}}$, got {slug!r}.")

    rbps = p.get("royalty_bps")
    if rbps is not None:
        if not (isinstance(rbps, str) and INTEGER_STRING_RE.match(rbps)
                and 0 <= int(rbps) <= 1000):
            _add(issues, "error", "MUST-054",
                 f"royalty_bps must be an integer string in range 0..1000, got {rbps!r}.")

    if "sig" not in p:
        _add(issues, "warning", "MUST-051",
             "collection manifest missing sig field — creator signature required.")
    else:
        payload_copy = {k: v for k, v in p.items() if k not in ('sig', 'sig_msg')}
        canonical = canonical_json(payload_copy)
        if not verify_dogecoin_signature(canonical, p["sig"], p["creator_address"]):
            _add(issues, "error", "SIG-VERIFY", "collection sig does not verify to creator_address.")

    das = p.get("default_auction_settings")
    if das is not None and isinstance(das, dict):
        dam = das.get("auction_mode")
        if dam is not None and dam not in VALID_AUCTION_MODES:
            _add(issues, "error", "MUST-055",
                 f"default_auction_settings.auction_mode invalid: {dam!r}.")


def _validate_collection_update(p: Dict, issues: List[ValidationIssue]) -> None:
    if "patch" in p and not isinstance(p["patch"], dict):
        _add(issues, "error", "FORMAT", "patch must be a JSON object.")
    if "sig" not in p:
        _add(issues, "warning", "MUST-062",
             "collection-update missing sig — creator signature required.")
    else:
        payload_copy = {k: v for k, v in p.items() if k not in ('sig', 'sig_msg')}
        canonical = canonical_json(payload_copy)
        if not verify_dogecoin_signature(canonical, p["sig"], p["creator_address"]):
            _add(issues, "error", "SIG-VERIFY", "collection-update sig does not verify to creator_address.")


def _validate_vote(p: Dict, issues: List[ValidationIssue]) -> None:
    result = p.get("result")
    if result not in VALID_VOTE_RESULTS:
        _add(issues, "error", "MUST-073",
             f"result must be approved or rejected, got {result!r}.")

    vs = p.get("vote_start")
    ve = p.get("vote_end")
    if isinstance(vs, int) and isinstance(ve, int) and ve <= vs:
        _add(issues, "error", "MUST-072",
             f"vote_end ({ve}) must be > vote_start ({vs}).")

    if "sig" not in p:
        _add(issues, "warning", "MUST-071",
             "vote missing sig — DAO authority signature required.")


def _validate_auction(p: Dict, issues: List[ValidationIssue]) -> None:
    am = p.get("auction_mode")
    if am not in VALID_AUCTION_MODES:
        _add(issues, "error", "MUST-074",
             f"auction_mode required and must be one of {sorted(VALID_AUCTION_MODES)}, got {am!r}.")

    st = p.get("start_ts")
    exp = p.get("expiry")
    if isinstance(st, int) and isinstance(exp, int) and exp <= st:
        _add(issues, "error", "MUST-075",
             f"expiry ({exp}) must be > start_ts ({st}).")


def _validate_offer(p: Dict, issues: List[ValidationIssue]) -> None:
    ott = p.get("offer_target_type")
    if ott not in VALID_OFFER_TARGET_TYPES:
        _add(issues, "error", "MUST-080",
             f"offer_target_type must be inscription or collection, got {ott!r}.")
        return

    if ott == "inscription" and "inscription_id" not in p:
        _add(issues, "error", "MUST-081",
             'offer_target_type="inscription" requires inscription_id.')
    elif ott == "collection" and "collection_id" not in p:
        _add(issues, "error", "MUST-081",
             'offer_target_type="collection" requires collection_id.')

    of = p.get("offer_fee")
    if of is None or not (isinstance(of, str) and POSITIVE_INT_STRING_RE.match(of)):
        _add(issues, "error", "MUST-082",
             "offer_fee required and must be a positive integer string.")

    if "fee_recipient" not in p:
        _add(issues, "error", "MUST-083",
             "fee_recipient required for offer.")


def _validate_accept_decline(p: Dict, op: str, issues: List[ValidationIssue]) -> None:
    top = p.get("target_op")
    if top not in {"offer", "counteroffer"}:
        _add(issues, "error", "FORMAT-TARGET-OP",
             f"{op}.target_op must be offer or counteroffer, got {top!r}.")


def _validate_counteroffer(p: Dict, issues: List[ValidationIssue]) -> None:
    pass  # required fields and positive_int_strings already checked by generic logic


def _validate_transfer(p: Dict, issues: List[ValidationIssue]) -> None:
    tt = p.get("transfer_type")
    if tt not in VALID_TRANSFER_TYPES:
        _add(issues, "error", "MUST-095",
             f"transfer_type must be one of {sorted(VALID_TRANSFER_TYPES)}, got {tt!r}.")

    note = p.get("note")
    if note is not None and len(str(note)) > 140:
        _add(issues, "warning", "FORMAT",
             f"note exceeds 140 character limit ({len(str(note))} chars).")

    _add(issues, "info", "TRANSFER-STUB",
         "transfer_txid on-chain verification is a stub. "
         "Production indexers MUST verify from_address/to_address against confirmed tx.")


# ---------------------------------------------------------------------------
# Provenance gap logic
# ---------------------------------------------------------------------------

def detect_provenance_gap(has_valid_dmp_intent: bool, ownership_changed: bool) -> bool:
    """Return True when ownership changed without a valid DMP intent/settlement path."""
    return ownership_changed and not has_valid_dmp_intent


def royalty_check(price_koinu: int, royalty_bps: int, royalty_paid_koinu: int) -> Tuple[bool, int]:
    """Return (passes, expected_koinu). Expected = floor(price * bps / 10000)."""
    expected = floor(price_koinu * royalty_bps / 10000)
    return royalty_paid_koinu >= expected, expected


# ---------------------------------------------------------------------------
# Top-level validate function
# ---------------------------------------------------------------------------

def validate_payload(raw_text: str) -> ParsedOp:
    issues: List[ValidationIssue] = []

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        _add(issues, "error", "JSON", f"Invalid JSON: {exc}")
        return ParsedOp(valid=False, op=None, version=None, payload={}, issues=issues)

    if not isinstance(payload, dict):
        _add(issues, "error", "JSON", "Top-level JSON value must be an object.")
        return ParsedOp(valid=False, op=None, version=None, payload=payload, issues=issues)

    op = validate_envelope(payload, raw_text, issues)
    version = payload.get("v", "")

    validate_id_patterns(payload, issues)

    if op is not None:
        validate_op_rules(payload, op, version, issues)

    has_errors = any(i.level == "error" for i in issues)
    return ParsedOp(
        valid=not has_errors,
        op=op,
        version=version,
        payload=payload,
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Test vectors
# ---------------------------------------------------------------------------

TEST_VECTORS: List[Dict[str, Any]] = [
    # --- PASS cases ---
    {
        "id": "TV-001",
        "desc": "Valid fixed-price list (v1.0)",
        "expect": "pass",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "list",
            "inscription_id": "aaaa" * 16 + "i0",
            "price": "100000000",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "chain": "dogecoin", "ts": 1700000000,
        },
    },
    {
        "id": "TV-001b",
        "desc": "Valid lean list (MUST-109 defaults: no v/currency/chain)",
        "expect": "pass",
        "payload": {
            "p": "dmp", "op": "list",
            "inscription_id": "aaaa" * 16 + "i0",
            "price": "100000000",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
        },
    },
    {
        "id": "TV-002",
        "desc": "Valid bid with inscription_id (v1.0)",
        "expect": "pass",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "bid",
            "inscription_id": "bbbb" * 16 + "i0",
            "price": "150000000",
            "bidder": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
            "chain": "dogecoin", "ts": 1700000100,
        },
    },
    {
        "id": "TV-003",
        "desc": "Valid bid with collection_id (v1.0)",
        "expect": "pass",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "bid",
            "collection_id": "cccc" * 16 + "i0",
            "price": "200000000",
            "bidder": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
            "chain": "dogecoin", "ts": 1700000200,
        },
    },
    {
        "id": "TV-004",
        "desc": "Valid settle (v1.0)",
        "expect": "pass",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "settle",
            "inscription_id": "aaaa" * 16 + "i0",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "buyer": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
            "price": "100000000",
            "settlement_txid": "9f8e" * 16,
            "chain": "dogecoin", "ts": 1700000900,
        },
    },
    {
        "id": "TV-005",
        "desc": "Valid cancel (v1.0, no canceller)",
        "expect": "pass",  # warning only — no canceller is v1.0-valid
        "payload": {
            "p": "dmp", "v": "1.0", "op": "cancel",
            "cancel_id": "cccc" * 16 + "i0",
            "cancel_type": "list",
            "reason": "seller_request",
            "chain": "dogecoin", "ts": 1700000300,
        },
    },
    {
        "id": "TV-006",
        "desc": "Valid cancel with canceller (v1.0)",
        "expect": "pass",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "cancel",
            "cancel_id": "cccc" * 16 + "i0",
            "cancel_type": "list",
            "canceller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "reason": "seller_request",
            "chain": "dogecoin", "ts": 1700000300,
        },
    },
    {
        "id": "TV-007",
        "desc": "Valid auction (v1.0)",
        "expect": "pass",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "auction",
            "inscription_id": "1111" * 16 + "i0",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "auction_mode": "time_based",
            "min_bid_increment": "50000000",
            "start_ts": 1700000000,
            "expiry": 1700007200,
            "chain": "dogecoin", "ts": 1700000001,
        },
    },
    {
        "id": "TV-008",
        "desc": "Valid offer (v1.0)",
        "expect": "pass",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "offer",
            "offer_target_type": "inscription",
            "inscription_id": "aaaa" * 16 + "i0",
            "buyer": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
            "price": "1250000000",
            "currency": "DOGE",
            "offer_fee": "100000000",
            "fee_recipient": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "expiry": 1700010000,
            "chain": "dogecoin", "ts": 1700000400,
        },
    },
    {
        "id": "TV-009",
        "desc": "Valid transfer (v1.0)",
        "expect": "pass",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "transfer",
            "inscription_id": "aaaa" * 16 + "i0",
            "from_address": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "to_address": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
            "transfer_type": "gift",
            "transfer_txid": "a1b2" * 16,
            "note": "Gifted to community winner",
            "chain": "dogecoin", "ts": 1700001200,
        },
    },
    {
        "id": "TV-010",
        "desc": "Valid settle with platform_fee (v1.0)",
        "expect": "pass",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "settle",
            "inscription_id": "aaaa" * 16 + "i0",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "buyer": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
            "price": "100000000",
            "platform_fee": "2000000",
            "platform_fee_recipient": "DFeeAddressMarketplaceXXXXXXXXXXXX",
            "settlement_txid": "9f8e" * 16,
            "chain": "dogecoin", "ts": 1700001000,
        },
    },
    # --- FAIL cases ---
    {
        "id": "TV-101",
        "desc": "MUST-001: wrong p value",
        "expect": "fail",
        "payload": {
            "p": "ord", "v": "1.0", "op": "list",
            "inscription_id": "aaaa" * 16 + "i0",
            "price": "100000000",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
        },
    },
    {
        "id": "TV-102",
        "desc": "MUST-002: unknown version",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "9.9", "op": "list",
            "inscription_id": "aaaa" * 16 + "i0",
            "price": "100000000",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
        },
    },
    {
        "id": "TV-103",
        "desc": "MUST-003: unknown op",
        "expect": "fail",
        "payload": {"p": "dmp", "v": "1.0", "op": "unknown_op"},
    },
    {
        "id": "TV-104",
        "desc": "MUST-REQ: list missing inscription_id",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "list",
            "price": "100000000",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
        },
    },
    {
        "id": "TV-105",
        "desc": "MUST-REQ: list missing price",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "list",
            "inscription_id": "aaaa" * 16 + "i0",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
        },
    },
    {
        "id": "TV-106",
        "desc": "MUST-ONE-OF: bid missing both inscription_id and collection_id",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "bid",
            "price": "100000000",
            "bidder": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
        },
    },
    {
        "id": "TV-107",
        "desc": "FORMAT-ID: malformed inscription_id",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "list",
            "inscription_id": "not-a-valid-id",
            "price": "100000000",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
        },
    },
    {
        "id": "TV-108",
        "desc": "MUST-074: auction with invalid auction_mode",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "auction",
            "inscription_id": "1111" * 16 + "i0",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "auction_mode": "invalid_mode",
            "min_bid_increment": "50000000",
            "start_ts": 1700000000,
            "expiry": 1700007200,
        },
    },
    {
        "id": "TV-109",
        "desc": "MUST-075: auction expiry <= start_ts",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "auction",
            "inscription_id": "1111" * 16 + "i0",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "auction_mode": "time_based",
            "min_bid_increment": "50000000",
            "start_ts": 1700007200,
            "expiry": 1700000000,  # expiry < start_ts
        },
    },
    {
        "id": "TV-110",
        "desc": "MUST-082: offer with offer_fee = 0",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "offer",
            "offer_target_type": "inscription",
            "inscription_id": "aaaa" * 16 + "i0",
            "buyer": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
            "price": "100000000",
            "currency": "DOGE",
            "offer_fee": "0",  # must be > 0
            "fee_recipient": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
        },
    },
    {
        "id": "TV-111",
        "desc": "MUST-083: offer missing fee_recipient",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "offer",
            "offer_target_type": "inscription",
            "inscription_id": "aaaa" * 16 + "i0",
            "buyer": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
            "price": "100000000",
            "currency": "DOGE",
            "offer_fee": "100000000",
        },
    },
    {
        "id": "TV-112",
        "desc": "MUST-006: chain != dogecoin",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "list",
            "inscription_id": "aaaa" * 16 + "i0",
            "price": "100000000",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "chain": "bitcoin",  # wrong chain
        },
    },
    {
        "id": "TV-113",
        "desc": "MUST-106: cancel missing reason",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "cancel",
            "cancel_id": "cccc" * 16 + "i0",
            "cancel_type": "list",
            "canceller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "chain": "dogecoin",
            "ts": 1700000300,
        },
    },
    {
        "id": "TV-114",
        "desc": "MUST-095: invalid transfer_type",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "transfer",
            "inscription_id": "aaaa" * 16 + "i0",
            "from_address": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "to_address": "DRPLkFEt5GNQR2xt1GtVBSsTUr63W3mBnq",
            "transfer_type": "sale",  # invalid — use settle for sales
            "transfer_txid": "a1b2" * 16,
        },
    },
    {
        "id": "TV-115",
        "desc": "MUST-054: royalty_bps out of range",
        "expect": "fail",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "collection",
            "slug": "test-collection",
            "creator_address": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "type": "fixed",
            "royalty_bps": "1500",  # > 1000 (10%)
        },
    },
    {
        "id": "TV-116",
        "desc": "Unknown fields are silently ignored (MUST-005)",
        "expect": "pass",
        "payload": {
            "p": "dmp", "v": "1.0", "op": "list",
            "inscription_id": "aaaa" * 16 + "i0",
            "price": "100000000",
            "seller": "D8mZsgKwmSQWYRPEMCcm8KzNFj1JVF5UpA",
            "future_field_v99": "this_should_be_ignored",
            "another_unknown": {"nested": "value"},
        },
    },
    {
        "id": "TV-117",
        "desc": "Royalty check helper — passes",
        "expect": "royalty_pass",
        "royalty": {"price": 1000000000, "bps": 500, "paid": 50000000},
    },
    {
        "id": "TV-118",
        "desc": "Royalty check helper — fails (underpayment)",
        "expect": "royalty_fail",
        "royalty": {"price": 1000000000, "bps": 500, "paid": 49999999},
    },
]


def run_test_vectors() -> int:
    """Run all test vectors. Returns exit code (0=all passed, 1=failures)."""
    passed = 0
    failed = 0

    for tv in TEST_VECTORS:
        tv_id = tv["id"]
        desc = tv["desc"]
        expect = tv["expect"]

        # Royalty check vectors
        if "royalty" in tv:
            r = tv["royalty"]
            ok, expected = royalty_check(r["price"], r["bps"], r["paid"])
            if expect == "royalty_pass" and ok:
                print(f"  PASS  {tv_id}: {desc}")
                passed += 1
            elif expect == "royalty_fail" and not ok:
                print(f"  PASS  {tv_id}: {desc} (correctly fails; expected {expected}, got {r['paid']})")
                passed += 1
            else:
                print(f"  FAIL  {tv_id}: {desc} (royalty check {'passed' if ok else 'failed'}, expected {expect})")
                failed += 1
            continue

        raw_text = json.dumps(tv["payload"])
        result = validate_payload(raw_text)
        has_errors = not result.valid

        if expect == "pass" and result.valid:
            print(f"  PASS  {tv_id}: {desc}")
            passed += 1
        elif expect == "fail" and has_errors:
            codes = [i.code for i in result.issues if i.level == "error"]
            print(f"  PASS  {tv_id}: {desc} (correctly fails: {', '.join(codes)})")
            passed += 1
        else:
            print(f"  FAIL  {tv_id}: {desc}")
            print(f"        Expected: {expect}, valid={result.valid}")
            for issue in result.issues:
                print(f"        {issue}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed out of {len(TEST_VECTORS)} vectors.")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_result(result: ParsedOp) -> int:
    if not result.issues:
        print(f"VALID: payload is a well-formed DMP v{result.version} {result.op!r} op.")
        return 0

    exit_code = 0
    for issue in result.issues:
        print(issue)
        if issue.level == "error":
            exit_code = 1

    if exit_code == 0:
        print(f"\nVALID (with warnings): DMP v{result.version} {result.op!r} op.")
    else:
        print(f"\nINVALID: {sum(1 for i in result.issues if i.level == 'error')} error(s) found.")

    return exit_code


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DMP v1.0 reference parser and validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    vp = sub.add_parser("validate", help="Validate a JSON file")
    vp.add_argument("path", type=Path)

    vr = sub.add_parser("validate-raw", help="Validate raw JSON string")
    vr.add_argument("raw_text")

    sub.add_parser("test-vectors", help="Run the built-in test vector suite")

    gp = sub.add_parser("demo-gap", help="Demo the provenance-gap rule")
    gp.add_argument("--has-valid-dmp-intent", action="store_true")
    gp.add_argument("--ownership-changed", action="store_true")

    return parser


def main(argv: List[str]) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        raw = args.path.read_text(encoding="utf-8")
        return print_result(validate_payload(raw))

    if args.command == "validate-raw":
        return print_result(validate_payload(args.raw_text))

    if args.command == "test-vectors":
        return run_test_vectors()

    if args.command == "demo-gap":
        gap = detect_provenance_gap(args.has_valid_dmp_intent, args.ownership_changed)
        print(json.dumps({
            "ownership_changed": args.ownership_changed,
            "has_valid_dmp_intent": args.has_valid_dmp_intent,
            "provenance_gap": gap,
        }, indent=2))
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
