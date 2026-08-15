from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "analyze-project-claims"
MODULE_PATH = SKILL_ROOT / "scripts" / "update_policy.py"
SPEC = importlib.util.spec_from_file_location("analyze_project_claims_update_policy", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
update_policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = update_policy
SPEC.loader.exec_module(update_policy)


TREE_A = "a" * 40
TREE_B = "b" * 40


class FakeNative:
    def __init__(self, installs: list[dict[str, object]]) -> None:
        self.installs = installs
        self.list_calls = 0
        self.update_calls: list[bool] = []
        self.result = update_policy.NativeResult(0, "", "")
        self.on_update = None

    def list_installs(self) -> list[dict[str, object]]:
        self.list_calls += 1
        return [dict(item) for item in self.installs]

    def update(self, *, dry_run: bool):
        self.update_calls.append(dry_run)
        if self.on_update is not None:
            self.on_update(dry_run)
        return self.result


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def make_skill(base: Path, *, version: str = "0.4.0", tree: str = TREE_A) -> Path:
    root = base / "analyze-project-claims"
    (root / "references").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: analyze-project-claims\ndescription: Test fixture.\n---\n\n# Fixture\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "scripts" / "fixture.txt").write_text("release payload\n", encoding="utf-8", newline="\n")
    write_json(
        root / "references" / "package-version.json",
        {"schema_version": 1, "skill_name": "analyze-project-claims", "version": version},
    )
    update_policy.write_package_manifest(root)
    inject_metadata(root, repository="owner/repository", tree=tree)
    return root


def inject_metadata(root: Path, *, repository: str, tree: str) -> None:
    path = root / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    if "metadata:\n" in text:
        text = re.sub(r"(?m)^(\s+github-repo:\s*).*$", rf"\g<1>{repository}", text)
        text = re.sub(r"(?m)^(\s+github-tree-sha:\s*).*$", rf"\g<1>{tree}", text)
    else:
        text = text.replace(
            "---\n",
            "---\nmetadata:\n"
            "  github-path: skills/analyze-project-claims\n"
            f"  github-repo: {repository}\n"
            "  github-ref: v0.4.0\n"
            f"  github-tree-sha: {tree}\n",
            1,
        )
    path.write_text(text, encoding="utf-8", newline="\n")


def install_for(root: Path, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "skillName": "analyze-project-claims",
        "sourceURL": "https://github.com/owner/repository",
        "scope": "user",
        "version": "v0.4.0",
        "pinned": False,
        "path": str(root),
    }
    value.update(overrides)
    return value


def coordinator(root: Path, state_dir: Path, native: FakeNative, clock: list[int]):
    return update_policy.UpdateCoordinator(
        root,
        update_policy.PolicyStore(state_dir),
        native,
        now=lambda: clock[0],
    )


class UpdatePolicyTests(unittest.TestCase):
    def test_manifest_normalizes_injected_metadata_and_detects_local_edits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            root = make_skill(Path(temporary))
            digest = update_policy.verify_package_manifest(root)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            (root / "scripts" / "fixture.txt").write_text("local edit\n", encoding="utf-8")
            with self.assertRaises(update_policy.PolicyError) as raised:
                update_policy.verify_package_manifest(root)
            self.assertEqual(raised.exception.code, "PACKAGE_MODIFIED")

    def test_manifest_normalizes_current_gh_frontmatter_rewrite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            root = make_skill(Path(temporary))
            (root / "SKILL.md").write_text(
                "---\n"
                "description: Test fixture.\n"
                "metadata:\n"
                "    github-path: skills/analyze-project-claims\n"
                "    github-ref: refs/tags/v0.4.0\n"
                "    github-repo: https://github.com/owner/repository\n"
                f"    github-tree-sha: {TREE_A}\n"
                "name: analyze-project-claims\n"
                "---\n"
                "# Fixture\n",
                encoding="utf-8",
                newline="\n",
            )
            self.assertRegex(update_policy.verify_package_manifest(root), r"^[0-9a-f]{64}$")

    def test_first_substantive_use_prompts_once_without_update_action(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            native = FakeNative([install_for(root)])
            subject = coordinator(root, base / "state", native, [1000])
            first = subject.maintain()
            second = subject.maintain()
            self.assertEqual(first["status"], "CONSENT_REQUIRED")
            self.assertTrue(first["emit"])
            self.assertEqual(second["status"], "UNCONFIGURED")
            self.assertEqual(native.list_calls, 1)  # Local eligibility probe; no update/network action.
            self.assertEqual(native.update_calls, [])

    def test_update_consent_discloses_success_lease_and_failure_retry(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            subject = coordinator(root, base / "state", FakeNative([install_for(root)]), [1000])
            message = subject.prompt()["message"].lower()
            self.assertIn("successful check", message)
            self.assertIn("24 hours", message)
            self.assertIn("transient failure", message)
            self.assertIn("one hour", message)

    def test_untracked_or_host_managed_copy_does_not_prompt_or_write_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            native = FakeNative([])
            state_dir = base / "state"
            subject = coordinator(root, state_dir, native, [1000])
            result = subject.maintain()
            self.assertEqual(result["status"], "HOST_MANAGED_OR_UNTRACKED")
            self.assertFalse((state_dir / "update-policy.json").exists())
            self.assertEqual(native.update_calls, [])

    def test_exact_path_and_version_are_required_before_enablement(self) -> None:
        cases = (
            ({"path": "somewhere-else"}, "INSTALL_PATH_MISMATCH"),
            ({"version": "v9.9.9"}, "VERSION_MISMATCH"),
        )
        for overrides, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
                base = Path(temporary)
                root = make_skill(base)
                native = FakeNative([install_for(root, **overrides)])
                subject = coordinator(root, base / "state", native, [1000])
                with self.assertRaises(update_policy.PolicyError) as raised:
                    subject.enable("auto")
                self.assertEqual(raised.exception.code, expected)
                self.assertEqual(native.update_calls, [])

    def test_auto_mode_checks_once_per_24_hours(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            clock = [1000]
            native = FakeNative([install_for(root)])
            subject = coordinator(root, base / "state", native, clock)
            self.assertEqual(subject.enable("auto")["status"], "ENABLED_AUTO")
            result = subject.maintain()
            self.assertEqual(result["status"], "UP_TO_DATE")
            self.assertEqual(native.update_calls, [False])
            calls = native.list_calls
            clock[0] += update_policy.SUCCESS_LEASE_SECONDS - 1
            self.assertEqual(subject.maintain()["status"], "NOT_DUE")
            self.assertEqual(native.list_calls, calls)

    def test_verified_update_is_active_next_use(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            native = FakeNative([install_for(root)])
            subject = coordinator(root, base / "state", native, [1000])
            subject.enable("auto")

            def apply_release(dry_run: bool) -> None:
                self.assertFalse(dry_run)
                write_json(
                    root / "references" / "package-version.json",
                    {"schema_version": 1, "skill_name": "analyze-project-claims", "version": "0.5.0"},
                )
                skill_path = root / "SKILL.md"
                skill_path.write_text(
                    skill_path.read_text(encoding="utf-8").replace(TREE_A, TREE_B),
                    encoding="utf-8",
                    newline="\n",
                )
                write_json(root / "references" / "package-manifest.json", update_policy.build_package_manifest(root))
                native.installs[0]["version"] = "v0.5.0"

            native.on_update = apply_release
            result = subject.maintain()
            self.assertEqual(result["status"], "UPDATED_NEXT_USE")
            self.assertEqual(result["current_version"], "0.4.0")
            self.assertEqual(result["installed_version"], "0.5.0")
            self.assertIn("next invocation", result["message"])

    def test_pinned_and_project_installs_degrade_to_notify(self) -> None:
        for field, value, reason in (("pinned", True, "PINNED"), ("scope", "project", "PROJECT_SCOPE")):
            with self.subTest(field=field), tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
                base = Path(temporary)
                root = make_skill(base)
                native = FakeNative([install_for(root, **{field: value})])
                subject = coordinator(root, base / "state", native, [1000])
                result = subject.enable("auto")
                self.assertEqual(result["status"], "AUTO_DEGRADED_TO_NOTIFY")
                self.assertIn(reason, result["message"])
                self.assertEqual(subject.status()["mode"], "notify")
                self.assertEqual(native.update_calls, [])

    def test_install_that_becomes_pinned_switches_to_notify(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            native = FakeNative([install_for(root)])
            subject = coordinator(root, base / "state", native, [1000])
            subject.enable("auto")
            native.installs[0]["pinned"] = True
            result = subject.maintain()
            self.assertEqual(result["status"], "PINNED")
            self.assertEqual(result["mode"], "notify")
            self.assertEqual(native.update_calls, [])

    def test_duplicate_install_refuses_update_by_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            native = FakeNative([install_for(root), install_for(root)])
            subject = coordinator(root, base / "state", native, [1000])
            with self.assertRaises(update_policy.PolicyError) as raised:
                subject.enable("auto")
            self.assertEqual(raised.exception.code, "AMBIGUOUS_INSTALL")
            self.assertEqual(subject.status()["mode"], "unconfigured")

    def test_source_change_suspends_auto(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            native = FakeNative([install_for(root)])
            subject = coordinator(root, base / "state", native, [1000])
            subject.enable("auto")
            inject_metadata(root, repository="other/repository", tree=TREE_A)
            native.installs[0]["sourceURL"] = "https://github.com/other/repository"
            result = subject.maintain()
            self.assertEqual(result["status"], "SOURCE_OR_INSTALL_CHANGED")
            state = update_policy.PolicyStore(base / "state").load()
            self.assertTrue(state["suspended"])
            self.assertEqual(native.update_calls, [])

    def test_transient_native_failure_preserves_verified_package(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            clock = [1000]
            native = FakeNative([install_for(root)])
            native.result = update_policy.NativeResult(1, "", "offline")
            subject = coordinator(root, base / "state", native, clock)
            subject.enable("auto")
            result = subject.maintain()
            state = update_policy.PolicyStore(base / "state").load()
            self.assertEqual(result["status"], "TRANSIENT_FAILURE")
            self.assertFalse(state["suspended"])
            self.assertEqual(state["next_check_at"], 1000 + update_policy.TRANSIENT_BACKOFF_SECONDS)
            self.assertEqual(update_policy.verify_package_manifest(root), update_policy.verify_package_manifest(root))

    def test_failed_or_zero_exit_with_bad_postcondition_suspends_auto(self) -> None:
        for returncode in (0, 1):
            with self.subTest(returncode=returncode), tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
                base = Path(temporary)
                root = make_skill(base)
                native = FakeNative([install_for(root)])
                native.result = update_policy.NativeResult(returncode, "", "interrupted")
                native.on_update = lambda _dry_run: (root / "scripts" / "fixture.txt").write_text(
                    "partial replacement\n", encoding="utf-8"
                )
                subject = coordinator(root, base / "state", native, [1000])
                subject.enable("auto")
                result = subject.maintain()
                self.assertEqual(result["status"], "INVALID_POSTCONDITION")
                self.assertTrue(update_policy.PolicyStore(base / "state").load()["suspended"])

    def test_preexisting_local_edit_suspends_without_replacement(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            native = FakeNative([install_for(root)])
            subject = coordinator(root, base / "state", native, [1000])
            subject.enable("auto")
            (root / "scripts" / "fixture.txt").write_text("local edit\n", encoding="utf-8")
            result = subject.maintain()
            self.assertEqual(result["status"], "PACKAGE_MODIFIED")
            self.assertTrue(update_policy.PolicyStore(base / "state").load()["suspended"])
            self.assertEqual(native.update_calls, [])

    def test_check_now_is_read_only_without_auto_consent_and_does_not_change_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            native = FakeNative([install_for(root)])
            native.result = update_policy.NativeResult(0, "an update is available", "")
            subject = coordinator(root, base / "state", native, [1000])
            result = subject.check_now()
            self.assertEqual(result["status"], "NOTIFY_CHECKED")
            self.assertEqual(result["mode"], "unconfigured")
            self.assertEqual(update_policy.PolicyStore(base / "state").load()["mode"], "unconfigured")
            self.assertEqual(native.update_calls, [True])

    def test_check_now_preserves_explicit_non_auto_modes(self) -> None:
        for mode in ("notify", "off"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
                base = Path(temporary)
                root = make_skill(base)
                native = FakeNative([install_for(root)])
                native.result = update_policy.NativeResult(0, "an update is available", "")
                subject = coordinator(root, base / "state", native, [1000])
                if mode == "notify":
                    subject.enable("notify")
                else:
                    subject.disable()
                native.update_calls.clear()

                result = subject.check_now()

                self.assertEqual(result["status"], "NOTIFY_CHECKED")
                self.assertEqual(result["mode"], mode)
                self.assertEqual(update_policy.PolicyStore(base / "state").load()["mode"], mode)
                self.assertEqual(native.update_calls, [True])

    def test_check_now_honors_auto_consent_and_bypasses_the_active_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            native = FakeNative([install_for(root)])
            subject = coordinator(root, base / "state", native, [1000])
            subject.enable("auto")
            self.assertEqual(subject.maintain()["status"], "UP_TO_DATE")
            native.update_calls.clear()

            result = subject.check_now()

            self.assertEqual(result["status"], "UP_TO_DATE")
            self.assertEqual(result["mode"], "auto")
            self.assertEqual(native.update_calls, [False])

    def test_check_now_rechecks_revoked_auto_consent_under_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            native = FakeNative([install_for(root)])
            native.result = update_policy.NativeResult(0, "an update is available", "")
            subject = coordinator(root, base / "state", native, [1000])
            auto_state = update_policy.default_state()
            auto_state.update({"mode": "auto", "prompted": True})
            off_state = dict(auto_state)
            off_state["mode"] = "off"

            with mock.patch.object(subject.store, "load", side_effect=[auto_state, off_state]):
                result = subject.check_now()

            self.assertEqual(result["status"], "NOTIFY_CHECKED")
            self.assertEqual(result["mode"], "off")
            self.assertEqual(native.update_calls, [True])

    def test_maintain_rechecks_inactive_auto_states_under_lock(self) -> None:
        cases = (
            ("unconfigured", False, "UNCONFIGURED"),
            ("off", False, "DISABLED"),
            ("auto", True, "AUTO_SUSPENDED"),
        )
        for locked_mode, suspended, expected_status in cases:
            with self.subTest(status=expected_status), tempfile.TemporaryDirectory(
                prefix="update-policy-"
            ) as temporary:
                base = Path(temporary)
                root = make_skill(base)
                native = FakeNative([install_for(root)])
                subject = coordinator(root, base / "state", native, [1000])
                auto_state = update_policy.default_state()
                auto_state.update({"mode": "auto", "prompted": True})
                locked_state = dict(auto_state)
                locked_state.update({"mode": locked_mode, "suspended": suspended})

                with mock.patch.object(subject.store, "load", side_effect=[auto_state, locked_state]):
                    result = subject.maintain()

                self.assertEqual(result["status"], expected_status)
                self.assertEqual(native.update_calls, [])

    def test_check_now_uses_newly_granted_auto_consent_under_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            native = FakeNative([install_for(root)])
            subject = coordinator(root, base / "state", native, [1000])
            off_state = update_policy.default_state()
            off_state.update(
                {
                    "mode": "off",
                    "prompted": True,
                    "installation_id": update_policy.installation_id(
                        "https://github.com/owner/repository", root
                    ),
                    "source_fingerprint": update_policy.source_fingerprint(
                        "https://github.com/owner/repository"
                    ),
                }
            )
            auto_state = dict(off_state)
            auto_state["mode"] = "auto"

            with mock.patch.object(subject.store, "load", side_effect=[off_state, auto_state]):
                result = subject.check_now()

            self.assertEqual(result["status"], "UP_TO_DATE")
            self.assertEqual(result["mode"], "auto")
            self.assertEqual(native.update_calls, [False])

    def test_check_now_cli_uses_the_policy_aware_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            result = update_policy._result(
                "NOTIFY_CHECKED",
                update_policy.default_state(),
                "Checked.",
            )
            with mock.patch.object(
                update_policy.UpdateCoordinator,
                "check_now",
                return_value=result,
            ) as check_now, mock.patch("builtins.print"):
                exit_code = update_policy.main(
                    [
                        "--skill-root",
                        str(root),
                        "--state-dir",
                        str(base / "state"),
                        "--format",
                        "json",
                        "check-now",
                    ]
                )

            self.assertEqual(exit_code, 0)
            check_now.assert_called_once_with()

    def test_state_schema_is_exact_and_unknown_fields_fail_closed(self) -> None:
        schema = json.loads((SKILL_ROOT / "references" / "update-policy.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), update_policy.STATE_KEYS)
        value = update_policy.default_state()
        value["unexpected"] = True
        with self.assertRaises(update_policy.PolicyError) as raised:
            update_policy.validate_state(value)
        self.assertEqual(raised.exception.code, "UPDATE_POLICY_STATE_INVALID")

    def test_native_client_uses_argument_arrays_without_force_or_unpin(self) -> None:
        client = update_policy.NativeClient(("gh",))
        listing = json.dumps([{"skillName": "x"}])
        with mock.patch.object(client, "run", return_value=update_policy.NativeResult(0, listing, "")) as run:
            client.list_installs()
            run.assert_called_once_with(
                ["skill", "list", "--json", "skillName,sourceURL,scope,version,pinned,path"]
            )
        with mock.patch.object(client, "run", return_value=update_policy.NativeResult(0, "", "")) as run:
            client.update(dry_run=True)
            run.assert_called_once_with(["skill", "update", "analyze-project-claims", "--dry-run"])
        with mock.patch.object(client, "run", return_value=update_policy.NativeResult(0, "", "")) as run:
            client.update(dry_run=False)
            arguments = run.call_args.args[0]
            self.assertEqual(arguments, ["skill", "update", "analyze-project-claims", "--all"])
            self.assertNotIn("--force", arguments)
            self.assertNotIn("--unpin", arguments)
            self.assertNotIn("--dir", arguments)

    def test_native_output_is_bounded(self) -> None:
        handle = io.BytesIO(b"x" * (update_policy.OUTPUT_LIMIT_BYTES + 10))
        result = update_policy._bounded_text(handle)
        self.assertLessEqual(len(result.encode("utf-8")), update_policy.OUTPUT_LIMIT_BYTES + 32)
        self.assertTrue(result.endswith("[output truncated]"))

    def test_single_flight_lock_reports_contention(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            base = Path(temporary)
            root = make_skill(base)
            store = update_policy.PolicyStore(base / "state")
            subject = update_policy.UpdateCoordinator(root, store, FakeNative([install_for(root)]), now=lambda: 1000)
            with store.try_lock() as acquired:
                self.assertTrue(acquired)
                self.assertEqual(subject.prompt()["status"], "LOCKED")

    def test_repository_package_version_and_manifest_are_consistent(self) -> None:
        package = json.loads((SKILL_ROOT / "references" / "package-version.json").read_text(encoding="utf-8"))
        self.assertEqual(package["version"], (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        self.assertRegex(update_policy.verify_package_manifest(SKILL_ROOT), r"^[0-9a-f]{64}$")

    def test_repository_package_text_uses_canonical_lf_bytes(self) -> None:
        manifest = json.loads((SKILL_ROOT / "references" / "package-manifest.json").read_text(encoding="utf-8"))
        text_suffixes = {".json", ".md", ".py", ".txt", ".yaml", ".yml"}
        for entry in manifest["files"]:
            relative = Path(entry["path"])
            if relative.suffix.lower() in text_suffixes:
                self.assertNotIn(b"\r", (SKILL_ROOT / relative).read_bytes(), entry["path"])

    @unittest.skipIf(os.name == "nt", "Creating symlinks is privilege-dependent on Windows.")
    def test_manifest_rejects_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-policy-") as temporary:
            root = make_skill(Path(temporary))
            (root / "linked").symlink_to(root / "scripts" / "fixture.txt")
            with self.assertRaises(update_policy.PolicyError) as raised:
                update_policy.verify_package_manifest(root)
            self.assertEqual(raised.exception.code, "PACKAGE_MODIFIED")


if __name__ == "__main__":
    unittest.main()
