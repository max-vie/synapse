from pathlib import Path
from types import SimpleNamespace

from scripts.checks import public as public_hygiene
from scripts.checks.images import parse_image_ref
from scripts.checks.private import validate_repo


def test_image_reference_requires_valid_optional_digest():
    assert parse_image_ref("qdrant/qdrant:v1.19.0@sha256:" + "a" * 64) == ("qdrant/qdrant", "v1.19.0", "sha256:" + "a" * 64)
    try:
        parse_image_ref("qdrant/qdrant:v1.19.0@sha256:short")
    except ValueError as error:
        assert "sha256 digest" in str(error)
    else:
        raise AssertionError("invalid image digest should be rejected")


def test_candidate_files_skips_deleted_tracked_files(tmp_path: Path, monkeypatch):
    existing = tmp_path / "README.md"
    existing.write_text("# ok\n", encoding="utf-8")

    def fake_run(command, cwd, text, capture_output, check):
        if command == ["git", "ls-files"]:
            return SimpleNamespace(stdout="README.md\ndocs/archive/README.md\n")
        if command == ["git", "ls-files", "--others", "--exclude-standard"]:
            return SimpleNamespace(stdout="")
        raise AssertionError(command)

    monkeypatch.setattr(public_hygiene.subprocess, "run", fake_run)

    assert public_hygiene.candidate_files(tmp_path) == [existing]


def test_public_hygiene_accepts_benchmark_fixture_forbidden_terms(tmp_path: Path):
    path = tmp_path / "scripts" / "benchmark" / "fixtures" / "questions.yml"
    path.parent.mkdir(parents=True)
    forbidden = "enterprise-" + "ready"
    production_claim = "SOC2-ready " + "production " + "SaaS"
    path.write_text(f"forbidden_facts:\n  - {forbidden}\n  - {production_claim}\n", encoding="utf-8")

    assert public_hygiene.scan_file(tmp_path, path) == []


def test_public_hygiene_accepts_local_ollama_client_host_constant(tmp_path: Path):
    path = tmp_path / "scripts" / "benchmark" / "ollama_models.py"
    path.parent.mkdir(parents=True)
    any_bind = "0" + ".0.0.0"
    path.write_text(f'_LOCAL_HOSTS = {{"http://{any_bind}:11434"}}\n', encoding="utf-8")

    assert public_hygiene.scan_file(tmp_path, path) == []


def test_public_hygiene_still_flags_public_bind_in_docs(tmp_path: Path):
    path = tmp_path / "README.md"
    any_bind = "0" + ".0.0.0"
    path.write_text(f"Bind the demo to {any_bind} for public access.\n", encoding="utf-8")

    findings = public_hygiene.scan_file(tmp_path, path)
    assert any(f.code == "PUBLIC_BIND" for f in findings)


def test_public_hygiene_still_flags_mixed_overclaim_in_docs(tmp_path: Path):
    path = tmp_path / "README.md"
    overclaim = "enterprise-" + "ready commercial" + " product"
    path.write_text(f"This is an {overclaim}; an unsupported claim note exists.\n", encoding="utf-8")

    findings = public_hygiene.scan_file(tmp_path, path)
    assert any(f.code == "OVERCLAIM" for f in findings)


def test_public_hygiene_does_not_exempt_unrelated_negation_before_overclaim(tmp_path: Path):
    path = tmp_path / "README.md"
    overclaim = "production-" + "ready"
    path.write_text(f"This is not just a reviewer demo; it is {overclaim}.\n", encoding="utf-8")

    findings = public_hygiene.scan_file(tmp_path, path)
    assert any(f.code == "OVERCLAIM" for f in findings)


def test_public_hygiene_does_not_exempt_later_claim_after_negated_claim(tmp_path: Path):
    path = tmp_path / "README.md"
    first_claim = "production-" + "ready"
    second_claim = "enterprise-" + "ready"
    path.write_text(f"Synapse does not claim {first_claim}, but it is {second_claim}.\n", encoding="utf-8")

    findings = public_hygiene.scan_file(tmp_path, path)
    assert any(f.code == "OVERCLAIM" for f in findings)


def test_public_hygiene_does_not_exempt_next_sentence_after_negated_claim(tmp_path: Path):
    path = tmp_path / "README.md"
    first_claim = "production-" + "ready"
    second_claim = "enterprise-" + "ready"
    path.write_text(f"Synapse does not claim {first_claim}. It is {second_claim}.\n", encoding="utf-8")

    findings = public_hygiene.scan_file(tmp_path, path)
    assert any(f.code == "OVERCLAIM" for f in findings)


def test_public_hygiene_flags_production_saas_claims(tmp_path: Path):
    path = tmp_path / "README.md"
    claim = "production " + "SaaS"
    path.write_text(f"Synapse is a {claim} for customers.\n", encoding="utf-8")

    findings = public_hygiene.scan_file(tmp_path, path)
    assert any(f.code == "OVERCLAIM" for f in findings)


def test_public_hygiene_flags_commercial_saas_enterprise_customer_claims(tmp_path: Path):
    path = tmp_path / "README.md"
    claim = "commercial " + "SaaS for enterprise " + "customers"
    path.write_text(f"Synapse is a {claim}.\n", encoding="utf-8")

    findings = public_hygiene.scan_file(tmp_path, path)
    assert any(f.code == "OVERCLAIM" for f in findings)


def test_public_hygiene_accepts_negated_enterprise_customer_claims(tmp_path: Path):
    path = tmp_path / "README.md"
    claim = "enterprise " + "customers"
    path.write_text(f"Synapse has no {claim}.\n", encoding="utf-8")

    assert public_hygiene.scan_file(tmp_path, path) == []


def test_public_hygiene_does_not_exempt_fixture_labels_in_docs(tmp_path: Path):
    path = tmp_path / "README.md"
    overclaim = "enterprise-" + "ready"
    path.write_text(f"forbidden_facts label appears here, but this says {overclaim}.\n", encoding="utf-8")

    findings = public_hygiene.scan_file(tmp_path, path)
    assert any(f.code == "OVERCLAIM" for f in findings)
def test_validate_detects_private_ip(tmp_path: Path):
    private_ip = "192" + ".168.1.10"
    (tmp_path / "README.md").write_text(f"service at http://{private_ip}:1234\n", encoding="utf-8")
    findings = validate_repo(tmp_path)
    assert any(f.code == "PRIVATE_IP" for f in findings)


def test_validate_detects_docker_host_gateway_literal(tmp_path: Path):
    host_gateway = "host" + ".docker.internal"
    (tmp_path / "README.md").write_text(f"service at http://{host_gateway}:6333\n", encoding="utf-8")
    findings = validate_repo(tmp_path)
    assert any(f.code == "HOST_GATEWAY_LITERAL" for f in findings)


def test_validate_detects_inline_password_phrase(tmp_path: Path):
    sample = "default " + "password" + " hunter2 must change\n"
    (tmp_path / "notes.md").write_text(sample, encoding="utf-8")
    findings = validate_repo(tmp_path)
    assert any(f.code == "PASSWORD_PHRASE" for f in findings)


def test_validate_accepts_env_placeholders(tmp_path: Path):
    (tmp_path / ".env.example").write_text("WIKIJS_API_TOKEN=replace-with-token\n", encoding="utf-8")
    assert validate_repo(tmp_path) == []


def test_validate_accepts_runtime_env_secret_reads(tmp_path: Path):
    sample = 'OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")\n'
    (tmp_path / "config.py").write_text(sample, encoding="utf-8")
    assert validate_repo(tmp_path) == []


def test_validate_rejects_quoted_env_secret_assignments(tmp_path: Path):
    fake_value = "sk-" + "live-" + "hardcoded-" + "secret"
    (tmp_path / ".env").write_text(
        f'WIKIJS_API_TOKEN="{fake_value}"\n'
        f"DB_PASSWORD='{fake_value}'\n",
        encoding="utf-8",
    )

    findings = validate_repo(tmp_path)
    assert sum(1 for f in findings if f.code == "ENV_SECRET") == 2


def test_validate_rejects_yaml_and_json_secret_assignments(tmp_path: Path):
    fake_value = "sk-" + "live-" + "hardcoded-" + "secret"
    (tmp_path / "config.yaml").write_text(f"api_key: {fake_value}\n", encoding="utf-8")
    (tmp_path / "config.json").write_text(f'{{"apiToken": "{fake_value}"}}\n', encoding="utf-8")

    findings = validate_repo(tmp_path)
    assert sum(1 for f in findings if f.code == "ENV_SECRET") == 2


def test_validate_rejects_hardcoded_runtime_env_secret_fallback(tmp_path: Path):
    env_var = "OLLAMA_" + "API_KEY"
    fake_value = "sk-" + "live-" + "hardcoded-" + "secret"
    samples = [
        f'{env_var} = os.environ.get("{env_var}", "{fake_value}")\n',
        f'{env_var} = os.getenv("{env_var}", "{fake_value}")\n',
        f'{env_var} = env.get("{env_var}", "{fake_value}")\n',
        f'{env_var} = os.getenv("{env_var}", default="{fake_value}")\n',
        f'{env_var} = os.getenv(\n    "{env_var}",\n    "{fake_value}",\n)\n',
    ]
    for i, sample in enumerate(samples):
        (tmp_path / f"config_{i}.py").write_text(sample, encoding="utf-8")

    findings = validate_repo(tmp_path)
    assert sum(1 for f in findings if f.code == "ENV_SECRET") == len(samples)
