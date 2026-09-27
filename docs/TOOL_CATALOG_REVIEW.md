# Detailed tool-catalog review

Phase 6l adds an offline pre-signing gate for changes to an existing trusted tool catalog. The gate
compares a strict candidate catalog with an authenticated approved base and requires one exact
review entry for every added, removed or modified tool.

Each entry records a non-personal owner role, one or more HTTPS implementation references, the
observed change type and an `APPROVED`, `REJECTED` or `NEEDS_REVISION` conclusion. The review file
binds the approved pack payload digest and exact candidate catalog bytes. Raw source content,
credentials, tool arguments, outputs and customer data are forbidden by the strict schema.

Run the standalone gate before signing a candidate pack:

```bash
uv run python scripts/review_tool_catalog_update.py \
  --base-manifest path/to/approved/control-pack-manifest.yaml \
  --trust-store path/to/control-pack-signing-keys.yaml \
  --candidate-catalog path/to/candidate-tools.yaml \
  --review-record path/to/tool-catalog-review.yaml
```

Exit code `0` means the detailed review passed, `2` means valid evidence blocked the change and `1`
means an input or binding was invalid. A schema change also requires the tool's `schema_version` to
change.

For release evidence, pass the record with `--tool-catalog-review-record`. A `MODIFIED` signed
tool-catalog attestation must bind this review's id, digest, reviewer role and candidate catalog
digest. The whole-catalog signature authenticates the reviewer; the detailed gate proves bounded
coverage. Neither authorizes tool arguments, execution, side effects, promotion or deployment.
