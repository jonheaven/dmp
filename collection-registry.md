# ÐMP Collection Registry (spec revision 1.1)

**Status:** normative part of ÐMP 1.0, added in spec revision 1.1 (2026-11-20). Wire `v` stays
`"1.0"`. Nothing here changes an op that was valid before: the registry adds optional fields that
older indexers ignore (MUST-005), and the one rule it tightens (slug and member precedence, §6)
only matters once two valid manifests disagree.

The registry lets a creator, or anyone, put a collection's member list on Dogecoin, including old
collections whose list only exists today as a JSON file on a marketplace server. A manifest commits
to the whole list with one SHA-256 root. The list itself is inscribed in chunks. Any indexer with a
full node can rebuild it, check the root, and decide from chain data alone whether the signer is the
collection's creator (`verified`) or someone else (`community`).

Vectors: [`vectors/collection_registry_vectors.json`](vectors/collection_registry_vectors.json),
checked by [`reference/collection_registry.py`](reference/collection_registry.py).

---

## 1. Terms

| Term | Meaning |
| --- | --- |
| **Manifest** | A §4.5 `collection` inscription. A **committed manifest** is one that carries `criteria.members_root` (§4). |
| **Chunk** | An inscription that holds part of a committed member list (§3). |
| **Canonical id** | An inscription id matching `^[0-9a-f]{64}i(0\|[1-9][0-9]*)$`: lowercase hex txid, `i`, index in canonical decimal (no leading zeros). |
| **H** | The height of the block holding the transaction that completes the manifest inscription. |
| **State at H−1** | Chain state at the end of block H−1: every transaction in blocks before H applied, none from block H. |
| **Position** | Canonical ordering (§2 of spec.md): block height, then transaction index, then inscription order. Earlier is smaller. |
| **Inscriber** of an inscription X | The address of the output that holds X when its body is complete: the first output of a single-transaction reveal, or the output that receives X from the completing transaction of a multi-transaction reveal (the location in spec.md §2 / compact-orders §8.1). If that output is not P2PKH or P2SH, X has no inscriber. Inscriber never changes when X moves. |
| **Origin address** | `creator_address` of the root manifest. |
| **Signer** | The address whose signature the next `collection-update` must carry. It starts as the origin address and changes only by handover (§7.3). |

Addresses are compared by type and hash160, not by string.

## 2. Limits

| Limit | Value |
| --- | --- |
| Chunk body | ≤ 32,768 bytes |
| Chunks per manifest (`members_chunks`) | 1 to 256 |
| Members per committed manifest (`members_count`) | 1 to 100,000 |
| Chunk window | every chunk complete by block **H + 1440** (about one day) |

A text chunk holds at most 489 ids (489 × 67 bytes = 32,763). 10,000 members need 21 chunks.

## 3. Chunks

A chunk is an ordinary Doginals inscription. Its content type is not part of the rule; wallets SHOULD
use `text/plain;charset=utf-8` for the text form and `application/json` for the JSON form. Indexers
MUST NOT reject a chunk because of its content type.

The form is decided by the first byte of the body:

- **JSON form** (first byte `{`): a UTF-8 JSON object with `"p":"dmp"`, `"op":"collection-chunk"`,
  and `"ids"`: an array of one or more canonical ids. `"v"`, when present, MUST be `"1.0"`. Other keys
  are ignored. A bare JSON array is **not** a chunk (it would also read as a legacy member document).
- **Text form** (any other first byte): one or more canonical ids, each followed by one LF (`0x0A`).
  The LF after the last id is optional. Nothing else is allowed: no CR, spaces, tabs, BOM, empty
  lines or comments.

A chunk is **malformed** when its body is over 32,768 bytes, fails its form's rules, or lists the same
id twice. A chunk is **complete** when its inscription body is complete (every part of a
multi-transaction reveal confirmed).

`collection-chunk` is a payload format, not an op. Indexers MUST NOT treat a chunk as an intent.

## 4. Committed manifests

A committed manifest is a §4.5 `collection` op with `type: "fixed"`, `criteria.mode: "explicit"` and:

```json
"criteria": {
  "mode": "explicit",
  "members_root": "<64 lowercase hex>",
  "members_count": "10000",
  "members_chunks": ["<chunk inscription id>", "…"]
}
```

| Field | Rule |
| --- | --- |
| `members_root` | `^[0-9a-f]{64}$`. The root of §4.1. |
| `members_count` | Decimal string `^[1-9][0-9]*$`, at most `100000`. |
| `members_chunks` | Array of 1 to 256 canonical ids, no duplicates. Order is free and does not affect the root. A chunk MAY be any inscription, including one inscribed after the manifest (inside the window). |
| `criteria.inscription_ids`, `signed_list` | MUST be absent. The manifest `sig` covers the root, count and chunk ids, so a separate list signature is not needed (this replaces MUST-052 for committed manifests). |
| `supply` | When `supply_locked` is `true`, `supply` MUST equal `members_count`. |

Optional display fields, on any manifest and in `collection-update` patches: `description` (string,
≤ 2,000 characters), `image` (canonical id of the collection image), `links` (object of string URLs;
keys `website`, `x`, `discord`, `telegram` are recognized). They never affect validity.

A committed manifest that fails a rule in this table, or the spec.md §13.6 rules (signature, slug,
royalty cap), is **invalid** at once.

### 4.1 The root

```
canonical_list = the member ids, each a canonical id, sorted ascending by byte value (ASCII),
                 joined with a single LF (0x0A), no trailing LF
members_root   = lowercase hex of SHA-256(UTF-8 bytes of canonical_list)
```

Sorting is plain byte order on the id strings, so `…i10` sorts before `…i9`. One member gives
`canonical_list` = that id. Implementations MUST NOT normalize ids before hashing: a non-canonical id
anywhere makes its chunk malformed.

### 4.2 Resolution

Status starts at `pending`. An indexer re-evaluates a pending manifest whenever a referenced chunk
becomes complete, and at least once after block H + 1440.

1. If any referenced chunk is not complete by block H + 1440: `invalid` (`chunk_missing`).
2. Otherwise, once all are complete:
   - any chunk malformed: `invalid` (`chunk_invalid`);
   - the same id in two chunks: `invalid` (`duplicate_member`);
   - number of ids ≠ `members_count`: `invalid` (`count_mismatch`);
   - root of the union ≠ `members_root`: `invalid` (`root_mismatch`);
   - else `valid`. The members are exactly the union.

Checks run in that order; the first failure names the reason. The outcome depends only on chunk
contents and the window, so every indexer reaches the same status. A pending or invalid manifest has
no members and takes part in no conflict (§6). `invalid` is final.

## 5. Verification tiers

Every valid ÐMP `collection` manifest (committed, inline `explicit`, `parent`, `creator_signed`,
`range`, `rule_based`) gets a tier. Let S be the origin address and P the manifest's
`parent_inscription_id`, if any. The manifest is **`verified`** when at least one rule holds, checked
in this order; `verified_by` names the first that holds:

| `verified_by` | Rule |
| --- | --- |
| `parent_holder` | P is set, P exists at state H−1, and the output holding P at state H−1 pays to S. |
| `parent_inscriber` | P is set, P exists at state H−1, and the inscriber of P is S. |
| `member_inscriber` | The member set M is known (inline list, or a committed list once valid), and more than half of M (strictly: `2 × k > \|M\|`) are inscriptions completed in a block before H whose inscriber is S. |

Otherwise the manifest is **`community`**. Tiers use chain data only. No venue list, API or signature
from a third party can make a manifest verified.

- `parent_holder` is checked at H, even while the list is still pending. The other two rules use facts
  that never change (inscriber, completion height), so they give the same answer whenever they run.
- **Why not "the first member's inscriber"?** Many collections were minted straight to buyers, so the
  first member's inscriber is often a collector. A rule they can satisfy would let one collector
  verify the whole collection. A strict majority, a parent, or the parent's holder are things only
  the team that inscribed the collection controls.
- Members inscribed in block H or later never count toward `member_inscriber`.
- `parent` mode membership is still the native-parent join of §9; its tier comes from the parent
  rules because the member set is open.

Venues MUST show the tier. They MUST NOT present a `community` manifest's royalty as the creator's
royalty (royalty is informational anyway, MUST-107).

## 6. Conflicts: slugs and members

Let V be the set of `valid` manifests that are not retired. Rank each by
`(tier, position)`, with `verified` before `community` and earlier position first.

- **Slug.** The slug belongs to the lowest-ranked manifest in V with that slug. This refines MUST-050:
  a verified manifest beats a community one, and among the same tier the earliest wins. A manifest that
  loses its slug stays valid and is still reachable by its id; venues MUST NOT serve it at the slug.
- **Primary collection of an inscription.** The lowest-ranked manifest in V that lists it. An
  inscription MAY be a member of several collections (sub-collections, editions); the primary one is
  only the default label.
- **No silent takeover.** A later root manifest never displaces an earlier one of the same tier, even
  from the same signer. To replace your own manifest, update it (§7.1) or retire it (§7.2).
- A pending manifest that becomes valid takes its place by its own position, so it can outrank a
  manifest that became valid while it waited. The chunk window bounds how long that can take.

There are no ties: positions are unique.

## 7. Updates to registry manifests

The §4.6 `collection-update` op applies, with these additions. Its `sig` MUST verify to the current
signer (this extends MUST-062, which named the root `creator_address`). `supersedes` MUST equal the
current head: the root id until an update is accepted, then the id of the last accepted update. An
accepted update moves the head even if a membership change it carries later fails.

`patch` MAY carry: `name`, `description`, `image`, `links`, `royalty_address`, `royalty_bps` (cap 2500),
`criteria` (§7.1) and `retired` (§7.2). It MUST NOT carry `slug`, `chain`, `type`,
`parent_inscription_id` or `creator_address`; an update with any of them is rejected whole.

### 7.1 Replacing the member list

`patch.criteria` carries `members_root`, `members_count` and `members_chunks` with the §4 rules. The
new list resolves as in §4.2, with H the height of the update and the window counted from it. While it
is pending, the old list stays in force. When it becomes valid it replaces the old list and the tier is
evaluated again (§5, with S still the origin address, `parent_holder` checked against the current
signer at the update's H−1). If it becomes invalid, the old list stays. A newer list replacement
cancels a pending older one. The manifest keeps its id and its position.

### 7.2 Retiring

`patch.retired: true` withdraws the manifest from V for good: it loses its slug and every member claim.
Retiring is final.

### 7.3 Handover (signer rotation)

```json
"handover": { "to": "<new P2PKH address>", "sig": "<base64 signature by the new address>" }
```

A top-level `handover` object rotates the signer. Both `sig` (by the current signer) and
`handover.sig` (by `to`) MUST verify over the same message: the canonical JSON of the whole update with
every `sig` and `sig_msg` key removed at every nesting level (so the message includes
`"handover":{"to":"…"}`). If either fails, the update is rejected. The tier is unchanged by handover;
inscriber rules keep using the origin address.

## 8. Signing

Unchanged from spec.md §5–§6: remove `sig` and `sig_msg` (at every nesting level), sort keys at every
level, serialize with no insignificant whitespace and strings as raw UTF-8 (no `\u` escaping of
non-ASCII), then sign as a Dogecoin signed message. Signatures are the standard 65-byte compact
recoverable form, base64 (what `signmessage` and wallet `signMessage` return). Only P2PKH addresses
can sign. The signer pays nothing on chain: any wallet may inscribe a manifest someone else signed.

## 9. Cost (informative)

A registration is `members_chunks` chunk inscriptions plus one manifest. Doginals carry about 1,450
body bytes per transaction, plus one commit, so a full 32 KB chunk is about 24 transactions. Each
inscription costs roughly:

```
transactions = ceil(body_bytes / 1450) + 1
miner_fee    = (body_bytes + 330 × transactions) × fee_rate / 1000
extra        = 0.01 DOGE soft-dust fee + 0.001 DOGE postage on the final reveal
```

At 0.01 DOGE/kB, 10,000 members (21 text chunks, 670 KB) plus a 2 KB manifest come to about 495
transactions and **about 8.6 DOGE** (`reference/collection_registry.py`, vector `cost`). Wallets pause
for one confirmation every 25 chained transactions, so a 10,000-member registration takes about
20 to 30 minutes of blocks. No protocol fee exists.

## 10. Indexer checklist

- [ ] Strict canonical ids; text and JSON chunk forms; 32,768-byte cap.
- [ ] Root over the sorted, LF-joined list, no trailing LF.
- [ ] Pending until every chunk is complete; `invalid` after H + 1440.
- [ ] Tiers from state H−1 and immutable inscriber facts only.
- [ ] Slug and primary-member precedence by `(tier, position)`; retired and invalid manifests excluded.
- [ ] `collection-update`: current signer, `supersedes` = head, immutable keys rejected, list replacement,
      retire, dual-signed handover.
- [ ] Reorgs roll all of it back.
- [ ] `python3 reference/collection_registry.py check vectors/collection_registry_vectors.json` passes against your outputs.
