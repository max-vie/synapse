import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_update_check_module():
    path = ROOT / "scripts" / "check_image_versions.py"
    spec = importlib.util.spec_from_file_location("check_image_versions", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def image_default(compose, service, env_name):
    value = compose["services"][service]["image"]
    prefix = "${" + env_name + ":-"
    assert value.startswith(prefix)
    assert value.endswith("}")
    return value[len(prefix) : -1]


REVIEWED_IMAGE_PINS = {
    "QDRANT_IMAGE": "qdrant/qdrant:v1.18.1",
    "OLLAMA_IMAGE": "ollama/ollama:0.24.0",
    "SYNAPSE_SERVICE_IMAGE": "synapse-service:local",
    "WIKIJS_IMAGE": "ghcr.io/requarks/wiki:2.5.314",
    "WIKIJS_POSTGRES_IMAGE": "postgres:16-alpine",
}


def test_compose_service_images_use_current_reviewed_pins():
    compose = yaml.safe_load((ROOT / "docker-compose.e2e.yml").read_text(encoding="utf-8"))

    assert image_default(compose, "qdrant", "QDRANT_IMAGE") == REVIEWED_IMAGE_PINS["QDRANT_IMAGE"]
    assert image_default(compose, "ollama", "OLLAMA_IMAGE") == REVIEWED_IMAGE_PINS["OLLAMA_IMAGE"]
    assert "n8n" not in compose["services"]
    assert image_default(compose, "synapse-service", "SYNAPSE_SERVICE_IMAGE") == REVIEWED_IMAGE_PINS["SYNAPSE_SERVICE_IMAGE"]
    assert image_default(compose, "wikijs", "WIKIJS_IMAGE") == REVIEWED_IMAGE_PINS["WIKIJS_IMAGE"]
    assert image_default(compose, "wikijs-db", "WIKIJS_POSTGRES_IMAGE") == REVIEWED_IMAGE_PINS["WIKIJS_POSTGRES_IMAGE"]


def test_setup_script_generates_same_reviewed_image_pins_as_compose():
    setup_script = (ROOT / "scripts" / "e2e" / "setup.sh").read_text(encoding="utf-8")

    for env_name, image in REVIEWED_IMAGE_PINS.items():
        assert f"{env_name}={image}" in setup_script


def test_compose_requires_webhook_auth_token_and_keeps_bypass_disabled_by_default():
    compose_path = ROOT / "docker-compose.e2e.yml"
    compose_text = compose_path.read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text)
    env = compose["services"]["synapse-service"]["environment"]

    assert "SYNAPSE_WEBHOOK_AUTH_TOKEN: ${SYNAPSE_WEBHOOK_AUTH_TOKEN:-}" not in compose_text
    assert str(env["SYNAPSE_WEBHOOK_AUTH_TOKEN"]).startswith("${SYNAPSE_WEBHOOK_AUTH_TOKEN:?")
    assert env["SYNAPSE_AUTH_DISABLED"] == "${SYNAPSE_AUTH_DISABLED:-false}"


def test_setup_and_example_env_keep_auth_bypass_disabled_by_default():
    setup_script = (ROOT / "scripts" / "e2e" / "setup.sh").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "SYNAPSE_AUTH_DISABLED=false" in setup_script
    assert "SYNAPSE_AUTH_DISABLED=false" in env_example


def test_version_policy_documents_update_check_and_major_upgrade_boundary():
    policy = (ROOT / "docs" / "VERSION_POLICY.md").read_text(encoding="utf-8")

    assert "make update-check" in policy
    assert "monthly" in policy.casefold()
    assert "Trivy" in policy
    assert "major" in policy.casefold()
    assert "n8n" not in policy.casefold()


def test_makefile_exposes_manual_update_check_target():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "update-check" in makefile
    assert "scripts/check_image_versions.py" in makefile
    assert "make update-check" in makefile


def test_update_check_reports_current_reviewed_pins(monkeypatch):
    checker = load_update_check_module()
    latest = {
        "qdrant": "v1.18.1",
        "ollama": "v0.24.0",
        "wikijs": "v2.5.314",
    }
    monkeypatch.setattr(checker, "latest_github_release_tag", lambda source: latest[source.name])

    report = checker.build_report(ROOT / "docker-compose.e2e.yml")

    assert report["outdated"] == []
    pinned = {item["name"]: item["pinned"] for item in report["images"]}
    assert pinned["qdrant"] == "qdrant/qdrant:v1.18.1"
    assert "n8n" not in pinned


def test_update_check_cli_outputs_json_without_network_when_stubbed(monkeypatch):
    script = ROOT / "scripts" / "check_image_versions.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--compose-file", str(ROOT / "docker-compose.e2e.yml"), "--offline-fixture"],
        text=True,
        capture_output=True,
        check=True,
    )

    assert '"outdated": []' in completed.stdout
    assert "qdrant/qdrant:v1.18.1" in completed.stdout


def test_dockerfile_exists_and_installs_runtime_deps_at_build_time():
    dockerfile = ROOT / "Dockerfile"
    assert dockerfile.is_file(), "Dockerfile must exist for build-time dep installation"
    text = dockerfile.read_text(encoding="utf-8")
    assert "requirements/runtime.txt" in text
    assert "pip install" in text
    # The pip install must be in a RUN instruction (build time), not CMD/ENTRYPOINT
    for line in text.splitlines():
        stripped = line.strip()
        if "pip install" in stripped:
            assert stripped.startswith("RUN"), f"pip install must be in RUN (build-time), not runtime: {stripped}"


def test_dockerfile_copies_version_file():
    dockerfile = ROOT / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    lines = text.splitlines()
    copy_version_idx = None
    copy_scripts_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("COPY") and "VERSION" in line and "/app/VERSION" in line:
            copy_version_idx = i
        if line.strip().startswith("COPY") and "scripts" in line and "/app/scripts" in line:
            copy_scripts_idx = i
    assert copy_version_idx is not None, "Dockerfile must COPY VERSION /app/VERSION"
    assert copy_scripts_idx is not None, "Dockerfile must COPY scripts /app/scripts"
    assert copy_version_idx < copy_scripts_idx, (
        "COPY VERSION must come before COPY scripts so the version is available at /app/VERSION"
    )


def test_compose_files_do_not_mount_version_separately():
    """docker-compose files should not need a separate VERSION volume mount
    because the Dockerfile copies VERSION into /app/VERSION."""
    for compose_file in ["docker-compose.e2e.yml", "docker-compose.ci-e2e.yml"]:
        compose = yaml.safe_load((ROOT / compose_file).read_text(encoding="utf-8"))
        synapse = compose["services"]["synapse-service"]
        volumes = synapse.get("volumes", [])
        volume_texts = [str(v) for v in volumes]
        version_mounts = [v for v in volume_texts if "VERSION" in v]
        assert version_mounts == [], (
            f"{compose_file} should not mount VERSION separately — "
            "the Dockerfile copies it into /app/VERSION"
        )


def test_compose_build_points_to_dockerfile():
    compose = yaml.safe_load((ROOT / "docker-compose.e2e.yml").read_text(encoding="utf-8"))
    synapse = compose["services"]["synapse-service"]
    assert "build" in synapse, "synapse-service must have build directive"
    assert synapse["build"]["dockerfile"] == "Dockerfile"
    ci_compose = yaml.safe_load((ROOT / "docker-compose.ci-e2e.yml").read_text(encoding="utf-8"))
    ci_synapse = ci_compose["services"]["synapse-service"]
    assert "build" in ci_synapse, "CI synapse-service must have build directive"
    assert ci_synapse["build"]["dockerfile"] == "Dockerfile"


def test_compose_no_runtime_pip_install_in_command():
    compose = yaml.safe_load((ROOT / "docker-compose.e2e.yml").read_text(encoding="utf-8"))
    command = str(compose["services"]["synapse-service"].get("command", ""))
    assert "pip install" not in command, "synapse-service command must not pip-install at runtime"
    ci_compose = yaml.safe_load((ROOT / "docker-compose.ci-e2e.yml").read_text(encoding="utf-8"))
    ci_command = str(ci_compose["services"]["synapse-service"].get("command", ""))
    assert "pip install" not in ci_command, "CI synapse-service command must not pip-install at runtime"


def test_service_version_path_resolves_to_repo_root():
    """service.py must read VERSION from _REPO_ROOT / VERSION, which resolves
    to /app/VERSION inside the container. This test verifies the path expression
    is correct so that COPY VERSION /app/VERSION in the Dockerfile is sufficient."""
    service_source = (ROOT / "scripts" / "synapse" / "service.py").read_text(encoding="utf-8")
    assert '_REPO_ROOT = Path(__file__).resolve().parent.parent.parent' in service_source
    assert 'VERSION' in service_source
    assert 'version="0.' not in service_source and "version='0." not in service_source, (
        "service.py must not hard-code version — use _SYNAPSE_VERSION from VERSION file"
    )
