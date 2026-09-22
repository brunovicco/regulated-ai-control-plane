# Regulated AI Control Plane — Starter Pack

Working product name: **RegulaAI**  
Suggested repository: `regulated-ai-control-plane`  
Suggested Python package: `regulated_ai`

This package is intended to be copied into a repository generated from
`brunovicco/codex-python-engineering-harness`.

## Suggested bootstrap

```bash
python bootstrap.py \
  --name regulated-ai-control-plane \
  --package regulated_ai \
  --target ../regulated-ai-control-plane \
  --profile service \
  --governance-profile agentic \
  --governance-overlay iso-iec-42001 \
  --governance-overlay nist-sp-800-53 \
  --git-init \
  --lock
```

Then copy the contents of this starter pack into the generated repository.
Do not replace the harness-generated `AGENTS.md`; the Codex prompt asks the
agent to amend it minimally with project-specific references.

## Read order

1. `CODEX_BOOTSTRAP_PROMPT.md`
2. `docs/PROJECT_CONTEXT.md`
3. `docs/PRODUCT_VISION.md`
4. `docs/PRODUCT_ARCHITECTURE.md`
5. `docs/DOMAIN_MODEL.md`
6. `docs/REGULATORY_BASELINE_BR.md`
7. `docs/PROVIDER_CAPABILITY_REGISTRY.md`
8. `docs/POLICY_MODEL.md`
9. `docs/API_CONTRACT.md`
10. `docs/THREAT_MODEL.md`
11. `docs/EVAL_STRATEGY.md`
12. `docs/MVP_ROADMAP.md`
13. `docs/ADRs/*`
14. `SOURCES.md`

## Important boundary

This project does **not** claim to provide legal advice, certification, or automatic regulatory
compliance. It provides a technical control plane that can encode organization-approved controls,
enforce them at runtime, and generate evidence about what the system actually did.
