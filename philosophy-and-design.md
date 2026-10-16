# Doginals Marketplace Protocol (ÐMP)
## Philosophy and Design Decisions

Last Updated: 2026-09-03
Status: Canonical project philosophy and product architecture reference

---

## 1. Project Name and Core Philosophy

### 1.1 Canonical Name

The canonical name of this ecosystem and protocol direction is Dogenals.

### 1.2 I vs E Framing

This project intentionally draws a line between two cultural models:

- The pre-Dogenals legacy model (I for I): centralized control, gatekeeping, and extraction.
- Dogenals (this project): E for Everyone, open source, permissionless participation, and transparent rules.

The point is not cosmetic branding. The point is governance philosophy encoded into protocol and product behavior.

### 1.3 Ethos

Dogenals follows a Doge-native, Robin Hood style ethos:

- open tools over closed platforms
- protocol guarantees over private dashboards
- transparent history over opaque claims
- user choice over forced paths

---

## 2. Why ÐMP Exists

ÐMP exists to remove dependence on centralized marketplace databases and APIs.

The wire follows Satoshi + Casey: the **seller PSDT** is the contract; the **inscription** is an
indexable durable pointer. Omit implied fields. Pay venues with addresses, not labels. Keep every
marketplace op (`list` through `vote`) available. Prefer the [L1 write budget](spec.md#write-budget-l1-surface-at-scale)
so chatty bids ride DogeTag / venue books instead of fat scriptSig envelopes.

With ÐMP, market behavior is encoded as chain-verifiable intents:

- listings (durable; prefer `psdt_hash` when the parent tx is fat)
- bids / private offers (prefer DogeTag at scale; inscription when provenance-grade)
- auctions
- counteroffers, accepts, and declines (same scale preference)
- settlements and cancellations (sale tx is money truth; settle/DOTC optional receipts)
- collection provenance and governance hooks

This gives the ecosystem durable guarantees:

- portability: users can move across wallets and marketplaces without losing meaning
- verifiability: any indexer can reconstruct valid state from chain data
- resilience: market history survives the failure of any single platform
- honesty about L1 cost: Dogecoin Doginals are scriptSig (no witness discount); NFT markets scale with
  pieces + sales, not with fungible inscription-transfer spam. Dunes is the fungible answer; ÐMP is not Dunes.

ÐMP is not a branding layer. It is anti-gatekeeping infrastructure.

---

## 3. Hybrid Marketplace Strategy

### 3.1 Strategic Position

ÐMP is the default and first-class path.

The marketplace also supports raw, anonymous, off-protocol inscription moves (plain DOGE transfers with no ÐMP metadata) as an explicit decentralization choice.

### 3.2 Why Support Both Paths

- Maximum freedom: users can choose rich provenance or minimal metadata.
- Permissionless reality: no protocol should pretend off-protocol transfers do not exist.
- Honest UX: indexers should report provenance quality instead of hiding messy state.

### 3.3 Trade-Offs

ÐMP path advantages:

- complete, auditable provenance
- stronger trust signals for buyers and collectors
- better interoperability and analytics

Raw/off-protocol path advantages:

- lower friction for quick or private transfers
- minimal public metadata footprint

Raw/off-protocol path costs:

- provenance continuity breaks
- reduced buyer confidence and weaker historical guarantees

Basic chain indexing tells you the ownership path.
ÐMP tells you the full market story - what price was asked, what offers were made, how the auction resolved, and whether royalties actually flowed - all without depending on any single platform's database.

---

## 4. Incentives and Multi-Marketplace Ecosystem

ÐMP is designed as a shared public on-chain layer for Doginals markets — not as a replacement for any marketplace. Building and running a successful marketplace requires real effort: reliable indexing, smooth user experience, liquidity, marketing, support, and community trust. Marketplace operators deserve to earn for the value they deliver.

ÐMP gives every operator the choice to adopt a unified, portable on-chain standard while keeping complete control over their own frontend, branding, fees, and business model.

Why many marketplace operators may choose to support or implement ÐMP:

- Access to a significantly larger shared liquidity pool across the ecosystem
- Portable, verifiable on-chain provenance and settlement records that increase user confidence
- The ability to charge their own platform fees on any trade they close
- Greater flexibility to compete on product quality, UX, speed, and features

**Win-Win Trade Example**

1. A seller lists an inscription on Marketplace A using ÐMP.
2. Marketplace A benefits from the seller relationship and discovery.
3. A buyer on Marketplace B discovers the same listing through the shared on-chain ÐMP data.
4. Marketplace B facilitates the purchase, builds the settlement transaction (including their own marketplace fee), and broadcasts it.
5. Once confirmed, a `settle-op` is inscribed with the transaction ID, creating a public record.

In this model, Marketplace A gains visibility and Marketplace B earns the fee. Both benefit from the expanded liquidity without giving up control of their own business.

This approach creates a healthy, open, capitalistic environment where multiple teams can build successful businesses on top of the same public standard. It favors user choice and collective growth while allowing honest operators to thrive on their own terms.

This reflects the core Dogenals philosophy of “E” for Everyone: an open infrastructure layer that lets builders and operators succeed together.

---

## 5. Technical Detection of Off-Protocol Moves

Indexers must detect provenance continuity and provenance breaks deterministically.

### 5.1 Required Monitoring

- monitor mempool transactions
- monitor confirmed chain transactions
- track UTXO ownership of known inscribed outputs

### 5.2 Detection Logic

For each spend of a known inscription-carrying UTXO:

1. Parse transaction for valid ÐMP inscription metadata.
2. If valid ÐMP metadata exists:
   - process as a clean protocol action.
   - continue provenance chain.
3. If no valid ÐMP metadata exists:
   - mark inscription state with provenance_gap = true.
   - set provenance_gap_from_txid to the current spend txid.
   - persist a provenance break event in immutable audit history.

### 5.3 Operational Notes

- apply the same logic in mempool and post-confirmation contexts
- reconcile mempool events on reorg and replacement scenarios
- keep provenance-gap events append-only for auditability

---

## 6. UI and UX Guidelines

The frontend must make provenance status obvious and understandable.

### 6.1 Visual Status Rules

- ÐMP-tracked items: prominent green ÐMP Verified badge.
- Off-protocol items: neutral or gray badge with explicit warning:
  - Provenance broken - anonymous move detected.

### 6.2 Listing Flow Rules

Default listing flow should steer users to ÐMP.

A clearly labeled alternative must exist:

- Quick and Private (skip ÐMP)

This option should include plain-language trade-off messaging:

- faster and less metadata
- weaker provenance and trust signals

### 6.3 Marketplace Communication

- never hide provenance gaps
- never imply raw/off-protocol items are ÐMP-verified
- let users filter by provenance quality
- include tooltip or detail-panel explanation for badge states

---

## 7. Long-Term Vision

Dogenals is not framed as a war to erase other ecosystems.

The legacy centralized model and Dogenals can coexist, similar to how different tools can coexist for different jobs.

Our strategy is to win mindshare by shipping better values and better tech:

- open source over gatekeeping
- protocol truth over platform narrative
- user choice over control
- transparent provenance over black-box claims

If we execute well, developers, collectors, and marketplaces choose Dogenals because it is more honest, more composable, and more aligned with the spirit of Dogecoin.

---

## 8. Contribution Direction

Contributors should preserve these invariants in all future proposals:

- Dogenals naming remains canonical
- ÐMP remains first-class and encouraged
- raw/off-protocol support remains available
- provenance-gap detection remains mandatory behavior for indexers
- UX must clearly separate verified provenance from anonymous moves

Design changes that weaken these invariants should be treated as high-risk and require explicit justification.
