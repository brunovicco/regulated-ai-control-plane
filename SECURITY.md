# Security Policy

Security and privacy are part of the product boundary of Regulated AI Control Plane. Reports that identify ways to bypass policy enforcement, leak sensitive data, weaken evidence integrity, or cross authority boundaries are especially valuable.

## Supported versions

The project is currently **pre-alpha** and has no stable release line. Until the first tagged release, security fixes apply to the latest commit on the default branch.

| Version | Supported |
|---|---|
| Default branch (`main`) | Yes |
| Older commits/forks | No |
| Unreleased local modifications | No |

## Reporting a vulnerability

Please report security vulnerabilities privately through GitHub Security Advisories:

<https://github.com/brunovicco/regulated-ai-control-plane/security/advisories/new>

Do **not** open a public issue for a vulnerability that could expose sensitive data, bypass enforcement, enable unauthorized actions, or compromise credentials.

A useful report includes the affected commit/version, component, reproduction steps, security/privacy impact, expected vs actual behavior and any suggested mitigation.

Do not include production credentials, real customer data, real personal/sensitive personal data or third-party secrets.

The project will aim to acknowledge a complete report within seven calendar days. Remediation and coordinated-disclosure timing depend on severity and complexity.

## High-priority security scope

Reports are especially relevant for:

- policy-evaluation bypasses;
- cases where `DENY` or `REQUIRE_APPROVAL` can be downgraded;
- provider fallback that weakens mandatory controls;
- stale or `unknown` provider capabilities incorrectly treated as trusted;
- transformation bypass before an external trust boundary;
- raw personal data, prompts, responses, secrets or credentials written to evidence;
- sensitive information leaked through logs, traces or error messages;
- evidence tampering or incorrect version attribution;
- approval spoofing or replay;
- unauthorized tool/action execution;
- malicious policy/capability files causing code execution;
- unsafe YAML/object deserialization;
- path traversal or arbitrary file access;
- SSRF or arbitrary outbound access in future provider adapters;
- authentication/authorization failures once those features exist;
- dependency or supply-chain weaknesses.

## Security invariants

1. A model cannot grant itself authority or override policy.
2. `DENY` has the strongest decision precedence.
3. Mandatory `unknown` capability fails closed.
4. Stale high-assurance capability information fails closed.
5. Required transformations occur before provider execution.
6. Fallback cannot silently weaken mandatory controls.
7. Evidence is metadata-only.
8. Logs and traces do not contain raw sensitive payloads.
9. Policy and provider-capability data are versioned and validated.
10. External input is treated as untrusted.

## Sensitive data handling

Never use real production data for testing or demonstration. Examples and tests should use synthetic values specifically created for the project.

Raw prompts, model responses, personal data, credentials, API keys and unredacted tool payloads must not be persisted in the evidence ledger.

## Dependency and secret hygiene

- Do not commit `.env` files containing secrets.
- Keep credentials outside source control.
- Prefer environment-variable names or workload identity over static credentials.
- Review dependencies for maintenance, vulnerabilities and licensing.
- Keep external calls bounded by explicit timeouts.
- Do not introduce a dependency solely to avoid implementing a small deterministic boundary.

## Regulatory boundary

Security controls and framework mappings in this repository are technical support mechanisms. They do not constitute legal advice, regulatory certification or a guarantee of compliance with LGPD, ANPD rules, CMN/BCB regulation, ISO/IEC 42001, NIST guidance or any other framework.

## Out of scope

The following are not security vulnerabilities by themselves:

- disagreement with a regulatory interpretation documented as requiring human review;
- missing support for a provider or regulation not declared as implemented;
- absence of live provider execution during the pre-alpha decision-engine phase;
- use of synthetic demo policies explicitly marked as examples.
