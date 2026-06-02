from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dependabot_is_not_configured():
    assert not (ROOT / ".github" / "dependabot.yml").exists()


def test_renovate_is_not_configured():
    assert not (ROOT / "renovate.json").exists()


def test_ci_runs_monthly_dependency_security_scan_and_uploads_sbom():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    on_config = workflow["on"]

    assert {schedule["cron"] for schedule in on_config["schedule"]} == {"0 9 1 * *"}
    assert "dependency-security" in workflow["jobs"]
    job = workflow["jobs"]["dependency-security"]
    step_text = "\n".join(str(step) for step in job["steps"])
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in step_text
    assert "python -m pip install -r requirements/dev.txt" in step_text
    assert "scripts/ci/scan-images.sh" in step_text
    assert "trivy" in step_text.casefold()
    assert "sbom" in step_text.casefold()
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in step_text


def test_image_scan_script_generates_sboms_and_honors_trivy_exit_code():
    script = (ROOT / "scripts" / "ci" / "scan-images.sh").read_text(encoding="utf-8")

    assert "TRIVY_IMAGE" in script
    assert "aquasec/trivy:" in script
    assert "TRIVY_EXIT_CODE" in script
    assert '--exit-code "$trivy_exit_code"' in script
    assert "--format cyclonedx" in script
    assert "--severity HIGH,CRITICAL" in script
    assert "scripts/check_image_versions.py" in script


def test_update_check_script_exists_and_references_compose():
    script = ROOT / "scripts" / "check_image_versions.py"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "docker-compose" in text
    assert "latest_github_release_tag" in text


def test_makefile_exposes_update_check_target():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "update-check" in makefile
    assert "scripts/check_image_versions.py" in makefile
    assert "make update-check" in makefile


def test_version_policy_documents_automated_dependency_security_loop():
    policy = (ROOT / "docs" / "VERSION_POLICY.md").read_text(encoding="utf-8")

    assert "Dependabot" not in policy
    assert "Renovate" not in policy
    for required in [
        "monthly CI",
        "Trivy",
        "SBOM",
        "make update-check",
        "scripts/ci/scan-images.sh",
    ]:
        assert required in policy


def test_accepted_security_findings_file_does_not_exist():
    """SECURITY_ACCEPTED_FINDINGS.md was removed — accepted findings are tracked
    in Git history, not in a standing file that could become stale."""
    assert not (ROOT / "docs" / "SECURITY_ACCEPTED_FINDINGS.md").exists()


def test_actionlint_knows_real_stack_self_hosted_runner_label():
    config = yaml.safe_load((ROOT / ".github" / "actionlint.yaml").read_text(encoding="utf-8"))

    labels = config["self-hosted-runner"]["labels"]
    assert "synapse-real-stack" in labels
