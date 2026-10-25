# Contributing to the Doginals Marketplace Protocol

Thank you for your interest in improving ÐMP. This document explains how the spec evolves, what kinds of contributions are welcome, and how to submit them.

---

## Philosophy

ÐMP is a **protocol specification**, not a codebase. The goal of contributions is to make the spec clearer, more complete, more secure, and more useful for developers, wallets, indexers, and AI agents — not to expand scope unnecessarily.

Good contributions:

- Fix ambiguities that could cause two compliant implementations to disagree.
- Add missing edge cases or security considerations.
- Improve code examples or JSON examples for clarity.
- Correct factual errors in the spec.
- Propose new optional fields or op types that solve real problems.

Contributions that will not be accepted:

- Changes that require a central authority, registry, or approval process.
- Changes that make the protocol less trustless or less verifiable.
- Post-launch changes that break compatibility without a compelling reason and a clear migration path.
- Scope creep: features that solve hypothetical problems no one has actually encountered.

---

## Versioning and Breaking Changes

ÐMP uses `vMAJOR.MINOR` versioning:

| Change type | Version bump | Definition |
| --- | --- | --- |
| Breaking | MAJOR | Existing valid ops become invalid under new rules, OR previously accepted ops are newly rejected |
| Additive | MINOR | New optional fields, new op types, clarifications with no behavior change |
| Editorial | None | Typos, formatting, wording improvements with zero semantic change |

Before launch, abandoned draft profiles may be replaced cleanly. After launch, breaking changes require:

1. A documented migration path — how should indexers on the old version handle new data?
2. A clear rationale — what real-world problem makes the breakage worth it?
3. A version bump in `SPEC.md` and a new entry in `CHANGELOG.md`.

If you are unsure whether your change is breaking, open a discussion issue before submitting a PR.

---

## How to Propose a Change

### Step 1 — Check for existing issues

Search open issues and PRs first. Many improvements are already in discussion.

### Step 2 — Open an issue for significant changes

For anything beyond an editorial fix, open an issue to describe the problem before writing the solution. This saves effort if the direction is wrong.

Good issue title: `"[PROPOSAL] Add bundle op for multi-item listings"`
Bad issue title: `"improve spec"`

### Step 3 — Fork and branch

```bash
git clone https://github.com/jonheaven/dmp.git
git checkout -b proposal/bundle-op
```

### Step 4 — Make your changes

Follow the existing style:

- Section headings use `##`, `###`, `####` (no `#####` or deeper).
- All JSON examples are in fenced code blocks with the `json` language tag.
- All Python pseudocode examples use the `python` language tag.
- Tables use pipe-separated columns with spaces around pipes: `| Field | Type | Required |`
- Table separator rows: `| --- | --- | --- |`
- MUST rules follow the `MUST-NNN` identifier format. New rules get the next available number.
- Field definition tables always have columns: `Field | Type | Required | Description`.

### Step 5 — Update the required files

For any substantive spec change, you MUST update:

- [ ] `SPEC.md` — the authoritative change
- [ ] `CHANGELOG.md` — an entry under a new version heading or an "Unreleased" section
- [ ] `EXAMPLES/` — update any affected example files; add new examples for new op types

For implementation-affecting changes, you SHOULD update:

- [ ] `IMPLEMENTATION-GUIDE.md` — update code snippets, compliance checklist, or storage schema as needed

### Step 6 — Submit the PR

Open a pull request against [jonheaven/dmp](https://github.com/jonheaven/dmp). The description should cover:

- What sections are affected
- Whether this is a breaking change
- Migration path (if breaking)
- Motivation and rationale
- Alternatives considered

---

## Style Guide for Spec Text

**Be precise.** Use "MUST", "MUST NOT", "SHOULD", "SHOULD NOT", and "MAY" as defined in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119):

- **MUST** / **MUST NOT** — absolute requirements. Violation = non-compliance.
- **SHOULD** / **SHOULD NOT** — strong recommendation. Deviation requires justification.
- **MAY** — optional. Compliant implementations can choose either way.

**Be concrete.** Every new field needs: type, required/optional, default value (if optional), maximum/minimum constraints, and a rationale for why it exists.

**Add examples.** Every new op type needs at minimum one complete JSON example in `SPEC.md §14` and one annotated example in `EXAMPLES/`.

**Explain the why.** Future readers — including AI agents parsing the spec — need to understand the design rationale, not just the rules. Always include a rationale note for non-obvious decisions.

---

## Breaking Change Policy

Before a breaking change is merged:

1. The change MUST be tagged `[BREAKING]` in the PR title and in `CHANGELOG.md`.
2. The PR MUST specify which existing MUST rule(s) are being changed and exactly how behavior changes.
3. The PR MUST include a migration note: what an indexer on the old version should do when it encounters ops written for the new version.
4. The PR MUST bump the MAJOR version in `SPEC.md`.
5. A minimum 14-day review period is enforced before merging breaking changes.

---

## Security Disclosures

If you discover a security issue in the protocol design — a way to forge provenance, bypass signature verification, or exploit a UTXO race condition — **do not open a public issue.**

Please describe the issue in a private message to the repository maintainers. We will work with you on a coordinated disclosure and credit you in the changelog.

---

## Code of Conduct

Be direct, technical, and respectful. Critiquing a proposal is encouraged; dismissing people is not. The goal is a better protocol, not winning arguments.

---

## Questions?

Open a discussion issue with the `question` label. If you are unsure about anything — whether a change is breaking, what the right section is, or how an edge case should be handled — ask before spending time implementing it.
