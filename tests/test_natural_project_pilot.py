from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "evaluation" / "scripts" / "natural_project_pilot.py"


def load_module():
    spec = importlib.util.spec_from_file_location("natural_project_pilot_public", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selection() -> dict:
    projects = []
    rows = [
        ("python_signing", "pallets/itsdangerous", "Python", "security_library", "1"),
        ("js_concurrency", "sindresorhus/p-map", "JavaScript", "async_library", "2"),
        ("rust_benchmark", "sharkdp/hyperfine", "Rust", "cli_application", "3"),
        ("go_router", "go-chi/chi", "Go", "web_library", "4"),
    ]
    for project_id, repository, language, stratum, digit in rows:
        commit = digit * 40
        projects.append(
            {
                "id": project_id,
                "repository_url": f"https://github.com/{repository}",
                "commit_sha": commit,
                "origin": "natural_external",
                "outcome_known": False,
                "used_in_skill_development": False,
                "primary_language": language,
                "task_stratum": stratum,
                "license": {
                    "spdx_ids": ["MIT"],
                    "file_paths": ["LICENSE"],
                    "evidence_urls": [
                        f"https://github.com/{repository}/blob/{commit}/LICENSE"
                    ],
                },
                "public_distribution": {"include_source_snapshot": False},
            }
        )
    return {
        "schema_version": "APC_NATURAL_PROJECT_SELECTION_V1",
        "selection_id": "apc-natural-development-pilot-v1",
        "phase": "development_pilot",
        "evidence_role": "development_evaluation",
        "claim_boundary": "Protocol feasibility and variance estimation in these four projects only.",
        "paper_table_eligible": False,
        "general_reliability_proved": False,
        "selection_frozen_before_outcome_review": True,
        "sampling_rule": {
            "outcome_fields_inspected": False,
            "selection_basis": "metadata-only stratification by language and task",
            "minimum_projects": 4,
            "maximum_projects": 6,
        },
        "excluded_repositories": [
            "https://github.com/example/originating-rag-project"
        ],
        "packet_limits": {
            "maximum_files_per_project": 100,
            "maximum_bytes_per_project": 100000,
        },
        "annotator_slots": [
            {
                "id": "human_a",
                "kind": "human",
                "independent": True,
                "condition_blinded": True,
                "identity_status": "unassigned",
            },
            {
                "id": "human_b",
                "kind": "human",
                "independent": True,
                "condition_blinded": True,
                "identity_status": "unassigned",
            },
        ],
        "projects": projects,
    }


def create_snapshots(root: Path, value: dict) -> None:
    for project in value["projects"]:
        project_root = root / project["id"]
        project_root.mkdir(parents=True)
        (project_root / "README.md").write_text(
            f"# {project['id']}\n", encoding="utf-8"
        )
        license_path = project_root / "LICENSE"
        license_path.write_text("MIT fixture\n", encoding="utf-8")
        provenance = {
            "schema_version": "APC_PINNED_PROJECT_SOURCE_V1",
            "project_id": project["id"],
            "repository_url": project["repository_url"],
            "commit_sha": project["commit_sha"],
            "archive_url": (
                project["repository_url"].replace("github.com", "codeload.github.com")
                + f"/zip/{project['commit_sha']}"
            ),
            "archive_sha256": "a" * 64,
            "acquired_at": "2026-08-09T00:00:00Z",
            "license_file_sha256": {"LICENSE": sha256(license_path)},
        }
        (project_root / ".apc-source.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )


class NaturalProjectPilotTests(unittest.TestCase):
    def test_metadata_selection_rejects_outcome_known_projects(self) -> None:
        module = load_module()
        value = selection()
        value["projects"][0]["outcome_known"] = True

        with self.assertRaisesRegex(module.ContractError, "outcome_known"):
            module.validate_selection(value)

    def test_selection_requires_four_diverse_natural_projects(self) -> None:
        module = load_module()
        value = selection()
        result = module.validate_selection(value)
        self.assertEqual(result["project_count"], 4)
        self.assertEqual(result["language_count"], 4)

        value["projects"] = value["projects"][:3]
        with self.assertRaisesRegex(module.ContractError, "4-6"):
            module.validate_selection(value)

    def test_prepares_two_identical_blinded_annotation_packets(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            value = selection()
            selection_path = temporary_root / "selection.json"
            selection_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            snapshot_root = temporary_root / "snapshots"
            create_snapshots(snapshot_root, value)

            result = module.prepare_annotation_workspace(
                selection_path, snapshot_root, temporary_root / "runs"
            )
            run_dir = Path(result["run_dir"])
            self.assertEqual(result["annotation_packet_count"], 8)
            self.assertFalse(result["paper_table_eligible"])
            self.assertFalse(result["general_reliability_proved"])
            artifact_manifest = json.loads(
                (run_dir / "controller" / "monitor_artifact_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                len(artifact_manifest["files"]),
                2 + result["annotation_packet_count"],
            )

            for project in value["projects"]:
                first = json.loads(
                    (run_dir / "annotation_packets" / "human_a" / project["id"] / "packet_manifest.json").read_text(encoding="utf-8")
                )
                second = json.loads(
                    (run_dir / "annotation_packets" / "human_b" / project["id"] / "packet_manifest.json").read_text(encoding="utf-8")
                )
                self.assertEqual(first["snapshot_sha256"], second["snapshot_sha256"])
                self.assertFalse(first["condition_prompts_included"])
                self.assertFalse(first["agent_outputs_included"])
                self.assertFalse(first["other_annotator_labels_included"])

            gate = module.execution_gate_status(run_dir)
            self.assertEqual(gate["execution_state"], "blocked")
            self.assertIn("independent_human_labels", gate["missing_gates"])
            self.assertIn("frozen_annotation_codebook", gate["missing_gates"])
            self.assertIn("two_live_agent_families", gate["missing_gates"])
            self.assertFalse(gate["paper_table_eligible"])

    def test_public_evaluation_tree_cannot_hold_natural_snapshots(self) -> None:
        module = load_module()
        value = selection()
        with tempfile.TemporaryDirectory() as temporary:
            selection_path = Path(temporary) / "selection.json"
            selection_path.write_text(json.dumps(value), encoding="utf-8")
            forbidden = ROOT / "evaluation" / "projects" / "natural-pilot-test"
            with self.assertRaisesRegex(module.ContractError, "public bundle"):
                module.validate_snapshot_root(forbidden, ROOT)


if __name__ == "__main__":
    unittest.main()


