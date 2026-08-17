"""Check reviewed Docker image pins against upstream release metadata."""
from __future__ import annotations

import argparse
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ImageSource:
    name: str
    service: str
    env_name: str
    repo: str | None
    release_prefix: str | None
    tag_to_image_tag: Callable[[str], str]
    policy: str


def strip_v(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


IMAGE_SOURCES: tuple[ImageSource, ...] = (
    ImageSource("qdrant", "qdrant", "QDRANT_IMAGE", "qdrant/qdrant", "v", lambda tag: tag, "track latest stable patch"),
    ImageSource("ollama", "ollama", "OLLAMA_IMAGE", "ollama/ollama", "v", strip_v, "track latest stable patch"),
    ImageSource("synapse-service", "synapse-service", "SYNAPSE_SERVICE_IMAGE", None, None, lambda tag: tag, "locally built image; base Python set in Dockerfile"),
    ImageSource("wikijs", "wikijs", "WIKIJS_IMAGE", "requarks/wiki", "v2.", strip_v, "track latest stable 2.x patch"),
    ImageSource("wikijs-postgres", "wikijs-db", "WIKIJS_POSTGRES_IMAGE", None, None, lambda tag: tag, "track postgres 16 alpine minor/security stream"),
)

OFFLINE_LATEST = {
    "qdrant": "v1.19.0",
    "ollama": "v0.32.14",
    "wikijs": "v2.5.314",
}


def parse_image_ref(image: str) -> tuple[str, str, str | None]:
    reference, separator, digest = image.partition("@")
    if ":" not in reference.rsplit("/", 1)[-1]:
        raise ValueError(f"image is not tag-pinned: {image}")
    repo, tag = reference.rsplit(":", 1)
    if tag == "latest":
        raise ValueError(f"image must not use latest tag: {image}")
    if separator and (not digest.startswith("sha256:") or len(digest) != len("sha256:") + 64):
        raise ValueError(f"image digest must be a sha256 digest: {image}")
    return repo, tag, digest or None


def compose_image_default(compose: dict[str, Any], source: ImageSource) -> str:
    value = str(compose["services"][source.service]["image"])
    prefix = "${" + source.env_name + ":-"
    if not value.startswith(prefix) or not value.endswith("}"):
        raise ValueError(f"{source.service} image must use ${{{source.env_name}:-...}} default")
    return value[len(prefix) : -1]


def github_releases(repo: str) -> list[dict[str, Any]]:
    url = f"https://api.github.com/repos/{repo}/releases?per_page=30"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "synapse-image-update-check"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def latest_github_release_tag(source: ImageSource) -> str:
    if not source.repo or not source.release_prefix:
        raise ValueError(f"{source.name} does not use GitHub releases")
    for release in github_releases(source.repo):
        tag = str(release.get("tag_name") or "")
        if release.get("prerelease"):
            continue
        if tag.startswith(source.release_prefix):
            return tag
    raise RuntimeError(f"no stable release found for {source.repo} with prefix {source.release_prefix}")


def build_report(compose_file: Path, offline_fixture: bool = False) -> dict[str, Any]:
    compose = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    images = []
    outdated = []
    for source in IMAGE_SOURCES:
        pinned = compose_image_default(compose, source)
        repo, tag, digest = parse_image_ref(pinned)
        latest_release = None
        latest_image = pinned
        current = True
        if source.repo:
            latest_release = OFFLINE_LATEST[source.name] if offline_fixture else latest_github_release_tag(source)
            latest_tag = source.tag_to_image_tag(latest_release)
            latest_image = f"{repo}:{latest_tag}" + (f"@{digest}" if digest else "")
            current = tag == latest_tag and digest is not None
        item = {
            "name": source.name,
            "service": source.service,
            "env_name": source.env_name,
            "pinned": pinned,
            "digest": digest,
            "latest_release": latest_release,
            "expected_image": latest_image,
            "current": current,
            "policy": source.policy,
        }
        images.append(item)
        if not current:
            outdated.append(item)
    return {"compose_file": str(compose_file), "images": images, "outdated": outdated}


def render_text(report: dict[str, Any]) -> str:
    lines = ["Synapse image update check", ""]
    for image in report["images"]:
        status = "OK" if image["current"] else "OUTDATED"
        latest = image["expected_image"] if image["latest_release"] else "policy-only"
        lines.append(f"- {status} {image['name']}: pinned={image['pinned']} latest={latest} policy={image['policy']}")
    if report["outdated"]:
        lines.extend(["", "Update required: bump reviewed pins, run local proof, then update docs/VERSION_POLICY.md."])
    else:
        lines.extend(["", "All automatically checked pins match the reviewed release line."])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Synapse Docker image pins against upstream releases.")
    parser.add_argument("--compose-file", type=Path, default=ROOT / "docker-compose.e2e.yml")
    parser.add_argument("--offline-fixture", action="store_true", help="Use the reviewed fixture versions for deterministic tests.")
    parser.add_argument("--format", choices=("text", "json"), default="json")
    args = parser.parse_args(argv)

    report = build_report(args.compose_file, offline_fixture=args.offline_fixture)
    if args.format == "text":
        print(render_text(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["outdated"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
