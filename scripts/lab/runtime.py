"""Deep local-lab lifecycle module behind the `scripts.lab` command."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from . import collection, envfile

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = ROOT / ".env"
DEFAULT_COMPOSE_FILE = ROOT / "docker-compose.e2e.yml"
CI_COMPOSE_FILE = ROOT / "docker-compose.ci-e2e.yml"


class LabError(RuntimeError):
    """An actionable local-lab failure safe to show to users."""


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class Lab:
    """Own Docker Compose, environment, health, and proof lifecycle behavior."""

    def __init__(
        self,
        *,
        root: Path = ROOT,
        env_path: Path | None = None,
        compose_path: Path | None = None,
        run: RunCommand = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.root = root.resolve()
        self.env_path = (env_path or self.root / ".env").resolve()
        self.compose_path = (compose_path or self.root / "docker-compose.e2e.yml").resolve()
        self._run = run
        self._sleep = sleep
        self._compose_prefix: list[str] | None = None
        self._use_docker_group = False

    def _exec(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
        capture: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        return self._run(
            list(args),
            cwd=self.root,
            env=merged_env,
            text=True,
            capture_output=capture,
            check=check,
        )

    def initialize(self, *, force: bool = False) -> bool:
        created = envfile.create_from_template(self.root / ".env.example", self.env_path, force=force)
        migrated = envfile.migrate_legacy_secrets(self.env_path)
        if created:
            print(f"[OK] Created private environment file: {self.env_path}")
        else:
            print(f"[OK] Using existing environment file: {self.env_path}")
        if migrated:
            print(f"[OK] Migrated inline secrets to: {envfile._secret_dir(envfile.load(self.env_path), env_path=self.env_path)}")
        return created or migrated

    def environment(self) -> dict[str, str]:
        try:
            return envfile.resolve_secret_values(envfile.load(self.env_path), env_path=self.env_path)
        except envfile.EnvFileError as exc:
            raise LabError(str(exc)) from exc

    def _select_compose(self) -> list[str]:
        if self._compose_prefix is not None:
            return self._compose_prefix
        docker_compose = self._exec(["docker", "compose", "version"], check=False, capture=True)
        if docker_compose.returncode == 0:
            self._compose_prefix = ["docker", "compose"]
        elif shutil.which("docker-compose"):
            self._compose_prefix = ["docker-compose"]
        else:
            raise LabError("Docker Compose is required")

        docker_info = self._exec(["docker", "info"], check=False, capture=True)
        if docker_info.returncode != 0:
            if not shutil.which("sg"):
                raise LabError("Docker daemon is not reachable; open a fresh shell with Docker group access")
            group_info = self._exec(["sg", "docker", "-c", "docker info"], check=False, capture=True)
            if group_info.returncode != 0:
                raise LabError("Docker daemon is not reachable; open a fresh shell with Docker group access")
            self._use_docker_group = True
        return self._compose_prefix

    def compose(
        self,
        *args: str,
        check: bool = True,
        capture: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        base = [*self._select_compose(), "--env-file", str(self.env_path), "-f", str(self.compose_path)]
        values = self.environment()
        if values.get("OLLAMA_CLOUD_MODE", "").strip().casefold() in {"1", "true", "yes", "on"}:
            overlay = self.root / "docker-compose.cloud-e2e.yml"
            if not overlay.exists():
                raise LabError(f"Ollama Cloud overlay is missing: {overlay}")
            base.extend(["-f", str(overlay)])
        command = [*base, *args]
        if self._use_docker_group:
            command = ["sg", "docker", "-c", shlex.join(command)]
        return self._exec(command, check=check, capture=capture)

    @staticmethod
    def _http_status(url: str, *, timeout: float = 5.0) -> int:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                response.read()
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except (OSError, TimeoutError, urllib.error.URLError):
            return 0

    def wait_http(self, name: str, url: str, *, attempts: int, delay: float = 2.0) -> None:
        for _ in range(attempts):
            status = self._http_status(url)
            if 200 <= status < 300:
                print(f"[OK] {name}: {url}")
                return
            self._sleep(delay)
        raise LabError(f"{name} did not become ready at {url}")

    @staticmethod
    def _request_json(url: str, payload: dict[str, Any] | None = None, method: str | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"} if payload is not None else {},
            method=method or ("POST" if data is not None else "GET"),
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:240]
            raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
        return json.loads(raw) if raw else {}

    def pull_models(self, values: Mapping[str, str] | None = None) -> None:
        values = values or self.environment()
        internal = "http://ollama:11434"
        ollama_base = values.get("OLLAMA_INTERNAL_BASE_URL", internal).rstrip("/")
        chat_base = (values.get("OLLAMA_CHAT_BASE_URL") or ollama_base).rstrip("/")
        models: list[str] = []
        if ollama_base == internal:
            models.append(values.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"))
        if chat_base == internal:
            models.extend(
                [
                    values.get("OLLAMA_FORMAT_MODEL", "tinyllama:latest"),
                    values.get("OLLAMA_ANSWER_MODEL", "tinyllama:latest"),
                ]
            )
        for model in dict.fromkeys(model for model in models if model):
            print(f"Pulling Ollama model: {model}")
            self.compose("exec", "-T", "ollama", "ollama", "pull", model)

    def ensure_collection(self, values: dict[str, str] | None = None) -> dict[str, Any]:
        values = values or self.environment()
        result = collection.ensure_collection(values, env_file=self.env_path, request_json=self._request_json)
        print(
            f"[OK] Qdrant collection {result['collection']} "
            f"({result['embedding_model']}, {result['embedding_dimension']} dimensions)"
        )
        return result

    def start_service(self) -> None:
        values = self.environment()
        self.compose("--profile", "full", "up", "-d", "--build", "--force-recreate", "synapse-service")
        port = values.get("SYNAPSE_SERVICE_PORT", "15515")
        self.wait_http("Synapse API", f"http://127.0.0.1:{port}/readyz", attempts=45)

    def up(self) -> None:
        """Start infrastructure, prepare models/indexes, then start Synapse."""
        # Verify Docker and Compose before creating local state. A missing
        # prerequisite should not leave a new .env or secrets directory behind.
        self._select_compose()
        self.initialize()
        values = self.environment()
        self.compose("--profile", "infra", "up", "-d", "--remove-orphans")
        self.wait_http("Qdrant", f"http://127.0.0.1:{values.get('QDRANT_PORT', '6333')}/collections", attempts=30)
        self.wait_http("Wiki.js", f"http://127.0.0.1:{values.get('WIKIJS_PORT', '3000')}", attempts=45)
        ollama_url = values.get("OLLAMA_HOST_BASE_URL") or f"http://127.0.0.1:{values.get('OLLAMA_PORT', '11434')}"
        self.wait_http("Ollama", f"{ollama_url.rstrip('/')}/api/tags", attempts=60)
        self.pull_models(values)
        self.ensure_collection(values)
        self.start_service()
        cloud = values.get("OLLAMA_CLOUD_MODE", "").strip().casefold() in {"1", "true", "yes", "on"}
        mode = "Ollama Cloud relay" if cloud else "local Ollama"
        print(f"[OK] Synapse lab is running ({mode})")

    def configure(self) -> None:
        values = self.environment()
        token = values.get("WIKIJS_API_TOKEN", "")
        if not token or token.casefold() in {"placeholder", "changeme", "todo"} or token.startswith(("replace-", "replace_with_")):
            raise LabError("WIKIJS_API_TOKEN is missing or still a placeholder")
        port = values.get("WIKIJS_PORT", "3000")
        endpoint = f"http://127.0.0.1:{port}/graphql"
        payload = json.dumps({"query": "query { pages { list { id path title } } }"}).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        except urllib.error.HTTPError as exc:
            raise LabError(f"Wiki.js rejected the API check with HTTP {exc.code}") from exc
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise LabError(f"Wiki.js is unreachable at {endpoint}: {exc}") from exc
        if result.get("errors"):
            raise LabError("Wiki.js GraphQL API returned errors; ensure the API and token permissions are enabled")
        print("[OK] Wiki.js API and token are configured")

    def proof(self, suite: str = "simple") -> None:
        self.configure()
        from scripts.proof import runner

        previous = os.environ.get("SYNAPSE_ENV_FILE")
        os.environ["SYNAPSE_ENV_FILE"] = str(self.env_path)
        try:
            status = runner.main(["--suite", suite])
        finally:
            if previous is None:
                os.environ.pop("SYNAPSE_ENV_FILE", None)
            else:
                os.environ["SYNAPSE_ENV_FILE"] = previous
        if status:
            raise LabError(f"proof suite {suite} failed with exit code {status}")

    def real_proof(self) -> None:
        self.up()
        self.proof("real")

    def mocked_proof(self) -> None:
        """Run the disposable Compose proof and always remove its state."""
        artifact_dir = self.root / ".local-artifacts" / "ci-e2e"
        ci_env = artifact_dir / ".env"
        envfile.create_from_template(self.root / ".env.example", ci_env, force=True)
        envfile.write_values(
            ci_env,
            {
                "COMPOSE_PROJECT_NAME": "synapse-ci-e2e",
                "SYNAPSE_SERVICE_PORT": "6578",
                "QDRANT_PORT": "6633",
                "OLLAMA_INTERNAL_BASE_URL": "http://mock-ollama:11435",
                "OLLAMA_CHAT_BASE_URL": "http://mock-ollama:11435",
                "OLLAMA_HOST_BASE_URL": "",
                "OLLAMA_EMBED_MODEL": "mock-embed",
                "OLLAMA_FORMAT_MODEL": "mock-format",
                "OLLAMA_ANSWER_MODEL": "mock-answer",
                "QDRANT_COLLECTION": "synapse_ci_e2e",
                "SYNAPSE_MANAGE_QDRANT_COLLECTION": "false",
                "QDRANT_VECTOR_SIZE": "8",
                "RAG_SCORE_THRESHOLD": "0",
                "OBSIDIAN_VAULT_PATH": "examples/obsidian-vault",
            },
        )
        envfile.write_secret(ci_env, "SYNAPSE_WEBHOOK_AUTH_TOKEN", "ci-e2e-token")
        ci = Lab(root=self.root, env_path=ci_env, compose_path=self.root / "docker-compose.ci-e2e.yml", run=self._run, sleep=self._sleep)
        try:
            ci.compose("up", "-d", "--build", "qdrant", "mock-ollama", "synapse-service")
            ci.wait_http("Qdrant", "http://127.0.0.1:6633/collections", attempts=60)
            ci.wait_http("Synapse API", "http://127.0.0.1:6578/healthz", attempts=90)
            ci.ensure_collection()
            from scripts.proof import runner

            previous = os.environ.get("SYNAPSE_ENV_FILE")
            os.environ["SYNAPSE_ENV_FILE"] = str(ci_env)
            try:
                status = runner.main(["--suite", "ci"])
            finally:
                if previous is None:
                    os.environ.pop("SYNAPSE_ENV_FILE", None)
                else:
                    os.environ["SYNAPSE_ENV_FILE"] = previous
            if status:
                raise LabError(f"mocked proof failed with exit code {status}")
        finally:
            ci.compose("down", "-v", "--remove-orphans", check=False)

    def status(self) -> int:
        values = self.environment()
        self.compose("--profile", "full", "ps", check=False)
        endpoints = {
            "Synapse": f"http://127.0.0.1:{values.get('SYNAPSE_SERVICE_PORT', '15515')}/readyz",
            "Wiki.js": f"http://127.0.0.1:{values.get('WIKIJS_PORT', '3000')}",
            "Qdrant": f"http://127.0.0.1:{values.get('QDRANT_PORT', '6333')}/collections",
            "Ollama": f"http://127.0.0.1:{values.get('OLLAMA_PORT', '11434')}/api/tags",
        }
        failed = False
        for name, url in endpoints.items():
            status = self._http_status(url)
            ok = 200 <= status < 300
            failed = failed or not ok
            print(f"[{'OK' if ok else 'FAIL'}] {name}: {url} ({status or 'unreachable'})")
        return 1 if failed else 0

    def logs(self, extra: Sequence[str] = ()) -> None:
        self.compose("logs", "--tail=120", *extra)

    def down(self) -> None:
        self.compose("--profile", "infra", "--profile", "full", "down", "--remove-orphans")

    def remove(self, *, yes: bool = False) -> None:
        """Remove only the explicitly listed local-lab state after confirmation."""
        targets = [path for path in (self.env_path, self.root / ".local-artifacts") if path.exists()]
        print("Removal targets:")
        print("- Docker containers, network, and named volumes")
        for target in targets:
            print(f"- {target}")
        if not yes:
            if not sys.stdin.isatty():
                raise LabError("refusing destructive removal without --yes in a noninteractive session")
            if input("Type 'remove' to continue: ").strip() != "remove":
                raise LabError("removal cancelled")
        if self.env_path.exists():
            self.compose("--profile", "infra", "--profile", "full", "down", "-v", "--remove-orphans", check=False)
        self.env_path.unlink(missing_ok=True)
        artifacts = (self.root / ".local-artifacts").resolve()
        if artifacts.parent != self.root or artifacts.name != ".local-artifacts":
            raise LabError("refusing to remove an unexpected artifact path")
        if artifacts.exists():
            shutil.rmtree(artifacts)
        print("[OK] Local lab state removed")
