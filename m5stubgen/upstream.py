"""Plan releases from stable upstream firmware tags for GitHub Actions."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import time
import tomllib
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


UPSTREAM = "m5stack/uiflow-micropython"
PYPI = "https://pypi.org/pypi/m5stack-stubs/json"
_VERSION = re.compile(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.post(0|[1-9]\d*))?")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_FIRMWARE_MARKER = re.compile(r"<!-- m5stubgen-firmware: ([A-Za-z0-9][A-Za-z0-9._/-]*) -->")


def version_key(value: str) -> tuple[int, int, int, int] | None:
    match = _VERSION.fullmatch(value)
    if not match:
        return None
    major, minor, patch, post = match.groups()
    return int(major), int(minor), int(patch), int(post) if post else -1


def _boolean(value: Any) -> bool:
    if value is True or value == "true":
        return True
    if value is None or value is False or value in ("false", ""):
        return False
    raise ValueError("expected a boolean workflow input")


def wants_sync(event_name: str, event: dict[str, Any]) -> bool:
    return event_name == "schedule" or (
        event_name == "workflow_dispatch"
        and _boolean(event.get("inputs", {}).get("sync_upstream"))
    )


@dataclass(frozen=True)
class ReleasePlan:
    build: bool
    publish: bool
    automatic: bool
    ref: str
    version: str
    reason: str
    verify: bool = False
    record: bool = False

    def outputs(self) -> dict[str, str]:
        values = {
            name: str(value).lower() if isinstance(value, bool) else value
            for name, value in asdict(self).items()
        }
        values["release_tag"] = "v" + self.version
        return values


def plan_release(
    event_name: str,
    event: dict[str, Any],
    upstream: dict[str, Any] | None = None,
    published_versions: Iterable[str] = (),
    publish_enabled: bool = True,
) -> ReleasePlan:
    inputs = event.get("inputs", {})
    if wants_sync(event_name, event):
        if upstream is None:
            raise ValueError("upstream release metadata is required")
        if upstream.get("draft") or upstream.get("prerelease"):
            return ReleasePlan(False, False, True, "master", "0.0.0", "Not a stable upstream release")
        tag = upstream["tag_name"]
        key = version_key(tag)
        if not key or key[3] != -1:
            raise ValueError("unsupported firmware tag: %r" % tag)
        version = tag.removeprefix("v")
        publish = publish_enabled and (
            event_name == "schedule" or _boolean(inputs.get("publish"))
        )
        published_versions = list(published_versions)
        existing = [k for value in published_versions if (k := version_key(value)) is not None]
        if any(k[:3] >= key[:3] for k in existing):
            recover = publish and version in published_versions and max(existing) == key
            return ReleasePlan(False, False, True, tag, version, "Already published or superseded",
                               verify=recover, record=recover)
        return ReleasePlan(True, publish, True, tag, version, "New stable upstream release",
                           verify=publish, record=publish)

    if event_name == "release":
        release = event["release"]
        tag = release["tag_name"]
        if release.get("draft") or release.get("prerelease"):
            return ReleasePlan(False, False, False, "master", "0.0.0", "Not a stable package release")
        if version_key(tag) is None:
            raise ValueError("unsupported package version: %r" % tag)
        marker = _FIRMWARE_MARKER.search(release.get("body") or "")
        ref = marker.group(1) if marker else "master"
        return ReleasePlan(True, publish_enabled, False, ref, tag.removeprefix("v"), "Package release",
                           verify=publish_enabled)

    if event_name != "workflow_dispatch":
        raise ValueError("unsupported workflow event: %s" % event_name)
    if _boolean(inputs.get("publish")):
        raise ValueError("manual publishing requires sync_upstream=true")
    ref = inputs.get("ref") or "master"
    if not _REF.fullmatch(ref):
        raise ValueError("invalid firmware ref: %r" % ref)
    return ReleasePlan(True, False, False, ref, "0.0.0", "Manual build only")


def fetch_json(url: str, missing_ok: bool = False) -> dict[str, Any] | None:
    headers = {"Accept": "application/json", "User-Agent": "m5stubgen-upstream-sync"}
    token = os.environ.get("GH_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = "Bearer " + token
    try:
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            data = json.load(response)
            if not isinstance(data, dict):
                raise ValueError("expected an API JSON object")
            return data
    except HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        raise


def set_version(path: Path, version: str) -> None:
    if version.startswith("v") or version_key(version) is None:
        raise ValueError("invalid package version: %r" % version)
    text = path.read_text(encoding="utf-8")
    if tomllib.loads(text)["project"]["name"] != "m5stack-stubs":
        raise ValueError("refusing to change a different project's version")
    text, count = re.subn(
        r'(?m)^version\s*=\s*"[^"]*"', 'version = "%s"' % version, text, count=1,
    )
    if count != 1 or tomllib.loads(text)["project"]["version"] != version:
        raise ValueError("could not set package version")
    path.write_text(text, encoding="utf-8")


def install_published(version: str, target: Path) -> None:
    """Wait up to five minutes for PyPI's package index to expose a new upload."""
    if version.startswith("v") or version_key(version) is None:
        raise ValueError("invalid package version: %r" % version)
    command = [
        "uv", "pip", "install", "--target", str(target), "--no-deps", "--no-cache",
        "--index-url", "https://pypi.org/simple", "m5stack-stubs==" + version,
    ]
    for attempt in range(11):
        try:
            subprocess.run(command, check=True)
            return
        except subprocess.CalledProcessError:
            if attempt == 10:
                raise
            print("PyPI install not ready; retrying in 30 seconds", flush=True)
            time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch"))
    plan.add_argument("--event-file", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))
    version = sub.add_parser("set-version")
    version.add_argument("version")
    version.add_argument("--path", type=Path, default=Path("stubpkg/pyproject.toml"))
    install = sub.add_parser("install-published")
    install.add_argument("version")
    install.add_argument("--target", type=Path, default=Path("published"))
    args = parser.parse_args()
    if args.command == "set-version":
        set_version(args.path, args.version)
        return
    if args.command == "install-published":
        install_published(args.version, args.target)
        return
    if args.event_file is None:
        parser.error("plan requires --event-file or GITHUB_EVENT_PATH")
    event = json.loads(args.event_file.read_text(encoding="utf-8"))
    upstream = None
    published: Iterable[str] = ()
    if wants_sync(args.event_name, event):
        upstream = fetch_json("https://api.github.com/repos/%s/releases/latest" % UPSTREAM)
        pypi = fetch_json(PYPI, missing_ok=True)
        if pypi is not None:
            if not isinstance(pypi.get("releases"), dict):
                raise ValueError("invalid PyPI releases response")
            published = pypi["releases"]
    result = plan_release(
        args.event_name, event, upstream, published,
        publish_enabled=os.environ.get("PUBLISH_TO_PYPI", "true") == "true",
    )
    outputs = result.outputs()
    print(json.dumps(outputs, indent=2))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as fh:
            for name, value in outputs.items():
                fh.write("%s=%s\n" % (name, value))
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Release plan\n\n%s\n\nFirmware: `%s`\n\nPackage: `%s`\n\nPublish: `%s`\n"
                     % (result.reason, result.ref, result.version, outputs["publish"]))


if __name__ == "__main__":
    main()
