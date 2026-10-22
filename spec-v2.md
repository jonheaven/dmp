# Moved: ÐMP 1.0 — Compact Signed Orders

This document is now **[compact-orders.md](compact-orders.md)**.

ÐMP has not launched, so there is no "ÐMP v2". The compact signed orders that were drafted here as "v2"
are part of **ÐMP 1.0**, together with the ops in [spec.md](spec.md). Section numbers are unchanged, so
`spec-v2.md §N` is `compact-orders.md §N`.

Nothing on the wire changed:

- A compact order still carries `"v":"2"`. That value is the compact-order wire marker, not a protocol
  version.
- The `asig` message prefix is still `dmp-v2-asig:`.
- Schemas, vectors and reference code keep their `-v2` / `_v2` file names.

The old "v1 list" format (spec.md §4.1 `list` with an embedded `psdt` or a `psdt_hash`) is now called
the **draft list format (pre-1.0)**. Wallets and venues MUST NOT create new draft lists, and indexers
SHOULD ignore them (compact-orders §2, §15).

Migration notes: [MIGRATION-from-draft.md](MIGRATION-from-draft.md).
