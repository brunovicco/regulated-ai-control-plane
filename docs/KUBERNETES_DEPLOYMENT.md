# Kubernetes and OpenShift deployment reference

Phase 6s provides manifests to render and review. Repository commands never apply them to a cluster.
The base starts in network-silent mock mode and intentionally uses a non-routable image location.

## External prerequisites

Before rendering for deployment:

1. build, scan and sign the image from a reviewed commit;
2. replace `newName` and `digest` in `deploy/kubernetes/kustomization.yaml` with the approved registry
   repository and immutable SHA-256 digest—never a tag alone;
3. provision `regulaai-control-pack` as a read-only-at-runtime PVC populated from the independently
   verified Phase 6r OCI package while preserving manifest-relative paths;
4. create `regulaai-control-pack-trust` with the public `control-pack-signing-keys.yaml` key;
5. create `regulaai-api-identity` with non-secret `issuer`, `audience` and `jwks.json` entries for
   the reviewed enterprise EdDSA token issuer; private IdP keys and access tokens remain external;
6. use the cluster secret manager to create `regulaai-runtime-keys` with `tokenization-key`, and
   create the `regulaai-operator-authority-trust` ConfigMap containing only the reviewed
   `operator-authority-keys.yaml` Ed25519 public trust store; private issuer keys must remain
   outside the cluster runtime;
7. provision PostgreSQL with TLS, least-privilege runtime and migration identities, then create the
   separate `regulaai-database-runtime` and `regulaai-database-migration` Secrets whose `url` keys
   carry the corresponding least-privilege identities from the cluster secret manager;
8. configure encrypted backups, point-in-time recovery, retention and restore exercises for the
   PostgreSQL database;
9. create `regulaai-deployment-metadata` with the non-secret immutable `service-version` matching
   the image release;
10. label only approved caller pods with `regulaai.openai.com/client: "true"`.

Do not place private keys, HMAC keys or credentials in Kustomize files, ConfigMaps, command lines or
Git. Admission policy should verify the image signature/digest and reject privileged exceptions.

## Runtime trust-state verifier

The CronJob additionally expects a read-only `regulaai-runtime-trust-input` PVC containing:

```text
trust-store.yaml
checkpoint.yaml
checkpoint-public-key.pem
runtime-policy.yaml
attestation-trust-store.yaml
attestations/*.yaml
```

Create `regulaai-runtime-trust-settings` with the non-secret
`checkpoint-signing-key-id`. A producer outside this verifier must populate signed assertions; the
CronJob has no service-account token, no network egress and no signing key. It captures current UTC
once per run, emits only the metadata report to stdout and exits nonzero when coverage is blocked.
Route failed-job alerts and logs through deployment-owned metadata-only controls.

## Render and inspect

```bash
kubectl kustomize deploy/kubernetes > /tmp/regulaai-kubernetes.yaml
kubectl apply --dry-run=server -f /tmp/regulaai-kubernetes.yaml

kubectl kustomize deploy/openshift > /tmp/regulaai-openshift.yaml
oc apply --dry-run=server -f /tmp/regulaai-openshift.yaml
```

The server-side dry run contacts the selected cluster and is intentionally an operator action, not a
repository quality-gate step. Review the complete rendered output and admission results before an
approved apply.

## Database migration and rollout

The base contains a restricted `regulaai-database-migration` Job. A deployment pipeline must apply
and wait for that Job before rolling out the API; Kustomize itself does not impose resource order.
Use an immutable Job name per release or delete a successfully completed prior Job through the
deployment platform before applying the next revision.

```bash
kubectl apply -f <rendered-migration-job.yaml>
kubectl wait --for=condition=complete --timeout=5m job/regulaai-database-migration
kubectl rollout status deployment/regulaai-control-plane --timeout=5m
```

The migration identity should own DDL. The runtime identity should have only the DML and sequence
permissions required by the migrated tables. The API verifies the exact Alembic revision at startup
and fails closed instead of creating tables.

Before production acceptance, restore a backup into a separate non-production database, run the
schema check and exercise concurrent enforcement/action claims. Record only metadata and artifact
digests from the exercise.

Production startup also requires the mounted operator-authority trust store. Validate one synthetic
`ra1e`, `ra2e` and `rr1e` assertion according to each key's configured scope after a key rotation;
never inject the issuer private key into an API pod. See `OPERATOR_AUTHORITY.md`.

The API also requires the mounted enterprise JWKS plus exact issuer/audience configuration. Verify
runtime, operator and reconciler tokens separately, confirm missing/wrong-role tokens fail closed,
and rotate only after the new public key is present on every replica. See `API_IDENTITY.md`.

## Platform differences and limits

The Kubernetes base uses UID/GID/fsGroup 10001. The OpenShift overlay removes those fixed fields so
`restricted-v2` can allocate namespace-specific identities and volume groups. Both keep non-root,
seccomp, capability and read-only-root controls.

The API uses PostgreSQL and the base runs two replicas with a rolling strategy. SQLite remains only
the local and controlled-pilot default. The default NetworkPolicy permits no egress; production
requires a reviewed overlay limited to the exact PostgreSQL endpoint, and gateway mode additionally
needs specific DNS/HTTPS destinations. JWT verification is network-silent; cluster ingress, TLS,
token issuance, MFA, external routes, registry authentication, database availability, backups and
disaster recovery remain external.

OTLP is also inactive by default even though the image contains the observability extra. Enabling it
requires an explicit OTLP endpoint plus a narrowly reviewed DNS/HTTPS NetworkPolicy, collector
authentication/TLS, metadata residency, sampling, retention and outage monitoring. Do not add
collector credentials to the manifests or permit broad egress.
