import re
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).parents[2]
_DEPLOY = _ROOT / "deploy" / "kubernetes"


def _documents(name: str) -> tuple[dict[str, Any], ...]:
    parsed = tuple(yaml.safe_load_all((_DEPLOY / name).read_text(encoding="utf-8")))
    assert parsed and all(isinstance(item, dict) for item in parsed)
    return parsed


def test_kustomization_uses_digest_and_complete_restricted_resources() -> None:
    kustomization = _documents("kustomization.yaml")[0]
    resources = set(kustomization["resources"])
    assert resources == {
        "namespace.yaml",
        "service-account.yaml",
        "database-migration-job.yaml",
        "deployment.yaml",
        "runtime-trust-verifier-cronjob.yaml",
        "service.yaml",
        "network-policy.yaml",
    }
    image = kustomization["images"][0]
    assert image["name"] == "example.invalid/regulated-ai-control-plane"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image["digest"])
    assert ":" not in image["newName"]

    namespace = _documents("namespace.yaml")[0]
    assert namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"


def test_deployment_is_multi_replica_non_root_and_uses_external_authority() -> None:
    deployment = _documents("deployment.yaml")[0]
    spec = deployment["spec"]
    assert spec["replicas"] == 2
    assert spec["strategy"] == {
        "type": "RollingUpdate",
        "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1},
    }
    pod = spec["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"] == {
        "runAsNonRoot": True,
        "runAsUser": 10001,
        "runAsGroup": 10001,
        "fsGroup": 10001,
        "fsGroupChangePolicy": "OnRootMismatch",
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    container = pod["containers"][0]
    assert container["image"] == "example.invalid/regulated-ai-control-plane"
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    assert {
        key
        for probe in ("startupProbe", "readinessProbe", "livenessProbe")
        for key in [container[probe]["httpGet"]["path"]]
    } == {"/health"}
    assert set(container["resources"]) == {"requests", "limits"}
    env = {item["name"]: item for item in container["env"]}
    assert env["REGULAAI_ENVIRONMENT"]["value"] == "production"
    assert env["REGULAAI_SERVICE_VERSION"]["valueFrom"]["configMapKeyRef"]["name"] == (
        "regulaai-deployment-metadata"
    )
    assert env["REGULAAI_EXECUTION_MODE"]["value"] == "mock"
    assert env["REGULAAI_DATABASE_URL"]["valueFrom"]["secretKeyRef"] == {
        "name": "regulaai-database-runtime",
        "key": "url",
    }
    assert env["REGULAAI_CONTROL_PACK_MANIFEST"]["value"].startswith("/etc/regulaai/")
    assert env["REGULAAI_TOKENIZATION_KEY"]["valueFrom"]["secretKeyRef"]["name"] == (
        "regulaai-runtime-keys"
    )
    volumes = {item["name"]: item for item in pod["volumes"]}
    assert volumes["control-pack"]["persistentVolumeClaim"]["claimName"] == (
        "regulaai-control-pack"
    )
    assert volumes["control-pack-trust"]["configMap"]["name"] == ("regulaai-control-pack-trust")
    assert all("hostPath" not in item for item in volumes.values())
    assert "data" not in volumes


def test_database_migration_is_an_explicit_restricted_job() -> None:
    job = _documents("database-migration-job.yaml")[0]
    assert job["kind"] == "Job"
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["restartPolicy"] == "OnFailure"
    container = pod["containers"][0]
    assert container["command"] == ["alembic", "upgrade", "head"]
    assert container["env"][0]["valueFrom"]["secretKeyRef"] == {
        "name": "regulaai-database-migration",
        "key": "url",
    }
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    policies = _documents("network-policy.yaml")
    migration_policy = next(
        item
        for item in policies
        if item["metadata"]["name"] == "regulaai-database-migration-default"
    )
    assert migration_policy["spec"]["ingress"] == []
    assert migration_policy["spec"]["egress"] == []


def test_runtime_verifier_is_network_silent_bounded_and_reads_mounted_assertions() -> None:
    cronjob = _documents("runtime-trust-verifier-cronjob.yaml")[0]
    spec = cronjob["spec"]
    assert spec["concurrencyPolicy"] == "Forbid"
    assert spec["jobTemplate"]["spec"]["backoffLimit"] == 1
    pod = spec["jobTemplate"]["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["restartPolicy"] == "Never"
    container = pod["containers"][0]
    assert container["command"] == ["python", "scripts/verify_runtime_trust_state.py"]
    assert "--attestation-directory" in container["args"]
    assert "--evaluated-at-now" in container["args"]
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]

    policies = _documents("network-policy.yaml")
    verifier_policy = next(
        item
        for item in policies
        if item["metadata"]["name"] == "regulaai-runtime-trust-verifier-default"
    )
    assert verifier_policy["spec"]["ingress"] == []
    assert verifier_policy["spec"]["egress"] == []


def test_openshift_overlay_defers_ids_to_restricted_scc_and_image_starts_api() -> None:
    overlay = next(
        yaml.safe_load_all(
            (_ROOT / "deploy" / "openshift" / "kustomization.yaml").read_text(encoding="utf-8")
        )
    )
    assert overlay["resources"] == ["../kubernetes"]
    removed_paths = {
        operation["path"]
        for patch in overlay["patches"]
        for operation in yaml.safe_load(patch["patch"])
    }
    assert removed_paths == {
        "/spec/template/spec/securityContext/runAsUser",
        "/spec/template/spec/securityContext/runAsGroup",
        "/spec/template/spec/securityContext/fsGroup",
        "/spec/template/spec/securityContext/fsGroupChangePolicy",
        "/spec/jobTemplate/spec/template/spec/securityContext/runAsUser",
        "/spec/jobTemplate/spec/template/spec/securityContext/runAsGroup",
        "/spec/jobTemplate/spec/template/spec/securityContext/fsGroup",
        "/spec/jobTemplate/spec/template/spec/securityContext/fsGroupChangePolicy",
    }
    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER app" in dockerfile
    assert "--extra observability" in dockerfile
    assert 'CMD ["uvicorn", "regulated_ai.entrypoints.api:app"' in dockerfile
