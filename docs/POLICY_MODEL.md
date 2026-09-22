# Policy model

## Design goal

Keep the first DSL small, explainable and deterministic.

Do not implement a general-purpose policy language in Phase 1.

## Three-layer model

```text
Authoritative source
      ↓
Human-reviewed control objective
      ↓
Executable enterprise policy
      ↓
Technical obligation / decision
```

This separation prevents code from pretending to be legal interpretation.

## Policy set

A policy set is immutable by version.

Suggested metadata:
- `id`
- `version`
- `jurisdiction`
- `sector`
- `status`
- `approved_control_objectives`
- `rules`

## Rule match dimensions

Initial rule conditions may match:
- jurisdiction;
- sector;
- purpose;
- operation kind;
- data classification;
- provider;
- service;
- region;
- tool/action risk class;
- assurance level.

Use explicit operators only:
- equals;
- in;
- contains classification;
- all/any.

Avoid arbitrary expression execution.

## Rule outputs

A matching rule may add:
- decision contribution;
- obligation;
- capability requirement;
- reason code;
- control-objective reference;
- support-source reference.

## Aggregation

Final outcome precedence:

```text
DENY
  >
REQUIRE_APPROVAL
  >
ALLOW_WITH_TRANSFORMATION
  >
ALLOW
```

Obligations are accumulated unless the final result is `DENY`; even then, evidence should retain
the matched reasons/controls without exposing payload.

## Provider capability requirement

Example concept:

```yaml
requires_capabilities:
  - key: zero_data_retention
    accepted_states: [supported, conditional]
    condition_assertions:
      eligible_organization_required: true
```

The policy/application layer must verify that required conditions are actually asserted/configured.
A `conditional` capability is not equivalent to `supported` without its conditions.

## Transformation semantics

Transformations must be executable obligations, not prose.

Examples:
- remove field;
- tokenize identifier;
- mask;
- pseudonymize.

The decision result should identify targets by logical field id/classification, not include the raw
field value.

## Authority policy

Tool/action authority is an enterprise policy layer.

Example:
- read-only account lookup -> allowed;
- state-changing card action -> approval required.

This should not be attributed to a regulator unless a reviewed mapping explicitly supports it.

## Policy schema evolution

Every policy file has a `schema_version`.

Unknown schema versions are rejected.

Backward-incompatible changes require:
- new schema version;
- migration note;
- eval/regression run;
- immutable historical evidence references.

## Policy review metadata

Production policy sets should eventually support:
- author;
- reviewer role;
- legal/privacy/security approval states;
- effective date;
- review due date;
- supersedes version.

The MVP may use synthetic metadata but preserve the fields.
