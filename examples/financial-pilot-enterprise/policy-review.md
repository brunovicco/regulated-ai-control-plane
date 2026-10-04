# Organization review worksheet — draft

No organizational or legal approval is recorded by this template. Assign non-personal owner roles,
review the exact candidate bytes and retain the signed review artifacts in organization custody.

| Objective | Proposed control | Required review |
| --- | --- | --- |
| ORG.PILOT.MINIMIZATION | Tokenize labelled direct identifiers before inference | Privacy owner: field inventory, classification limits, tokenization key management |
| ORG.PILOT.DATA_LEAK_PREVENTION | Deny detected authentication secrets | Security owner: synthetic negative cases and classifier coverage |
| ORG.PILOT.ACTION_AUTHORITY | Separate exact decision/action approval; terminal reconciliation | Business/system owner: concrete workload, approvers, durable downstream idempotency and investigation |
| ORG.PILOT.PROVIDER_CONFIGURATION | Reviewed OpenAI retention; Bedrock IAM/private endpoint/API audit facts | Provider owner: selected model, service, region, deployment, configuration evidence and freshness |

Record applicability, rationale, owner role, review date/due date, unresolved risks and the candidate
policy digest. No requirement here is attributed to legislation. Qualified organizational reviewers
must supply any applicable regulatory mappings through the existing policy-review workflow.

Both provider profiles start with condition assertions set to `false`. Change only assertions
supported by reviewed deployment evidence. A region string alone is not a data-residency guarantee.
The gateway workload must constrain its entire candidate/fallback set before it receives data.

Use the existing signed-pack lifecycle/onboarding review, scenario replay, release-evidence and
promotion-quorum tools. This draft is not a runtime override and is never loaded automatically.
Organization policy approval and the later pilot acceptance signatures are separate decisions.
