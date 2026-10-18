"""Release planning tests; run directly with `uv run python tests/test_upstream.py`."""
from contextlib import redirect_stdout
from email.message import Message
import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import tomllib
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError

from m5stubgen.upstream import fetch_json, main, plan_release, set_version, version_key


def _release(tag: str = "2.5.3", **kwargs):
    return {"tag_name": tag, "draft": False, "prerelease": False, **kwargs}


def test_daily_schedule_publishes_new_stable_version() -> None:
    plan = plan_release("schedule", {}, _release(), ["0.1.0", "0.1.1"])
    assert plan.build and plan.publish and plan.automatic
    assert plan.ref == "2.5.3" and plan.version == "2.5.3"
    assert plan.outputs()["release_tag"] == "v2.5.3"
    assert plan.outputs()["publish"] == "true"


def test_version_order_is_numeric() -> None:
    old = version_key("2.9.9")
    new = version_key("v2.10.0")
    assert old is not None and new is not None and new > old
    plan = plan_release("schedule", {}, _release("2.10.0"), ["2.9.9"])
    assert plan.publish
    tagged = plan_release("schedule", {}, _release("v2.5.3"))
    assert tagged.ref == "v2.5.3" and tagged.version == "2.5.3"


def test_published_versions_and_post_releases_are_skipped() -> None:
    for published in (["2.5.3"], ["2.5.3.post1"], ["2.5.4"], ["3.0.0"]):
        plan = plan_release("schedule", {}, _release(), published)
        assert not plan.build and not plan.publish


def test_pypi_prereleases_do_not_suppress_new_stable_versions() -> None:
    plan = plan_release("schedule", {}, _release(), ["2.6.0rc1", "2.5.2", "invalid"])
    assert plan.publish


def test_upstream_drafts_and_prereleases_are_skipped() -> None:
    for release in (_release(draft=True), _release("2.6.0-rc1", prerelease=True)):
        plan = plan_release("schedule", {}, release)
        assert not plan.build and not plan.publish


def test_invalid_upstream_tags_fail_closed() -> None:
    for tag in ("master", "2.5.3-rc1", "2.5.3.post1", "2.5.3\npublish=true", "--bad", "02.5.3"):
        with TestCase().assertRaises(ValueError):
            plan_release("schedule", {}, _release(tag))


def test_manual_build_is_not_a_publication() -> None:
    for event in ({}, {"inputs": {"ref": "2.5.3", "publish": "false"}}):
        plan = plan_release("workflow_dispatch", event)
        assert plan.build and not plan.publish and not plan.automatic
        assert plan.version == "0.0.0"
    with TestCase().assertRaises(ValueError):
        plan_release("workflow_dispatch", {"inputs": {"publish": True}})


def test_manual_sync_dry_run_and_explicit_publication() -> None:
    for sync in (True, "true"):
        for publish in (False, "false", True, "true"):
            event = {"inputs": {"sync_upstream": sync, "publish": publish, "ref": "ignored"}}
            plan = plan_release("workflow_dispatch", event, _release())
            assert plan.build and plan.automatic and plan.ref == "2.5.3"
            assert plan.publish == (publish is True or publish == "true")


def test_publish_switch_applies_to_all_triggers() -> None:
    events = [
        ("schedule", {}),
        ("workflow_dispatch", {"inputs": {"sync_upstream": True, "publish": True}}),
        ("release", {"release": _release("v2.5.3.post1")}),
    ]
    for name, event in events:
        plan = plan_release(name, event, _release(), publish_enabled=False)
        assert plan.build and not plan.publish


def test_manual_release_supports_pinned_firmware_and_post_fix() -> None:
    event = {"release": _release("v2.5.3.post1", body="Fix stubs.\n<!-- m5stubgen-firmware: 2.5.3 -->")}
    plan = plan_release("release", event)
    assert plan.build and plan.publish and not plan.automatic
    assert plan.version == "2.5.3.post1" and plan.ref == "2.5.3"
    legacy = plan_release("release", {"release": _release("v0.1.2")})
    assert legacy.ref == "master" and legacy.version == "0.1.2"


def test_package_prereleases_are_not_published() -> None:
    plan = plan_release("release", {"release": _release("v2.5.4rc1", prerelease=True)})
    assert not plan.build and not plan.publish


def test_manual_refs_and_inputs_are_validated() -> None:
    for ref in ("--branch=evil", "x\npublish=true", "$(echo bad)", "x;exit 0"):
        with TestCase().assertRaises(ValueError):
            plan_release("workflow_dispatch", {"inputs": {"ref": ref}})
    with TestCase().assertRaises(ValueError):
        plan_release("workflow_dispatch", {"inputs": {"sync_upstream": "maybe"}})
    with TestCase().assertRaises(ValueError):
        plan_release("push", {})


def test_only_missing_pypi_project_is_treated_as_empty() -> None:
    for code in (404, 403, 429, 500):
        error = HTTPError("https://pypi.org/test", code, "test", Message(), None)
        with patch("m5stubgen.upstream.urlopen", side_effect=error):
            if code == 404:
                assert fetch_json("https://pypi.org/test", missing_ok=True) is None
            else:
                with TestCase().assertRaises(HTTPError):
                    fetch_json("https://pypi.org/test", missing_ok=True)
    with patch("m5stubgen.upstream.urlopen", side_effect=error):
        with TestCase().assertRaises(HTTPError):
            fetch_json("https://api.github.com/test")


def test_github_token_is_not_sent_to_pypi() -> None:
    for url in ("https://api.github.com/test", "https://pypi.org/test"):
        response = io.BytesIO(b"{}")
        with patch.dict(os.environ, {"GH_TOKEN": "test-token"}), \
             patch("m5stubgen.upstream.urlopen", return_value=response) as request:
            assert fetch_json(url) == {}
            headers = dict(request.call_args.args[0].header_items())
            assert ("Authorization" in headers) == url.startswith("https://api.github.com/")


def test_set_version_validates_and_preserves_project_metadata() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "pyproject.toml"
        original = '[project]\nname = "m5stack-stubs"\nversion = "0.0.0" # comment\n'
        for version in ("2.5.3", "2.5.3.post1"):
            path.write_text(original, encoding="utf-8")
            set_version(path, version)
            assert tomllib.loads(path.read_text())["project"]["version"] == version
            assert "# comment" in path.read_text()
        for version in ("v2.5.3", "2.5.3\nx=true", "invalid", "2.5.3rc1"):
            with TestCase().assertRaises(ValueError):
                set_version(path, version)
        path.write_text(original.replace('"m5stack-stubs"', '"other"'), encoding="utf-8")
        with TestCase().assertRaises(ValueError):
            set_version(path, "2.5.3")


def test_cli_writes_safe_outputs_and_summary() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        event = root / "event.json"
        event.write_text(json.dumps({"inputs": {"sync_upstream": True}}), encoding="utf-8")
        output = root / "output"
        summary = root / "summary"
        env = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_EVENT_PATH": str(event),
               "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)}
        with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["upstream", "plan"]), \
             patch("m5stubgen.upstream.fetch_json", side_effect=[_release(), {"releases": {"0.1.1": []}}]), \
             redirect_stdout(io.StringIO()):
            main()
        assert "ref=2.5.3\n" in output.read_text()
        assert "publish=false\n" in output.read_text()
        assert "Package: `2.5.3`" in summary.read_text()


def test_cli_network_failure_does_not_emit_a_publish_plan() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        event = root / "event.json"
        event.write_text("{}", encoding="utf-8")
        output = root / "output"
        env = {"GITHUB_EVENT_NAME": "schedule", "GITHUB_EVENT_PATH": str(event), "GITHUB_OUTPUT": str(output)}
        with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["upstream", "plan"]), \
             patch("m5stubgen.upstream.fetch_json", side_effect=OSError("offline")), \
             TestCase().assertRaises(OSError):
            main()
        assert not output.exists()


def test_malformed_pypi_data_does_not_emit_a_publish_plan() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        event = root / "event.json"
        event.write_text("{}", encoding="utf-8")
        output = root / "output"
        env = {"GITHUB_EVENT_NAME": "schedule", "GITHUB_EVENT_PATH": str(event), "GITHUB_OUTPUT": str(output)}
        for data in ({}, {"releases": []}, {"releases": None}):
            with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["upstream", "plan"]), \
                 patch("m5stubgen.upstream.fetch_json", side_effect=[_release(), data]), \
                 TestCase().assertRaises(ValueError):
                main()
            assert not output.exists()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all release planning tests passed")
