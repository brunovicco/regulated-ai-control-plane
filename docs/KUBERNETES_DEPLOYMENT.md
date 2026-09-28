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
5. use the cluster secret manager to create `regulaai-runtime-keys` with distinct
   `tokenization-key`, `decision-approval-hmac-key` and `action-approval-hmac-key` values;
6. configure backup, restore and encryption for the `regulaai-data` PVC;
7. create `regulaai-deployment-metadata` with the non-secret immutable `service-version` matching
   the image release;
8. label only approved caller pods with `regulaai.openai.com/client: "true"`.

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

## Platform differences and limits

The Kubernetes base uses UID/GID/fsGroup 10001. The OpenShift overlay removes those fixed fields so
`restricted-v2` can allocate namespace-specific identities and volume groups. Both keep non-root,
seccomp, capability and read-only-root controls.

The API uses SQLite and `ReadWriteOnce`, so the reference fixes one replica and `Recreate` strategy.
Do not increase replicas until persistence, migrations and consistency semantics are redesigned.
The default NetworkPolicy permits no egress; gateway mode needs a separate reviewed overlay with
specific DNS/HTTPS destinations and credential delivery. Cluster ingress, TLS, OIDC, external
routes, storage classes, registry authentication, backups and disaster recovery remain external.

OTLP is also inactive by default even though the image contains the observability extra. Enabling it
requires an explicit OTLP endpoint plus a narrowly reviewed DNS/HTTPS NetworkPolicy, collector
authentication/TLS, metadata residency, sampling, retention and outage monitoring. Do not add
collector credentials to the manifests or permit broad egress.
