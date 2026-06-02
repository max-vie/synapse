from pathlib import Path
from types import SimpleNamespace

import public_hygiene


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
