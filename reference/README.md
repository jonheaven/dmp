# Reference Implementation

This folder contains the minimal ÐMP v1.0 reference parser and validator.

This is the reference implementation - all other indexers should match this behavior for:

- top-level envelope checks
- op recognition
- required field validation
- `offer_fee` / `fee_recipient` enforcement for `offer`
- basic format checks for inscription ids, txids, and integer-string amounts
- provenance-gap flagging semantics
- canonical JSON signature verification for signed ops

It is intentionally small and readable so teams can compare behavior quickly before building full production indexers.

## What It Validates

- `p` must equal `dmp`
- `v` must be `1.1` or `1.2`
- `op` must be recognized
- required fields per operation must be present (including v1.0 additions like `canceller`, `transfer_type`)
- conditional target requirements for `offer`
- simple format checks for ids, txids, and amount fields
- soft warning when payload exceeds 4 KB
- Real Dogecoin signed-message signature verification for `collection`, `collection-update`, and `cancel` (when `sig` present)

## What Is Stubbed

- chain lookups and UTXO ownership validation
- royalty output verification against a live Dogecoin transaction
- full state machine resolution across listings, offers, cancels, and settlements

## Run It

Validate a JSON file:

```bash
python reference/dmp_reference.py validate EXAMPLES/offer-op.json
```

Validate raw JSON text:

```bash
python reference/dmp_reference.py validate-raw '{"p":"dmp","v":"1.0","op":"offer","offer_target_type":"inscription","inscription_id":"aaaabbbbccccddddeeeeffff0000111122223333444455556666777788889999i0","buyer":"D...","price":"100000000","currency":"DOGE","offer_fee":"100000000","fee_recipient":"D..."}'
```

Run the provenance-gap stub:

```bash
python reference/dmp_reference.py demo-gap --ownership-changed
```

## Intended Use

- Compare parser behavior across teams early.
- Catch obvious schema drift before mainnet testing.
- Give wallets, marketplaces, and indexers one small runnable baseline.

Production implementations will need real chain ingestion, signature verification, transaction output inspection, rollback handling, and durable state storage.

## ÐMP v2 compact orders: `dmp_v2_reconstruct.py`

An independent reconstructor for [spec-v2.md](../spec-v2.md). It shares no code with dogex or dojak: it parses a
v2 order, rebuilds the canonical template and PSDT bytes (§5), verifies the SINGLE|ACP signature, checks fill
compliance (§8), and verifies `asig` (§7.2) with its own canonicalizer and its own pubkey recovery.
It needs `pip install ecdsa`.

```bash
python3 reference/dmp_v2_reconstruct.py vectors vectors/dmp_v2_vectors.json      # every vector, expect "ALL MATCH"
python3 reference/dmp_v2_reconstruct.py order order.json --parent-hex <raw parent tx hex>
python3 reference/dmp_v2_reconstruct.py order order.json --rpc http://127.0.0.1:18332 --rpc-auth user:pass   # regtest node
```
