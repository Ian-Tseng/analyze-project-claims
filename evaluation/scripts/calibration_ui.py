#!/usr/bin/env python3
"""Local, role-isolated UI for human annotation-codebook calibration.

The server is intentionally dependency-free and loopback-only. It delegates
scientific validation, calibration freezing, and study binding to the existing
controllers; it never creates human judgments or relaxes their attestations.
"""

from __future__ import annotations

import argparse
import json
import secrets
import tempfile
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlparse

import annotation_calibration as calibration
import natural_project_pilot as natural_pilot


FRONTEND = Path(__file__).resolve().parents[1] / "ui" / "calibration-console.html"
MAX_REQUEST_BYTES = 5 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class UIContractError(RuntimeError):
    """A request violates the role, artifact, or lifecycle contract."""


def _ui_error(exc: Exception) -> UIContractError:
    if isinstance(exc, UIContractError):
        return exc
    return UIContractError(str(exc))


def _sha256(path: Path) -> str:
    return calibration._file_sha256(path)


class CalibrationUIService:
    """Role-aware application service used by both HTTP handlers and tests."""

    def __init__(
        self,
        calibration_run_dir: Path | str,
        *,
        pilot_run_dir: Path | str | None = None,
        role_tokens: dict[str, str] | None = None,
    ) -> None:
        self.run_dir = Path(calibration_run_dir).resolve()
        try:
            self.manifest, self.selection, self.source = calibration._calibration_context(
                self.run_dir
            )
        except Exception as exc:
            raise _ui_error(exc) from exc
        self.project_id = self.selection["project"]["id"]
        self.slot_ids = tuple(row["id"] for row in self.selection["annotator_slots"])
        self.pilot_run_dir = Path(pilot_run_dir).resolve() if pilot_run_dir else None
        if self.pilot_run_dir is not None:
            pilot_manifest = self.pilot_run_dir / "controller" / "selection_manifest.json"
            if not pilot_manifest.is_file():
                raise UIContractError(f"pilot selection manifest is missing: {pilot_manifest}")

        roles = ("coordinator", *self.slot_ids)
        if role_tokens is None:
            role_tokens = {role: secrets.token_urlsafe(32) for role in roles}
        if set(role_tokens) != set(roles):
            raise UIContractError("role tokens must cover coordinator and every annotator slot")
        if any(not isinstance(token, str) or len(token) < 8 for token in role_tokens.values()):
            raise UIContractError("each role token must contain at least 8 characters")
        if len(set(role_tokens.values())) != len(role_tokens):
            raise UIContractError("role tokens must be unique")
        self.role_tokens = dict(role_tokens)

    def token_for(self, role: str) -> str:
        try:
            return self.role_tokens[role]
        except KeyError as exc:
            raise UIContractError(f"unknown UI role: {role}") from exc

    def _role(self, token: str) -> str:
        if not isinstance(token, str):
            raise UIContractError("invalid role token")
        for role, expected in self.role_tokens.items():
            if secrets.compare_digest(token, expected):
                return role
        raise UIContractError("invalid role token")

    def _require_coordinator(self, token: str) -> None:
        if self._role(token) != "coordinator":
            raise UIContractError("coordinator role required")

    def _require_annotator(self, token: str) -> str:
        role = self._role(token)
        if role not in self.slot_ids:
            raise UIContractError("annotation view is not available for this role")
        return role

    def _annotation_path(self, slot_id: str) -> Path:
        return self.run_dir / "review" / "raw_labels" / slot_id / f"{self.project_id}.json"

    def _template_path(self, slot_id: str) -> Path:
        return (
            self.run_dir
            / "annotation_packets"
            / slot_id
            / self.project_id
            / "annotation.template.json"
        )

    def _snapshot_root(self, slot_id: str) -> Path:
        return (
            self.run_dir
            / "annotation_packets"
            / slot_id
            / self.project_id
            / "snapshot"
        ).resolve()

    def _validate_submission(self, slot_id: str, artifact: dict[str, Any]) -> None:
        try:
            calibration._require(isinstance(artifact, dict), "annotation must be an object")
            allowed = {
                "schema_version",
                "selection_sha256",
                "project_id",
                "annotator_slot_id",
                "snapshot_sha256",
                "annotator_id",
                "completed",
                "human_attestation",
                "element_inventory",
                "candidate_findings",
                "notes",
            }
            calibration._require(
                set(artifact).issubset(allowed),
                "annotation contains unsupported fields",
            )
            label = f"calibration/{slot_id}/{self.project_id}.json"
            calibration._require(
                artifact.get("schema_version") == calibration.ANNOTATION_SCHEMA,
                f"invalid annotation schema: {label}",
            )
            calibration._require(
                artifact.get("selection_sha256") == self.manifest["selection_sha256"],
                f"annotation selection mismatch: {label}",
            )
            calibration._require(
                artifact.get("project_id") == self.project_id,
                f"annotation project mismatch: {label}",
            )
            calibration._require(
                artifact.get("annotator_slot_id") == slot_id,
                f"annotation slot mismatch: {label}",
            )
            calibration._require(
                artifact.get("snapshot_sha256")
                == self.source["projects"][0]["snapshot_sha256"],
                f"annotation snapshot mismatch: {label}",
            )
            calibration._nonempty_text(artifact.get("annotator_id"), f"{label} annotator_id")
            calibration._require(
                artifact.get("completed") is True,
                f"annotation is not complete: {label}",
            )
            attestation = artifact.get("human_attestation")
            calibration._require(isinstance(attestation, dict), f"missing human attestation: {label}")
            calibration._require(
                set(attestation)
                == {
                    "human_annotator",
                    "independent",
                    "condition_blinded",
                    "no_agent_outputs_reviewed",
                    "attested_at",
                },
                f"invalid human attestation fields: {label}",
            )
            for field in (
                "human_annotator",
                "independent",
                "condition_blinded",
                "no_agent_outputs_reviewed",
            ):
                calibration._require(
                    attestation.get(field) is True,
                    f"annotation attestation {field} is not true: {label}",
                )
            calibration._nonempty_text(attestation.get("attested_at"), f"{label} attested_at")
            element_ids = calibration._validate_element_inventory(
                artifact.get("element_inventory"), label
            )
            calibration._validate_candidate_findings(
                artifact.get("candidate_findings"), element_ids, label
            )
        except Exception as exc:
            raise _ui_error(exc) from exc

    def _discussion_enabled(self) -> bool:
        try:
            calibration.calibration_label_preflight(self.run_dir)
            return True
        except calibration.ContractError:
            return False

    def state(self, token: str) -> dict[str, Any]:
        role = self._role(token)
        try:
            status = calibration.calibration_status(self.run_dir)
        except Exception as exc:
            raise _ui_error(exc) from exc
        if role in self.slot_ids:
            path = self._annotation_path(role)
            return {
                "role": "annotator",
                "slot_id": role,
                "project_id": self.project_id,
                "run_group_id": self.manifest["run_group_id"],
                "submission_state": "committed" if path.is_file() else "draft",
                "calibration_state": status["calibration_state"],
                "other_annotator_data_visible": False,
                "paper_table_eligible": False,
                "general_reliability_proved": False,
            }

        slots = [
            {
                "slot_id": slot_id,
                "submission_state": (
                    "committed" if self._annotation_path(slot_id).is_file() else "pending"
                ),
            }
            for slot_id in self.slot_ids
        ]
        pilot_gate = None
        if self.pilot_run_dir is not None:
            try:
                pilot_gate = natural_pilot.execution_gate_status(self.pilot_run_dir)
            except Exception as exc:
                raise _ui_error(exc) from exc
        return {
            "role": "coordinator",
            "project_id": self.project_id,
            "run_group_id": self.manifest["run_group_id"],
            "calibration_state": status["calibration_state"],
            "slots": slots,
            "annotator_access": [
                {
                    "slot_id": slot_id,
                    "fragment": f"#token={self.role_tokens[slot_id]}",
                }
                for slot_id in self.slot_ids
            ],
            "discussion_enabled": self._discussion_enabled(),
            "freeze_enabled": status["calibration_state"] != "complete"
            and self._discussion_enabled(),
            "pilot_available": self.pilot_run_dir is not None,
            "pilot_gate": pilot_gate,
            "paper_table_eligible": False,
            "general_reliability_proved": False,
        }

    def annotation(self, token: str) -> dict[str, Any]:
        slot_id = self._require_annotator(token)
        path = self._annotation_path(slot_id)
        source = path if path.is_file() else self._template_path(slot_id)
        try:
            return calibration._load_json(source)
        except Exception as exc:
            raise _ui_error(exc) from exc

    def codebook(self, token: str) -> dict[str, Any]:
        self._role(token)
        final = self.run_dir / "protocol" / "final-annotation-codebook.md"
        path = final if final.is_file() else self.run_dir / "protocol" / "annotation-codebook.md"
        if not path.is_file():
            raise UIContractError("annotation codebook is missing")
        return {
            "state": "frozen_final" if path == final else "initial",
            "sha256": _sha256(path),
            "content": path.read_text(encoding="utf-8"),
        }

    def source_index(self, token: str) -> dict[str, Any]:
        slot_id = self._require_annotator(token)
        root = self._snapshot_root(slot_id)
        if not root.is_dir():
            raise UIContractError("annotation source snapshot is missing")
        files = [
            {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size}
            for path in sorted(root.rglob("*"))
            if path.is_file()
        ]
        return {"project_id": self.project_id, "files": files}

    def source_text(self, token: str, relative_path: str) -> dict[str, Any]:
        slot_id = self._require_annotator(token)
        candidate = PurePosixPath(relative_path)
        if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
            raise UIContractError("unsafe source path")
        root = self._snapshot_root(slot_id)
        path = (root / Path(*candidate.parts)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise UIContractError("unsafe source path") from exc
        if not path.is_file():
            raise UIContractError("source file is not available")
        size = path.stat().st_size
        if size > MAX_SOURCE_BYTES:
            raise UIContractError("source file exceeds the UI preview limit")
        raw = path.read_bytes()
        if b"\x00" in raw:
            raise UIContractError("binary source preview is not available")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UIContractError("non-UTF-8 source preview is not available") from exc
        return {"path": candidate.as_posix(), "bytes": size, "content": content}

    def submit_annotation(self, token: str, artifact: dict[str, Any]) -> dict[str, Any]:
        slot_id = self._require_annotator(token)
        if (self.run_dir / "review" / "calibration_commitment.json").is_file():
            raise UIContractError("calibration is already frozen")
        if (self.run_dir / "review" / "calibration_discussion.json").is_file():
            raise UIContractError("discussion already started; raw annotations are immutable")
        self._validate_submission(slot_id, artifact)
        path = self._annotation_path(slot_id)
        if path.is_file():
            if calibration._load_json(path) == artifact:
                return {
                    "submission_state": "committed",
                    "reused_existing": True,
                    "sha256": _sha256(path),
                }
            raise UIContractError("annotation is already committed and cannot be rewritten")
        try:
            calibration._atomic_json(path, artifact)
            self._validate_submission(slot_id, calibration._load_json(path))
        except Exception as exc:
            raise _ui_error(exc) from exc
        return {
            "submission_state": "committed",
            "reused_existing": False,
            "sha256": _sha256(path),
        }

    def discussion_context(self, token: str) -> dict[str, Any]:
        self._require_coordinator(token)
        try:
            preflight = calibration.calibration_label_preflight(self.run_dir)
        except Exception as exc:
            raise _ui_error(exc) from exc
        annotations = {
            slot_id: calibration._load_json(self._annotation_path(slot_id))
            for slot_id in self.slot_ids
        }
        return {"preflight": preflight, "annotations": annotations}

    def freeze_calibration(
        self,
        token: str,
        *,
        final_codebook: str,
        disagreement_items: list[Any],
        codebook_decisions: list[Any],
    ) -> dict[str, Any]:
        self._require_coordinator(token)
        if not isinstance(final_codebook, str) or not final_codebook.strip():
            raise UIContractError("final codebook must be non-empty text")
        if not isinstance(disagreement_items, list) or not isinstance(codebook_decisions, list):
            raise UIContractError("discussion items and codebook decisions must be arrays")
        frozen_codebook = self.run_dir / "protocol" / "final-annotation-codebook.md"
        commitment_path = self.run_dir / "review" / "calibration_commitment.json"
        if commitment_path.is_file():
            try:
                return calibration.freeze_calibration(self.run_dir, frozen_codebook)
            except Exception as exc:
                raise _ui_error(exc) from exc

        try:
            preflight = calibration.calibration_label_preflight(self.run_dir)
        except Exception as exc:
            raise _ui_error(exc) from exc
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".md",
                prefix=".calibration-ui-codebook-",
                dir=self.run_dir / "review",
                delete=False,
                newline="",
            ) as handle:
                handle.write(final_codebook)
                temp_path = Path(handle.name)
            discussion = {
                "schema_version": calibration.CALIBRATION_DISCUSSION_SCHEMA,
                "selection_sha256": self.manifest["selection_sha256"],
                "codebook_initial_sha256": self.selection["codebook"]["sha256"],
                "status": "complete",
                "independent_annotation_sha256": preflight["raw_label_sha256"],
                "disagreement_items": disagreement_items,
                "codebook_decisions": codebook_decisions,
                "codebook_revised": _sha256(temp_path) != self.selection["codebook"]["sha256"],
                "codebook_final_sha256": _sha256(temp_path),
                "completed_at": calibration._now(),
                "reuse_in_development_or_confirmation_prohibited": True,
                "paper_table_eligible": False,
                "general_reliability_proved": False,
            }
            calibration._validate_calibration_discussion(
                discussion,
                self.manifest,
                self.selection,
                preflight["raw_label_sha256"],
                temp_path,
            )
            discussion_path = self.run_dir / "review" / "calibration_discussion.json"
            if discussion_path.is_file():
                existing = calibration._load_json(discussion_path)
                comparable = {key: value for key, value in discussion.items() if key != "completed_at"}
                existing_comparable = {
                    key: value for key, value in existing.items() if key != "completed_at"
                }
                if existing_comparable != comparable:
                    raise UIContractError("a different calibration discussion is already recorded")
            else:
                calibration._atomic_json(discussion_path, discussion)
            return calibration.freeze_calibration(self.run_dir, temp_path)
        except Exception as exc:
            raise _ui_error(exc) from exc
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    def bind_study(self, token: str) -> dict[str, Any]:
        self._require_coordinator(token)
        if self.pilot_run_dir is None:
            raise UIContractError("pilot run was not configured for this UI session")
        try:
            return natural_pilot.bind_codebook(self.pilot_run_dir, self.run_dir)
        except Exception as exc:
            raise _ui_error(exc) from exc

    def pilot_gate(self, token: str) -> dict[str, Any]:
        self._require_coordinator(token)
        if self.pilot_run_dir is None:
            raise UIContractError("pilot run was not configured for this UI session")
        try:
            return natural_pilot.execution_gate_status(self.pilot_run_dir)
        except Exception as exc:
            raise _ui_error(exc) from exc


def create_server(
    service: CalibrationUIService,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    frontend_path: Path = FRONTEND,
) -> ThreadingHTTPServer:
    if host not in LOOPBACK_HOSTS:
        raise UIContractError("calibration UI must bind to a loopback host")
    page = frontend_path.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        server_version = "APCCalibrationUI/1"

        def log_message(self, _format: str, *args: object) -> None:
            return

        def _token(self) -> str:
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer "):
                raise UIContractError("invalid role token")
            return authorization[7:]

        def _send_json(self, status: HTTPStatus, payload: Any) -> None:
            body = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json_body(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise UIContractError("request body is missing")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise UIContractError("invalid request length") from exc
            if length < 0 or length > MAX_REQUEST_BYTES:
                raise UIContractError("request exceeds the UI size limit")
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise UIContractError("request body must be valid UTF-8 JSON") from exc
            if not isinstance(value, dict):
                raise UIContractError("request body must be a JSON object")
            return value

        def _dispatch(self) -> None:
            parsed = urlparse(self.path)
            token = self._token()
            if self.command == "GET" and parsed.path == "/api/state":
                self._send_json(HTTPStatus.OK, service.state(token))
            elif self.command == "GET" and parsed.path == "/api/annotation":
                self._send_json(HTTPStatus.OK, service.annotation(token))
            elif self.command == "GET" and parsed.path == "/api/codebook":
                self._send_json(HTTPStatus.OK, service.codebook(token))
            elif self.command == "GET" and parsed.path == "/api/source-index":
                self._send_json(HTTPStatus.OK, service.source_index(token))
            elif self.command == "GET" and parsed.path == "/api/source":
                query = parse_qs(parsed.query, strict_parsing=True)
                relative = query.get("path", [""])[0]
                self._send_json(HTTPStatus.OK, service.source_text(token, relative))
            elif self.command == "GET" and parsed.path == "/api/discussion-context":
                self._send_json(HTTPStatus.OK, service.discussion_context(token))
            elif self.command == "GET" and parsed.path == "/api/pilot-gate":
                self._send_json(HTTPStatus.OK, service.pilot_gate(token))
            elif self.command == "POST" and parsed.path == "/api/annotation":
                self._send_json(
                    HTTPStatus.OK,
                    service.submit_annotation(token, self._json_body()),
                )
            elif self.command == "POST" and parsed.path == "/api/freeze":
                body = self._json_body()
                self._send_json(
                    HTTPStatus.OK,
                    service.freeze_calibration(
                        token,
                        final_codebook=body.get("final_codebook"),
                        disagreement_items=body.get("disagreement_items"),
                        codebook_decisions=body.get("codebook_decisions"),
                    ),
                )
            elif self.command == "POST" and parsed.path == "/api/bind":
                self._json_body()
                self._send_json(HTTPStatus.OK, service.bind_study(token))
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "route not found"})

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/index.html"}:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(page)
                return
            try:
                self._dispatch()
            except UIContractError as exc:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
            except Exception:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal UI error"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._dispatch()
            except UIContractError as exc:
                self._send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
            except Exception:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal UI error"})

    return ThreadingHTTPServer((host, port), Handler)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--pilot-run-dir", type=Path)
    parser.add_argument("--host", default="127.0.0.1", choices=sorted(LOOPBACK_HOSTS))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        service = CalibrationUIService(
            args.run_dir,
            pilot_run_dir=args.pilot_run_dir,
        )
        server = create_server(service, host=args.host, port=args.port)
    except UIContractError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}/"
    print("Calibration Console is local and observational until a human submits a form.")
    print(f"Coordinator: {base}#token={service.token_for('coordinator')}")
    for slot_id in service.slot_ids:
        print(f"{slot_id}: {base}#token={service.token_for(slot_id)}")
    print("Share each annotator URL only with its assigned human. Press Ctrl+C to stop the UI.")
    if not args.no_browser:
        webbrowser.open(f"{base}#token={service.token_for('coordinator')}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
