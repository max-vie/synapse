from pathlib import Path

from validate import validate_repo


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
