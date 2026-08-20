import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "analyze-project-claims" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _internal.skill_quality import contract  # noqa: E402
from _internal.skill_quality.contribution import (  # noqa: E402
    ContributionError,
    approval_id,
    content_fingerprint,
    github_body,
    github_title,
    prepare_contribution,
    submit_contribution,
    validate_draft,
)
from _internal.skill_quality.store import QualityStore  # noqa: E402
import skill_quality_loop  # noqa: E402
from maintainer_service.intake import prepare_task  # noqa: E402


class FakeGitHub:
    def __init__(self, visibility: str = "PUBLIC") -> None:
        self.visibility = visibility
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        if command[1:3] == ["repo", "view"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"visibility": self.visibility}), "")
        if command[1:3] == ["issue", "create"]:
            destination = command[command.index("--repo") + 1]
            return subprocess.CompletedProcess(
                command,
                0,
                f"https://github.com/{destination}/issues/123\n",
                "",
            )
        return subprocess.CompletedProcess(command, 1, "", "unexpected")


class QualityContributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="quality-contribution-")
        self.state_dir = Path(self.temp.name)
        store = QualityStore(self.state_dir)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        receipt = contract.create_receipt(
            owner="Ian-Tseng",
            repository="example-producer",
            skill="example-producer",
            version="1.2.3",
            package_digest_sha256="c" * 64,
            outcome="completed_with_limitations",
            quality_signal="documentation_mismatch",
            requested_action="analyze_quality",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        self.proposal = store.consume(receipt, analyzer_version="1.0.0")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_prepare_is_enum_only_and_local(self) -> None:
        result = prepare_contribution(self.proposal, self.state_dir)
        draft = result["draft"]
        serialized = json.dumps(draft)
        self.assertNotIn("C:/private/project", serialized)
        self.assertNotIn("prompt", serialized.lower())
        self.assertEqual(result["outbound"], "NONE")
        self.assertEqual(result["destination"], "Ian-Tseng/example-producer")
        self.assertEqual(draft["destination"], "Ian-Tseng/example-producer")
        self.assertTrue(Path(result["draft_path"]).is_file())
        self.assertEqual(github_title(draft), "[skill-quality] documentation_mismatch from example-producer")

    def test_public_submission_requires_two_exact_approvals(self) -> None:
        result = prepare_contribution(self.proposal, self.state_dir)
        fake = FakeGitHub("PUBLIC")
        with self.assertRaisesRegex(ContributionError, "PUBLIC_ISSUE_APPROVAL_REQUIRED"):
            submit_contribution(
                Path(result["draft_path"]),
                approve=result["approval_id"],
                approved=True,
                allow_public_issue=False,
                runner=fake,
            )
        submitted = submit_contribution(
            Path(result["draft_path"]),
            approve=result["approval_id"],
            approved=True,
            allow_public_issue=True,
            runner=fake,
        )
        self.assertEqual(submitted["status"], "SUBMITTED")
        self.assertEqual(fake.commands[0][3], "Ian-Tseng/example-producer")
        issue_command = next(command for command in fake.commands if command[1:3] == ["issue", "create"])
        self.assertEqual(issue_command[issue_command.index("--repo") + 1], "Ian-Tseng/example-producer")
        self.assertEqual(submitted["issue_url"].rsplit("/", 1)[-1], "123")
        replay = submit_contribution(
            Path(result["draft_path"]),
            approve=result["approval_id"],
            approved=True,
            allow_public_issue=True,
            runner=fake,
        )
        self.assertFalse(replay["newly_created"])
        self.assertEqual(
            sum(command[1:3] == ["issue", "create"] for command in fake.commands),
            1,
        )

    def test_unknown_remote_outcome_blocks_replay(self) -> None:
        result = prepare_contribution(self.proposal, self.state_dir)

        class UnexpectedGitHub(FakeGitHub):
            def __call__(self, command, **kwargs):
                response = super().__call__(command, **kwargs)
                if command[1:3] == ["issue", "create"]:
                    return subprocess.CompletedProcess(command, 0, "unexpected\n", "")
                return response

        fake = UnexpectedGitHub()
        with self.assertRaisesRegex(ContributionError, "CONTRIBUTION_OUTCOME_UNKNOWN"):
            submit_contribution(
                Path(result["draft_path"]),
                approve=result["approval_id"],
                approved=True,
                allow_public_issue=True,
                runner=fake,
            )
        command_count = len(fake.commands)
        with self.assertRaisesRegex(ContributionError, "CONTRIBUTION_OUTCOME_UNKNOWN"):
            submit_contribution(
                Path(result["draft_path"]),
                approve=result["approval_id"],
                approved=True,
                allow_public_issue=True,
                runner=fake,
            )
        self.assertEqual(len(fake.commands), command_count)

    def test_submission_persistence_failure_is_unknown_and_not_retryable(self) -> None:
        result = prepare_contribution(self.proposal, self.state_dir)
        fake = FakeGitHub()
        with patch(
            "_internal.skill_quality.contribution._finish_submission",
            side_effect=OSError("simulated state write failure"),
        ):
            with self.assertRaisesRegex(ContributionError, "CONTRIBUTION_OUTCOME_UNKNOWN"):
                submit_contribution(
                    Path(result["draft_path"]),
                    approve=result["approval_id"],
                    approved=True,
                    allow_public_issue=True,
                    runner=fake,
                )
        self.assertEqual(
            sum(command[1:3] == ["issue", "create"] for command in fake.commands),
            1,
        )
        command_count = len(fake.commands)
        with self.assertRaisesRegex(ContributionError, "CONTRIBUTION_OUTCOME_UNKNOWN"):
            submit_contribution(
                Path(result["draft_path"]),
                approve=result["approval_id"],
                approved=True,
                allow_public_issue=True,
                runner=fake,
            )
        self.assertEqual(len(fake.commands), command_count)

    def test_confirmed_submission_survives_secondary_accounting_failure(self) -> None:
        result = prepare_contribution(self.proposal, self.state_dir)
        submitted = {
            "status": "SUBMITTED",
            "contribution_id": self.proposal["proposal_id"],
            "issue_url": "https://github.com/Ian-Tseng/analyze-project-claims/issues/123",
            "visibility": "PUBLIC",
            "next_action": "owner_triage_then_optional_agent-ready_label",
            "newly_created": True,
        }
        args = Namespace(
            command="contribution-submit",
            state_dir=self.state_dir,
            draft=Path(result["draft_path"]),
            approve=result["approval_id"],
            approved=True,
            allow_public_issue=True,
        )
        with patch.object(skill_quality_loop.contribution, "submit_contribution", return_value=submitted):
            with patch.object(
                skill_quality_loop.QualityStore,
                "record_outbound",
                side_effect=OSError("simulated accounting failure"),
            ):
                output = skill_quality_loop._run(args)
        self.assertEqual(output["status"], "SUBMITTED")
        self.assertEqual(output["local_accounting"], "WARNING")
        self.assertIn("Do not resubmit", output["warning"])

    def test_no_issue_proposal_is_not_contribution_eligible(self) -> None:
        proposal = dict(
            self.proposal,
            quality_signal="no_issue",
            recommended_action="no_change_recommended",
        )
        with self.assertRaisesRegex(ContributionError, "CONTRIBUTION_PROPOSAL_INELIGIBLE"):
            prepare_contribution(proposal, self.state_dir)

    def test_destination_cannot_be_rebound_to_another_repository(self) -> None:
        draft = prepare_contribution(self.proposal, self.state_dir)["draft"]
        draft["destination"] = "Ian-Tseng/analyze-project-claims"
        draft["content_fingerprint_sha256"] = content_fingerprint(draft)
        draft["approval_id"] = approval_id(draft)
        with self.assertRaisesRegex(ContributionError, "CONTRIBUTION_DESTINATION_INVALID"):
            validate_draft(draft)

    def test_stale_approval_is_rejected_before_network(self) -> None:
        result = prepare_contribution(self.proposal, self.state_dir)
        fake = FakeGitHub()
        with self.assertRaisesRegex(ContributionError, "CONTRIBUTION_APPROVAL_MISMATCH"):
            submit_contribution(
                Path(result["draft_path"]),
                approve="0" * 64,
                approved=True,
                allow_public_issue=True,
                runner=fake,
            )
        self.assertEqual(fake.commands, [])

    def test_owner_intake_accepts_exact_quality_body_only_after_owner_label(self) -> None:
        result = prepare_contribution(self.proposal, self.state_dir)
        draft = result["draft"]
        event = {
            "action": "labeled",
            "label": {"name": "agent-ready"},
            "sender": {"login": "Ian-Tseng"},
            "repository": {"full_name": "Ian-Tseng/example-producer"},
            "issue": {
                "number": 123,
                "html_url": "https://github.com/Ian-Tseng/example-producer/issues/123",
                "state": "open",
                "labels": [{"name": "agent-ready"}],
                "title": github_title(draft),
                "body": github_body(draft),
            },
        }
        task = prepare_task(
            event,
            repo_root=ROOT,
            expected_repository="Ian-Tseng/example-producer",
            allowed_actors={"Ian-Tseng"},
            base_sha="d" * 40,
        )
        self.assertEqual(task["source"], "github-bounded-quality-contribution")
        self.assertEqual(task["quality_signal"], "documentation_mismatch")
        self.assertNotIn("body", json.dumps(task).lower())


if __name__ == "__main__":
    unittest.main()
