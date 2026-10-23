# ÐMP Adoption Roadmap

Version: v1.0 (Draft)
Last Updated: 2026-09-03

---

## Strategic Position

ÐMP is not a product. It is **shared infrastructure** — the marketplace language that makes Dogecoin
NFT liquidity portable, settlement auditable, and provenance permanent.

Success is not measured by stars on this repo. It is measured by how many independent implementations
converge on the same market state from chain data alone.

**The adoption hypothesis**: If ÐMP is the clearest, most complete, and most honest on-chain
marketplace standard for Dogecoin, implementers will choose it because it solves real problems they
already have — not because of marketing.

**Scale hypothesis (write budget):** Millions of users mostly look. L1 fat path is the artifact + durable
list/`psdt_hash` + sale tx (+ optional DOTC/`settle` receipt). Live books SHOULD be DogeTag + venues.
Inscribing every bid is non-conformant as a *required* market model (MUST-111). See
[spec.md Write budget](spec.md#write-budget-l1-surface-at-scale).

---

## Phase 1: Foundation (Current — v1.0)

**Goal**: Make it trivially easy to build a compliant indexer from this spec alone.

### Deliverables (this repo)

- [x] SPEC.md v1.0 — all ambiguities resolved, state machine defined, ownership model explicit
- [x] SECURITY.md — honest threat model, attack vectors, mitigations
- [x] IMPLEMENTATION-GUIDE.md — indexer architecture, storage schema, API surface, reorg handling
- [x] EXAMPLES/ — canonical JSON payloads for every op
- [x] reference-implementation/dmp_reference.py — runnable validator with test vectors
- [x] Write budget (MUST-111+) — skinny L1 defaults documented
- [ ] JSON Schema files in schemas/ directory (one per op, machine-validatable)
- [ ] Test vector suite (test_vectors.json — expected pass/fail cases for all MUST rules)
- [ ] Convergence testing: two independent indexers against real testnet data

### Success criteria for Phase 1

A developer with no prior ÐMP knowledge should be able to:

1. Read SPEC.md and understand all MUST rules completely.
2. Build a basic compliant parser that passes all test vectors.
3. Know exactly what API surface to expose.
4. Do this in under 2 weeks.

---

## Phase 2: First Production Indexer (v1.0 + Reference Indexer)

**Goal**: A real, query-able ÐMP indexer running against Dogecoin mainnet.

### What to build

A Python (or Rust) indexer that:

- Consumes Dogecoin blocks via RPC (dogecoind or wonky-dogeord-style node).
- Parses ÐMP inscriptions from script_sig content **and** DogeTag / DOTC `OP_RETURN` signals.
- Applies all MUST rules including UTXO-spend invalidation and address-match ownership.
- Treats missing chatty envelopes as normal when DogeTag / venue books cover the live tape (MUST-111).
- Exposes a REST API:
  - `GET /listings?status=active` — all active listings
  - `GET /listing/:inscription_id` — single inscription market state
  - `GET /bids?inscription_id=:id` — active bids for inscription (inscription + DogeTag where linked)
  - `GET /auctions?status=active` — live auctions
  - `GET /collection/:slug` — collection with current head
  - `GET /provenance/:inscription_id` — full provenance chain including gaps
  - `GET /orderbook?collection_id=:id` — collection-level orderbook view
  - `GET /activity?from_block=:n` — delta feed for sniper/aggregator integration

### Integration targets for Phase 2

These use cases will drive real adoption:

**1. NFT Sniper**
- Subscribe to `GET /activity?from_block=:n` for real-time new listings.
- ÐMP-indexed listings from ALL venues in one feed = unified underpriced detection.
- Provenance quality signal: filter by `provenance_gap = false` for stronger trust signals.

**2. Doginals Aggregator ("Dexscreener of Dogenals")**
- Power the price discovery dashboard from ÐMP settle records (verified on-chain sales).
- Collection-level volume, average price, floor price — all derived from ÐMP data.
- No dependence on any single marketplace's database.

**3. Launchpad**
- Collection manifests define official membership and royalties on-chain.
- Trait-level bid support via collection-target offers.
- Demand signaling from open bids visible on-chain before launch (prefer DogeTag for volume).

---

## Phase 3: Multi-Marketplace Adoption

**Goal**: Two or more independent marketplaces emitting ÐMP intents, sharing liquidity discovery.

### The pitch to existing marketplaces

Marketplace operators who adopt ÐMP gain:

1. **Access to the ÐMP liquidity pool**: listings from other ÐMP venues are discoverable on yours.
2. **Portable provenance**: sellers keep full on-chain history regardless of which frontend they use.
3. **Zero protocol fee**: ÐMP takes nothing. Your fee model is 100% yours.
4. **Competitive signal**: "ÐMP Verified" badge differentiates your platform as trustworthy.

What they give up: nothing. ÐMP is additive. Existing flows can emit ÐMP ops alongside current systems.

### Compatibility layer for existing venues

Existing marketplaces (Doggy Market, DogeLabs, etc.) can adopt ÐMP incrementally — **skinny L1 first**:

- **Emit settle ops or DOTC** for completed trades → on-chain sale proof without listing-flow changes.
- **Emit list ops with `psdt_hash`** (PSDT off-band) for new listings → shared discovery without fat envelopes.
- **Emit collection manifests** for their collections → verified creator provenance.
- **Keep live bids on DogeTag / venue books** → do not inscribe every bid war click.

Each step is independent. Marketplaces can adopt one piece without committing to full integration.
Inscription `offer` / `accept` remain available for provenance-grade negotiation; they are not the default
for chatter.

### Marketplace linking field (optional draft field)

Settle ops may include an optional `marketplace_url` or `marketplace_id` field for attribution
without affecting protocol semantics. This is not a MUST rule — purely informational.

---

## Phase 4: Protocol Maturity

**Goal**: ÐMP becomes the default standard that new Dogecoin NFT tooling builds against.

### Ecosystem components powered by ÐMP

| Component | ÐMP dependency |
|-----------|---------------|
| NFT sniper | /activity delta feed, listing state |
| Price aggregator | settle records, collection floor/volume |
| Wallet | list/bid/offer/settle inscription construction |
| Explorer | provenance chain, gap flags, trade history |
| Launchpad | collection manifest, trait bid aggregation |
| Royalty tracker | royalty_paid verification vs on-chain outputs |
| Analytics | full ÐMP event log |

### ÐMP extension points (future versions)

These are not frozen. They are intentional open questions for future community input:

- **Trait-level bid targeting**: bid against specific trait combinations within a collection
  (`criteria` extension on bid/offer targeting collection members).
- **Bundle listings**: list multiple inscriptions atomically in one intent.
- **Dutch auction op**: descending price auction with automatic settlement at floor.
- **Cross-chain bridge proof**: settle op variant referencing a bridge transaction.

Any of these can be added as new op types in future minor versions without breaking v1.0/v1.0 parsers.

---

## v1.0 Ecosystem Extensions

**Goal**: Extend ÐMP with advanced marketplace features while maintaining backward compatibility.

### New Operations in v1.0

**bundle-list op**: Atomic multi-inscription listings for collections or bundles.
- Enables "buy the set" flows in wallets and aggregators.
- Indexers aggregate bundle listings for collection-level orderbooks.

**dutch-auction op**: Descending price auctions with automatic settlement.
- Reduces seller friction: set start/end prices, indexer handles price drops.
- Sniper tools can monitor descending prices in real-time via /activity feed.

**Trait-level targeting**: Extended bid/offer criteria for collection members.
- `{"traits": {"rarity": "legendary", "background": "blue"}}` targeting.
- Launchpads can signal demand for specific traits pre-launch.
- Aggregators build trait-specific floor prices from ÐMP settle records.

### Advanced Integrations Enabled by v1.0

**1. Advanced Sniper Bots**
- Monitor dutch auctions for price drops below threshold.
- Trait-level bid alerts: "legendary blue background just listed".
- Bundle arbitrage: detect underpriced bundles vs individual floor prices.

**2. Launchpad Platforms**
- Pre-launch trait demand via targeted offers/bids.
- Royalty terms declared on every order, with automatic royalty *compliance reporting* by indexers
  (`royalty_ok`). Royalties are verified, not enforced on chain; see
  [security.md §2.1](security.md#21-what-is-guaranteed-vs-verified).
- Post-launch analytics from ÐMP provenance chains.

**3. DeFi Integrations**
- Bundle listings as collateral for Dogecoin lending protocols.
- Dutch auctions integrated with automated market makers.
- Cross-chain settlement proofs for Dogecoin-bridge ecosystems.

**4. Analytics Dashboards**
- Trait-level volume and floor tracking from settle records.
- Bundle vs individual pricing efficiency metrics.
- Provenance gap analysis for collection health scoring.

### Pre-launch Compatibility

Before public launch, v1.0 features can still be folded into the draft directly:
- Draft indexers should ignore unknown ops gracefully (MUST-005).
- New fields should remain optional or version-gated unless the spec freezes them before launch.
- Post-launch compatibility requirements start only after real on-chain use.

---

## What ÐMP Will Never Do

To prevent scope creep and stay true to the "infrastructure, not platform" philosophy:

- **Never collect fees at the protocol level.**
- **Never require a central registry or approval.**
- **Never define UI or UX — that is marketplace territory.**
- **Never assume smart contract availability — stay within Dogecoin's actual constraints.**
- **Never hide provenance gaps — always surface them honestly.**

---

## Getting Involved

If you are building a Dogecoin NFT indexer, wallet, marketplace, sniper, or aggregator and want to
implement ÐMP:

1. Read SPEC.md — it contains everything needed to build a compliant indexer.
2. Run your parser against the test vectors in `reference-implementation/`.
3. Open an issue or PR if you find spec ambiguities, gaps, or errors.
4. Self-declare compliance using the checklist in IMPLEMENTATION-GUIDE.md.

The goal is convergence — multiple independent implementations reaching identical state from chain
data alone. Every compliant implementation makes ÐMP stronger infrastructure for everyone.
