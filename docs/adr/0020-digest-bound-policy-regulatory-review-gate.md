# ADR-0020: Gate policy drafts with digest-bound regulatory review

## Status

Accepted.

## Date

2026-09-26.

## Context

Executable policy rules refer to organization-approved control objectives and may include
regulatory-support identifiers. Phase 6a authenticates completed releases and Phases 6b/6c expose
potential and observed impact, but they do not prove that a human reviewed the regulatory mapping
of an exact policy draft before signing. Treating a signature or successful regression replay as
legal approval would collapse the required source, objective and technical-control layers.

Automatically retrieving or interpreting legal text would also create untrusted-content,
availability and false-certainty risks. A free-form approval note would not bind the reviewer
assertion to the approved lineage, exact candidate bytes or changed rules.

## Decision

Add an offline pre-signing gate for updates to one policy set already present in an authenticated
base pack. Parse the candidate policy from exact bounded bytes and require a strict review record
bound to the base pack payload digest, candidate policy digest, policy-set id, review date and a
non-personal reviewer role.

Compare rules by stable rule id and require coverage for every added, modified or removed rule.
Each rule review must reproduce the exact change type, control-objective identifiers and
regulatory-support references from the relevant candidate or removed base rule. Changed policy-set
metadata fields must also be named explicitly. A modified rule must advance its own version, a
changed candidate rule must retain at least one control objective, and the policy-set version must
advance.

Rules with regulatory-support references pass only with `APPROVED`. `REJECTED`, `NEEDS_REVISION`
and `NOT_APPLICABLE` block them. Rules without regulatory-support references are treated as
enterprise policy and pass only with `NOT_APPLICABLE`; this prevents the workflow from presenting
an internal authority decision as a regulatory requirement. Emit deterministic metadata-only JSON
and never invoke signing or promotion.

## Alternatives considered

- Infer regulatory approval from a valid pack signature: rejected because release authority and
  legal/regulatory review are different trust decisions.
- Execute or classify regulatory text automatically: rejected because interpretation and scope
  remain human-owned and external content is untrusted.
- Accept one policy-level approval boolean: rejected because it cannot show coverage of each
  changed rule or bind the exact objective/source mappings.
- Require regulatory references on every rule: rejected because organization authority policy may
  be intentionally independent of a regulatory source.
- Include source text, reviewer notes or personal identity: rejected because the gate needs only
  bounded metadata and those fields expand privacy, retention and prompt-injection exposure.

## Consequences

Policy drafts now have a reproducible, fail-closed review artifact before signing. Reviewers and CI
can distinguish invalid binding/lineage input from a structurally valid but blocked conclusion.
Rule identifiers, mappings and report schemas become governance contracts that require controlled
evolution.

The gate does not validate source applicability, reviewer competence, legal correctness or runtime
behavior. Removing a rule is reviewable against its base mappings, while added and modified rules
are reviewed against candidate mappings.

## Security and privacy impact

Review files contain policy/rule/control/source identifiers, conclusions, dates, digests and a
non-personal role. They contain no law text, quotes, prompts, customer data, credentials, private
keys or personal reviewer identity. Reports expose only allowlisted identifiers and findings.

Digest binding detects substitution of the base or draft but does not authenticate the human
reviewer. A malicious or mistaken conclusion, compromised trust store or authorized signing-key
compromise remains outside the guarantee.

## Operational impact

The CLI performs bounded local reads, signature verification, strict parsing and deterministic
comparison without network calls or mutation. Exit code 0 means the review gate passed, 1 means
invalid verification/schema/binding/lineage input and 2 means a valid review was blocked.

Organizations may place the command before an external signing job. Passing still grants no key
access and must not be interpreted as release promotion authority or a compliance statement.

## Follow-up

- Add organization-owned reviewer authentication, quorum and signed attestations.
- Define controlled onboarding for new policy sets and a versioned control-objective catalog.
- Bind complete-pack diff and scenario-replay evidence into an external promotion workflow.
- Add source-catalog lifecycle evidence without storing licensed or mutable source content.
- Version review/report schemas before external systems depend on them.
