# Evaluation and regression strategy

## Principle

The MVP's critical behavior is deterministic policy/enforcement logic. Test it as software, not as
an LLM benchmark.

No LLM-as-judge is required in Phase 1.

## Layers

### Unit tests

Pure domain behavior:
- decision precedence;
- obligation aggregation;
- capability state semantics;
- freshness logic;
- canonical digest generation;
- classification value objects.

### Contract tests

Adapters:
- YAML policy schema;
- provider capability schema;
- evidence persistence;
- HTTP request/response mapping.

### Scenario evals

Table-driven end-to-end cases from normalized request to decision/evidence.

Each scenario should declare:
- input metadata;
- expected classifications;
- expected decision;
- expected obligation types;
- expected reason codes;
- forbidden output substrings/values.

### Security regression

Include sentinel values that must never appear in:
- structured logs;
- evidence record;
- error messages;
- traces captured by test exporter.

## Minimum scenario set

1. no sensitive classes + approved provider -> allow;
2. CPF + external provider -> tokenize/remove according to demo policy;
3. secret pattern -> deny external inference;
4. mandatory capability unknown -> deny/fail closed;
5. mandatory capability unsupported -> deny;
6. capability conditional but condition not asserted -> deny;
7. capability conditional and approved condition asserted -> continue;
8. stale high-assurance provider record -> deny/fail closed;
9. high-impact state-changing tool -> require approval;
10. read-only tool -> no approval obligation;
11. one rule allows and another denies -> deny;
12. transform + approval -> require approval with transform obligation preserved;
13. malformed policy YAML -> startup/load failure;
14. unsupported schema version -> load failure;
15. evidence contains hashes/labels but no raw values;
16. identical versioned input -> identical decision digest;
17. policy version change -> different evidence/version metadata;
18. provider registry version change -> different evidence/version metadata;
19. fallback target lacks mandatory capability -> reject fallback;
20. no live network dependency.

## Quality targets

For Phase 1:
- 100% pass on deterministic scenario suite;
- no flaky tests;
- no live cloud credentials;
- strict type checking clean;
- negative privacy assertions around evidence/logging;
- coverage focused on policy branches and invariants, not vanity percentage.

## Future evals

Later phases may add:
- classifier quality datasets;
- adversarial prompt/tool tests;
- provider adapter contract tests;
- red-team suites;
- latency/throughput;
- false-positive/false-negative privacy classifier analysis;
- approval workflow replay;
- policy drift impact analysis.
