# ADR-0016: Verify signed policy and provider packs before runtime composition

## Status

Accepted.

## Date

2026-09-25.

## Context

RegulaAI already validates strict versioned YAML, records policy/provider versions and binds
provider provenance snapshots into decision evidence. Those controls detect malformed records and
make runtime decisions reproducible, but they do not authenticate who approved the current local
policy/provider release. An attacker or deployment error that can replace both YAML content and
declared versions could otherwise present a structurally valid but unauthorized control plane.

The runtime must remain network-silent by default. Regulatory interpretation and provider fact
review also remain human governance activities; cryptographic authenticity must not be represented
as proof that a policy is legally correct or a provider fact is current.

## Decision

Group runtime policy and provider capability YAML into a strict versioned manifest. Each entry has
one normalized relative path, record kind and SHA-256 digest. Sign a deterministic canonical JSON
projection of the manifest with Ed25519, including pack identity/version, ordered file entries,
algorithm and signing-key identifier.

At startup, before the existing YAML adapters parse records, RegulaAI:

1. strictly parses the manifest and deployment-controlled trust store;
2. rejects duplicate, absolute, traversing, symlinked, missing or oversized file paths;
3. verifies every content digest;
4. selects an explicitly trusted public key by id and verifies the signature;
5. passes the exact authenticated bytes to the existing strict policy/provider parsers, avoiding a
   verify-then-reopen filesystem race.

Package a demo public trust anchor and signature, never a private key. Provide an offline helper
that accepts an external Ed25519 PEM, refreshes digests, signs, verifies against the configured
trust store and only then replaces the manifest. Expose pack identity, version, signing-key id and
canonical payload digest as non-secret provider metadata.

## Alternatives considered

- SHA-256 manifests without signatures: rejected because they detect accidental corruption but an
  attacker able to change records could also replace the manifest.
- HMAC signatures: rejected because every verifier would hold authority to sign new releases.
- Online signature or transparency verification during startup: deferred because it adds network
  availability and external trust dependencies to the enforcement boundary.
- Sign raw concatenated YAML: rejected because path/kind metadata and deterministic ordering must
  also be authenticated.
- Embed signatures in each policy/provider schema: rejected because release composition and
  atomic version identity would remain ambiguous.

## Consequences

Unauthorized or corrupted packaged policy/provider content prevents startup. A release now has a
stable cryptographic identity independent of YAML parsing. Updating any covered record requires a
new digest and signature. Tool catalogs remain strictly validated but outside this first signed-pack
scope.

The project adds the maintained `cryptography` dependency for Ed25519. The manifest/trust schemas
and canonicalization become compatibility contracts. Existing direct construction of file
repositories remains useful in isolated tests, while the production composition root uses only a
verified pack.

## Security and privacy impact

Public keys, signature bytes, pack identifiers and content digests contain no customer payload or
secret. Private signing keys must remain outside the repository and runtime. The trust store is a
high-integrity deployment input: changing it changes who may authorize policy/provider releases.

A valid signature proves only that a trusted key authorized the exact manifest and file bytes. It
does not prove reviewer competence, legal correctness, source freshness, provider behavior or
compliance. Compromise of an authorized private key or the trust store remains a critical risk.

## Operational impact

Release automation must generate and protect an Ed25519 key, review changed records, refresh the
manifest, sign it offline and distribute the manifest, records and trust store coherently. Key
rotation requires adding a new public key and signing subsequent packs with its distinct id;
revocation and distribution policy remain organization-owned.

The service performs only bounded local reads and verification at startup. No runtime network call,
background refresh or private-key access is introduced.

## Follow-up

- Define a reviewed provider-capability update workflow and signed release promotion stages.
- Add semantic diff and decision-impact analysis between verified pack versions.
- Define key lifecycle, revocation, quorum/reviewer authorization and enterprise distribution.
- Decide whether trusted tool catalogs join the same release envelope.
- Consider external transparency or timestamp evidence only with explicit availability semantics.
