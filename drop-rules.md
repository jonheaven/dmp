# ÐMP Drop Rules (draft registry revision 1.2)

**Status:** draft, 2026-11-21. Part of the collection registry ([`collection-registry.md`](collection-registry.md)).
Wire `v` stays `"1.0"`. The draft is frozen, and its MUST rules numbered, after the first live drop
that uses it; until then it may change in place. Nothing here changes an op that was valid before: a
manifest without `mint` resolves exactly as in revision 1.1.

A drop is a collection whose members are minted by the public. Drop rules let the creator write
the terms of the mint into the signed manifest: when it opens and closes, the price, a venue fee,
the supply, and the rule that turns each child into its traits. Every indexer then decides from chain
data alone which children are members and what each one draws. No server takes part, and nobody
can pick a rare piece: not the minter, not the creator, not the venue.

Vectors: [`vectors/drop_rules_vectors.json`](vectors/drop_rules_vectors.json), checked by
[`reference/drop_rules.py`](reference/drop_rules.py).

---

## 1. Terms

Registry terms (§1 of `collection-registry.md`) apply: canonical id, position, inscriber, H.

| Term | Meaning |
| --- | --- |
| **Drop manifest** | A valid §4.5 `collection` manifest with a top-level `mint` object. Validity of the manifest itself (signature, slug, royalty cap) is unchanged. |
| **M** | The height of the block holding the drop manifest. |
| **Child** | An inscription whose native parent (envelope tag 3) is the drop manifest's inscription id. |
| **Hc** | The height of the block holding the transaction that completes a child. |
| **Mint transaction** | The transaction that completes a child. |
| **Funding transaction** | The transaction whose output is spent by input 0 of the mint transaction (for a P2SH reveal, the commit). |
| **F** | The height of the block holding the funding transaction. |
| **Owed** | The amounts a child must pay, per address (§4). |

## 2. The `mint` object

A drop manifest MUST have `type: "fixed"`, `criteria.mode: "parent"`, `supply` and
`supply_locked: true`. Children name the manifest itself as their parent (spec.md §4.5:
`parent` members are inscriptions whose native parent is *this collection inscription*).

```json
"mint": {
  "v": "1",
  "seed": "child-blockhash-v1",
  "seed_delay": "6",
  "opens_at_height": "5912000",
  "closes_at_height": "5922000",
  "price_koinu": "6900000000",
  "pay_to": "D…",
  "studio_fee_bps": "200",
  "studio_fee_min_koinu": "50000000",
  "studio_fee_to": "D…",
  "max_per_inscriber": "5",
  "brain": "<canonical id>",
  "recipe": "<canonical id>"
}
```

| Field | Rule |
| --- | --- |
| `v` | Required. `"1"`. |
| `seed` | Required. `"child-blockhash-v1"` (§5). |
| `seed_delay` | Optional, default `"6"`. Decimal string, 3 to 144. |
| `opens_at_height` | Required. Decimal string, greater than M. |
| `closes_at_height` | Optional. Decimal string, greater than `opens_at_height`. Absent: never closes. |
| `price_koinu` | Required. Decimal string `^(0\|[1-9][0-9]{0,16})$`. |
| `pay_to` | Required when `price_koinu` is not `"0"`. When present, a Dogecoin P2PKH or P2SH address. |
| `studio_fee_to` | Optional. A Dogecoin P2PKH or P2SH address. When present, `studio_fee_bps` and `studio_fee_min_koinu` are required. When absent, both MUST be absent. |
| `studio_fee_bps` | Decimal string, 0 to 2500. |
| `studio_fee_min_koinu` | Decimal string `^(0\|[1-9][0-9]{0,16})$`. |
| `max_per_inscriber` | Optional. Decimal string, 1 to 100000. |
| `brain`, `recipe` | Optional canonical ids. Informational: what venues and brains use to render. They never affect membership. |
| `signer` | Reserved for an admission rule in a later draft. MUST be absent or `null`. |

Decimal strings follow the ÐMP convention: canonical decimal, no sign, no leading zeros. Addresses
are compared by type and hash160. Unknown keys inside `mint` are ignored.

The manifest's `supply` MUST be a decimal string from 1 to 100000.

A drop manifest whose `mint` breaks any rule above has **invalid mint rules**. The manifest itself
stays valid (its slug, tier and metadata are unaffected), but it has **no members**: indexers fail
closed rather than fall back to plain parent membership, so unpaid children never count. The first
failing check names the reason, in this order:

| Reason | Check |
| --- | --- |
| `mint_shape` | `mint` is not an object; or `type`, `criteria.mode` or `supply_locked` is wrong |
| `mint_supply` | `supply` missing or out of range |
| `mint_version` | `v` |
| `mint_seed` | `seed` |
| `mint_seed_delay` | `seed_delay` |
| `mint_opens` | `opens_at_height` |
| `mint_closes` | `closes_at_height` |
| `mint_price` | `price_koinu` |
| `mint_pay_to` | `pay_to` missing when required, or not an address |
| `mint_studio_fee` | any `studio_fee_*` rule |
| `mint_cap` | `max_per_inscriber` |
| `mint_ref` | `brain` or `recipe` present and not a canonical id |
| `mint_signer` | `signer` present and not `null` |

`collection-update` MUST NOT patch `mint` in this draft (an update with `patch.mint` is rejected
whole, as for any key outside §7's list). Retiring the manifest (§7.2) ends the drop; its members
are withdrawn with every other member claim.

## 3. Membership

Children are evaluated one at a time in position order (spec.md §2), in the block where they
complete. A child that passes every check becomes a **member** and gets the next `member_no`,
starting at 1. A child that fails is `not_member` with the first failing reason, in this order:

| Reason | Check |
| --- | --- |
| `multi_tx` | The child's body spans more than one transaction. Drop children are single-transaction inscriptions. |
| `not_open` | Hc < `opens_at_height` |
| `closed` | `closes_at_height` is set and Hc ≥ `closes_at_height` |
| `unpaid` | §4 payment check fails |
| `no_inscriber` | `max_per_inscriber` is set and the child has no inscriber |
| `inscriber_cap` | `max_per_inscriber` is set and the child's inscriber already has that many members in this drop |
| `sold_out` | The drop already has `supply` members |

A child of a manifest with invalid mint rules has no reason of its own: the drop has no members.
The outcome is final once the child's block is final. Reorgs roll it back with the block.

## 4. Payment

```
fee         = max(floor(price_koinu × studio_fee_bps / 10000), studio_fee_min_koinu)   (0 without studio_fee_to)
owed[pay_to]        += price_koinu      when price_koinu > 0
owed[studio_fee_to] += fee              when fee > 0
```

When `pay_to` and `studio_fee_to` are the same address, the two amounts add.

A child with nothing owed passes. Otherwise the funding transaction MUST confirm in a block with
M < F ≤ Hc and Hc − F ≤ 30, and for every address A in `owed`:

```
paid(T, A) − used(T, A) ≥ owed[A]
```

where `paid(T, A)` is the sum of the funding transaction's outputs whose script pays A, and
`used(T, A)` is what earlier members, of **any** drop, already used from those outputs. When the
child becomes a member, `used(T, A) += owed[A]` for each A. So one commit may fund several children
in one batch, but each koinu of output pays for one child only, and a shared venue address cannot be
counted twice across drops. A child that fails a later check (§3) uses nothing.

Paying in the funding (commit) transaction keeps the payment in the minter's own wallet flow: any
wallet that builds the commit can add the outputs, and nothing is left to settle after the reveal.

## 5. Seed: `child-blockhash-v1`

```
seed = lowercase hex of SHA-256( UTF-8( "dmp-drop-seed|1|" + child_id + "|" + blockhash(Hc + seed_delay) ) )
```

`child_id` is the canonical id. `blockhash(h)` is the block hash at height h as 64 lowercase hex in
the usual display order (what `getblockhash` returns). A brain that needs fewer bits uses a prefix
(for example the first 32 hex).

- The minter knows its child id before broadcasting, but not the hash of a block that does not exist
  yet, so grinding txids gains nothing. Nobody else holds a secret.
- Until block Hc + `seed_delay` exists the child is **unrevealed**. A reorg that replaces that block
  changes the seed; `seed_delay` (at least 3) keeps that rare.
- A member's seed is a chain fact. Indexers SHOULD serve it with the member so venues can show traits
  without running the brain.

## 6. Rendering (informative)

A brain draws a child from its seed. It needs three recursion endpoints from ord on the content
origin: `/r/inscription/<id>` (with `height`), `/r/blockheight`, and `/r/blockhash/<height>`.
A brain MUST NOT draw a piece from any other value. Where those routes are missing, or the reveal
block does not exist yet, it shows an "unrevealed" state, never a substitute piece. A child MAY name
its manifest (for example `run({manifest:"<id>"})`) so the brain reads `seed_delay` from the
manifest itself.

## 7. Venues (informative)

Venues show a drop's terms from the manifest: price, venue fee, supply, open and close heights, seed
rule. They show members by `member_no`, and `not_member` children with their reason, never as part
of the collection. A venue's own listing policy (minimum price, takedowns) is its own and is not a
membership rule.

## 8. Indexer checklist

- [ ] `mint` validation in the order of §2; invalid mint rules mean no members, not plain parent mode.
- [ ] Children in position order; reasons in the order of §3; `member_no` from 1.
- [ ] Funding transaction = input 0's previous output; window M < F ≤ Hc, Hc − F ≤ 30.
- [ ] `used` shared across drops per funding transaction and address; only members use.
- [ ] Seed over the canonical child id and the display-order block hash at Hc + `seed_delay`.
- [ ] Reorgs roll all of it back.
- [ ] `python3 reference/drop_rules.py check vectors/drop_rules_vectors.json` passes against your outputs.
