# Brazilian regulatory baseline

Verified baseline date: **2026-09-22**

## Purpose

This document identifies public Brazilian sources that motivate control objectives in the product.

It is **not legal advice**, a legal interpretation engine, or a representation that the product
makes an organization compliant.

The engineering mapping must always follow:

`regulatory/security source -> human-approved control objective -> technical policy/control`

Never implement:
`law text -> automatic runtime rule`

## LGPD

Source: Lei nº 13.709/2018 (LGPD).

Relevant engineering themes include:
- purpose and adequacy;
- necessity/minimization;
- security;
- accountability;
- treatment of personal and sensitive personal data;
- international transfer mechanisms.

The product should represent these as source references supporting organization-approved control
objectives.

## ANPD — international data transfer

Resolução CD/ANPD nº 19/2024 regulates international transfers of personal data.

For product design, the official text supports at least these factual statements:

- an international transfer must be supported by a valid legal basis and valid transfer mechanism;
- transfers must serve legitimate, specific, explicit and informed purposes;
- the transfer should be limited to the minimum necessary for its purposes;
- controller/operator must adopt effective measures capable of demonstrating observance of data
  protection rules and the effectiveness of those measures, proportionate to risk/mechanism.

Engineering implications may include control objectives for:
- data minimization before an external boundary;
- explicit provider/processing-geography assessment;
- evidence of policy decisions;
- traceable approved transfer mechanisms as enterprise metadata.

The runtime must **not** decide by itself that a transfer is legally valid. It can enforce an
organization-provided assertion/approval and the associated technical controls.

## Banco Central/CMN

### Resolução CMN nº 4.893/2021

The current text addresses cybersecurity policy and requirements for contracting relevant data
processing/storage and cloud-computing services for institutions within its scope.

Product-relevant themes include:
- provider assessment;
- security and confidentiality/integrity/availability considerations;
- monitoring/management capability;
- contractual/outsourcing governance;
- location/processing considerations for relevant external services where applicable.

Scope matters. Do not label a control as applicable to every BCB-regulated entity without an
explicit scope review.

### Resolução CMN nº 5.274/2025

This resolution amended CMN 4.893 and expanded/detailed cybersecurity controls.

The official BCB page confirms that it changes, among other provisions, the minimum-control section
of CMN 4.893. Controls described in the updated framework include themes such as:
- authentication;
- encryption;
- intrusion prevention/detection;
- information-leak prevention;
- traceability;
- vulnerability management;
- access control;
- secure configuration.

Engineering implication:
these sources can support control objectives around identity, encryption, DLP, traceability,
least privilege, secure configuration, auditability and incident handling.

Do not misrepresent this list as a provider-specific cloud-contract checklist. Some requirements
apply at the institution's cybersecurity-policy level, while cloud contracting has its own
requirements.

## Corporate policy vs regulatory source

A state-changing action such as `card.unblock` requiring human approval is an example of
**enterprise authority policy** unless a reviewed regulatory mapping says otherwise.

Do not write:
`BCB requires human approval for card.unblock`.

Instead write:
- source/control objective may require strong access control and traceability;
- enterprise policy classifies this action as high impact;
- the technical implementation requires human approval.

## Initial control-objective catalog

Suggested IDs:

- `BR.PRIV.MINIMIZE_EXTERNAL_DATA`
- `BR.PRIV.TRANSFER_CONTEXT_REQUIRED`
- `BR.PRIV.DEMONSTRABLE_CONTROLS`
- `BR.FIN.TRACEABILITY`
- `BR.FIN.ACCESS_CONTROL`
- `BR.FIN.SECURE_CONFIGURATION`
- `BR.FIN.DATA_LEAK_PREVENTION`
- `ORG.AGENT.HIGH_IMPACT_APPROVAL`

Each control objective must have:
- owner;
- status (`draft/reviewed/approved/deprecated`);
- source references;
- rationale;
- technical-control mappings;
- version;
- approval metadata outside raw policy evaluation.

## Legal-review boundary

The product should provide explicit metadata fields such as:
- `legal_interpretation_status`
- `control_owner`
- `approved_at`
- `approved_by_role`
- `review_due_at`

The open-source demo can use synthetic approval metadata. Production approval identity belongs to
the customer's governance process.
