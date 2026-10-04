# Individual PoC self-review worksheet

This template records one author's technical self-review. It is not independent, organizational or
legal approval. Review the exact candidate bytes and keep the signed artifacts outside Git.

| Objective | Proposed control | Required review |
| --- | --- | --- |
| POC.MINIMIZATION | Tokenize labelled direct identifiers before inference | PoC author: synthetic field inventory and tokenization boundary |
| POC.DATA_LEAK_PREVENTION | Deny detected authentication secrets | PoC author: synthetic negative cases and classifier limits |
| POC.ACTION_AUTHORITY | Separate exact decision/action approval; terminal reconciliation | PoC author: local sandbox idempotency and investigated outcomes |
| POC.PROVIDER_CONFIGURATION | OpenAI `store=false`; Bedrock IAM and documented provider-access behavior | PoC author: exact model, region, deployment, request configuration and current sources |

Record applicability, rationale, owner role, review date/due date, unresolved risks and the candidate
policy digest. No requirement here is attributed to legislation and no organizational review is
implied.

The profiles require no enterprise-only capability assertion. The gateway must set OpenAI
`store=false`, use temporary or dedicated Bedrock credentials and constrain its entire
candidate/fallback set. A region string alone is not a data-residency guarantee.

Use two distinct Ed25519 keys for `POC_OPERATOR` and `POC_POLICY_REVIEWER`. The same individual may
control both for this demonstration, and that limitation must remain visible in the final report.
The enterprise reference under `examples/financial-pilot-enterprise/` retains the stricter future
ZDR, PrivateLink, CloudTrail and organizational-review profile.
