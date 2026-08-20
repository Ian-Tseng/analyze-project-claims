"""Private, replay-safe receipt and proposal store."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import contract


STATE_KEYS = {"schema_version", "receipts", "proposals", "hook_turns", "outbound_contributions"}
MAX_RECEIPTS = 64
MAX_PROPOSALS = 128
MAX_HOOK_TURNS = 256
RECOMMENDATIONS = {
    "claim_evidence_gap": "review_claim_evidence_binding",
    "lifecycle_inconsistency": "review_lifecycle_contract",
    "documentation_mismatch": "review_documentation_contract",
    "internal_failure": "prepare_bounded_regression",
    "no_issue": "no_change_recommended",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


class QualityStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.path = self.directory / "quality-loop-state.json"
        self.lock_path = self.directory / "quality-loop.lock"

    def _ensure_directory(self) -> None:
        if self.directory.exists() and self.directory.is_symlink():
            raise contract.QualityError("QUALITY_STATE_UNSAFE", "Quality-loop state directory cannot be a symlink.")
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.directory.is_dir() or self.directory.is_symlink():
            raise contract.QualityError("QUALITY_STATE_UNSAFE", "Quality-loop state directory is unsafe.")

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self._ensure_directory()
        handle = self.lock_path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "receipts": {},
            "proposals": {},
            "hook_turns": {},
            "outbound_contributions": {},
        }

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        if self.path.is_symlink() or not self.path.is_file():
            raise contract.QualityError("QUALITY_STATE_UNSAFE", "Quality-loop state file is unsafe.")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise contract.QualityError("QUALITY_STATE_INVALID", "Quality-loop state is not strict JSON.") from exc
        if not isinstance(value, dict) or set(value) != STATE_KEYS or value.get("schema_version") != 1:
            raise contract.QualityError("QUALITY_STATE_INVALID", "Quality-loop state has an invalid shape.")
        if not all(isinstance(value[key], dict) for key in ("receipts", "proposals", "hook_turns")):
            raise contract.QualityError("QUALITY_STATE_INVALID", "Quality-loop registries are invalid.")
        if not isinstance(value["outbound_contributions"], dict):
            raise contract.QualityError("QUALITY_STATE_INVALID", "Quality-loop outbound registry is invalid.")
        return value

    def _write(self, state: Mapping[str, Any]) -> None:
        self._ensure_directory()
        payload = json.dumps(state, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(prefix=".quality-loop-", suffix=".tmp", dir=self.directory)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _turn_key(session_id: str, turn_id: str) -> str:
        return hashlib.sha256(f"{session_id}:{turn_id}".encode("utf-8")).hexdigest()

    @staticmethod
    def _proposal_id(receipt_digest: str, analyzer_version: str) -> str:
        digest = hashlib.sha256(f"{receipt_digest}:{analyzer_version}".encode("utf-8")).hexdigest()
        return "quality-proposal-" + digest[:24]

    @staticmethod
    def _prune_receipts(state: dict[str, Any], current: datetime) -> bool:
        changed = False
        for digest, record in list(state["receipts"].items()):
            if record.get("state") in {"CONSUMED", "PROPOSAL_COMMITTED"}:
                state["receipts"].pop(digest)
                changed = True
                continue
            receipt = record.get("receipt")
            if not isinstance(receipt, dict):
                raise contract.QualityError("QUALITY_STATE_INVALID", "Stored receipt is invalid.")
            expires = _parse_utc(receipt.get("expires_at_utc"))
            if expires <= current:
                state["receipts"].pop(digest)
                changed = True
                continue
            if record.get("state") == "CLAIMED":
                lease_text = record.get("lease_expires_at_utc")
                if not isinstance(lease_text, str):
                    raise contract.QualityError("QUALITY_STATE_INVALID", "Stored lease is invalid.")
                if _parse_utc(lease_text) <= current:
                    record["state"] = "READY"
                    record["lease_id"] = None
                    record["lease_expires_at_utc"] = None
                    changed = True
        return changed

    @staticmethod
    def _free_proposal_capacity(state: dict[str, Any]) -> bool:
        changed = False
        dismissed = sorted(
            (
                proposal
                for proposal in state["proposals"].values()
                if proposal.get("status") == "dismissed"
            ),
            key=lambda proposal: (
                proposal.get("dismissed_at_utc", ""),
                proposal.get("proposal_id", ""),
            ),
        )
        while len(state["proposals"]) >= MAX_PROPOSALS and dismissed:
            proposal = dismissed.pop(0)
            state["proposals"].pop(proposal["proposal_id"], None)
            changed = True
        return changed

    def receive(self, receipt: Mapping[str, Any], *, envelope: Mapping[str, str] | None = None) -> dict[str, Any]:
        validated = contract.validate_receipt(dict(receipt))
        digest = validated["receipt_digest_sha256"]
        with self._lock():
            state = self._read()
            changed = self._prune_receipts(state, _utc_now())
            existing = state["receipts"].get(digest)
            if existing is not None:
                if changed:
                    self._write(state)
                return dict(existing)
            if len(state["receipts"]) >= MAX_RECEIPTS:
                raise contract.QualityError("QUALITY_QUEUE_FULL", "The bounded receipt queue is full.")
            record = {
                "receipt": validated,
                "state": "READY",
                "received_at_utc": _utc_text(_utc_now()),
                "lease_id": None,
                "lease_expires_at_utc": None,
                "proposal_id": None,
                "host_envelope": dict(envelope or {}),
            }
            state["receipts"][digest] = record
            self._write(state)
            return dict(record)

    def claim(
        self,
        receipt_digest: str,
        *,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = (now or _utc_now()).astimezone(timezone.utc)
        with self._lock():
            state = self._read()
            self._prune_receipts(state, current)
            record = state["receipts"].get(receipt_digest)
            if record is None:
                raise contract.QualityError("NO_COMPATIBLE_RECEIPT", "The receipt is not in local state.")
            if record["state"] in {"CONSUMED", "PROPOSAL_COMMITTED"}:
                return dict(record)
            if record["state"] == "CLAIMED":
                expires = _parse_utc(record["lease_expires_at_utc"])
                if expires > current:
                    raise contract.QualityError("RECEIPT_BUSY", "The receipt has an active analyzer lease.")
            record["state"] = "CLAIMED"
            record["lease_id"] = str(uuid.uuid4())
            record["lease_expires_at_utc"] = _utc_text(current + timedelta(seconds=lease_seconds))
            self._write(state)
            return dict(record)

    def consume(
        self,
        receipt: Mapping[str, Any],
        *,
        analyzer_version: str,
        lease_id: str | None = None,
    ) -> dict[str, Any]:
        validated = contract.validate_receipt(dict(receipt))
        digest = validated["receipt_digest_sha256"]
        proposal_id = self._proposal_id(digest, analyzer_version)
        current = _utc_now()
        with self._lock():
            state = self._read()
            self._prune_receipts(state, current)
            if validated["requested_action"] == "none":
                state["receipts"].pop(digest, None)
                self._write(state)
                return {
                    "receipt_digest_sha256": digest,
                    "analyzer_version": analyzer_version,
                    "quality_signal": validated["quality_signal"],
                    "recommended_action": RECOMMENDATIONS[validated["quality_signal"]],
                    "status": "no_action",
                    "outbound": "NONE",
                    "deduplicated": True,
                }
            existing = state["proposals"].get(proposal_id)
            if existing is not None:
                if digest in state["receipts"]:
                    state["receipts"].pop(digest)
                    self._write(state)
                result = dict(existing)
                result["deduplicated"] = True
                return result
            self._free_proposal_capacity(state)
            if len(state["proposals"]) >= MAX_PROPOSALS:
                raise contract.QualityError("QUALITY_PROPOSAL_LIMIT", "The bounded proposal store is full.")
            record = state["receipts"].get(digest)
            if record is None:
                if len(state["receipts"]) >= MAX_RECEIPTS:
                    raise contract.QualityError("QUALITY_QUEUE_FULL", "The bounded receipt queue is full.")
                record = {
                    "receipt": validated,
                    "state": "READY",
                    "received_at_utc": _utc_text(_utc_now()),
                    "lease_id": None,
                    "lease_expires_at_utc": None,
                    "proposal_id": None,
                    "host_envelope": {},
                }
                state["receipts"][digest] = record
            if record["state"] == "CLAIMED" and record["lease_expires_at_utc"] is not None:
                if _parse_utc(record["lease_expires_at_utc"]) > current and lease_id != record["lease_id"]:
                    raise contract.QualityError("RECEIPT_BUSY", "The receipt has an active analyzer lease.")
            proposal = {
                "proposal_id": proposal_id,
                "receipt_digest_sha256": digest,
                "analyzer_version": analyzer_version,
                "producer": validated["producer"],
                "outcome": validated["outcome"],
                "quality_signal": validated["quality_signal"],
                "recommended_action": RECOMMENDATIONS[validated["quality_signal"]],
                "status": "active",
                "created_at_utc": _utc_text(_utc_now()),
                "outbound": "NONE",
            }
            state["proposals"][proposal_id] = proposal
            state["receipts"].pop(digest, None)
            self._write(state)
            result = dict(proposal)
            result["deduplicated"] = False
            return result

    def consume_next(self, *, analyzer_version: str) -> dict[str, Any]:
        with self._lock():
            state = self._read()
            changed = self._prune_receipts(state, _utc_now())
            ready = [
                record["receipt"]
                for record in state["receipts"].values()
                if record.get("state") == "READY"
            ]
            busy = any(record.get("state") == "CLAIMED" for record in state["receipts"].values())
            if changed:
                self._write(state)
        if not ready:
            if busy:
                raise contract.QualityError("RECEIPT_BUSY", "Pending receipts have active analyzer leases.")
            raise contract.QualityError("NO_COMPATIBLE_RECEIPT", "No pending compatible receipt is available.")
        ready.sort(key=lambda item: (item["created_at_utc"], item["receipt_digest_sha256"]))
        return self.consume(ready[0], analyzer_version=analyzer_version)

    def handle_stop_event(self, event: object) -> dict[str, Any]:
        if not isinstance(event, dict) or event.get("hook_event_name") != "Stop":
            return {}
        if event.get("stop_hook_active") is not False:
            return {}
        session_id = event.get("session_id")
        turn_id = event.get("turn_id")
        message = event.get("last_assistant_message")
        if not all(isinstance(value, str) and 1 <= len(value) <= 200 for value in (session_id, turn_id)):
            return {}
        try:
            receipt = contract.extract_trailing_marker(message)
        except contract.QualityError:
            return {}
        if (
            receipt["requested_action"] != "analyze_quality"
            or receipt["quality_signal"] == "no_issue"
            or receipt["causal_depth"] > 0
            or receipt["producer"]["skill"] == "analyze-project-claims"
        ):
            return {}
        digest = receipt["receipt_digest_sha256"]
        turn_key = self._turn_key(session_id, turn_id)
        with self._lock():
            state = self._read()
            self._prune_receipts(state, _utc_now())
            if turn_key in state["hook_turns"]:
                return {}
            if len(state["hook_turns"]) >= MAX_HOOK_TURNS:
                oldest = sorted(state["hook_turns"], key=lambda key: state["hook_turns"][key]["created_at_utc"])[0]
                state["hook_turns"].pop(oldest)
            if digest not in state["receipts"]:
                if len(state["receipts"]) >= MAX_RECEIPTS:
                    return {}
                state["receipts"][digest] = {
                    "receipt": receipt,
                    "state": "READY",
                    "received_at_utc": _utc_text(_utc_now()),
                    "lease_id": None,
                    "lease_expires_at_utc": None,
                    "proposal_id": None,
                    "host_envelope": {"session_id": session_id, "turn_id": turn_id},
                }
            state["hook_turns"][turn_key] = {
                "receipt_digest_sha256": digest,
                "created_at_utc": _utc_text(_utc_now()),
            }
            self._write(state)
        return {
            "decision": "block",
            "reason": (
                "Use $analyze-project-claims to consume the pending SkillOutcomeReceipt "
                f"{digest} and create one local-only quality proposal. Do not submit, edit, release, or update anything."
            ),
        }

    def status(self) -> dict[str, Any]:
        with self._lock():
            state = self._read()
            if self._prune_receipts(state, _utc_now()):
                self._write(state)
        pending = sum(1 for item in state["receipts"].values() if item.get("state") in {"READY", "CLAIMED"})
        return {
            "status": "READY",
            "receipt_count": len(state["receipts"]),
            "pending_receipts": pending,
            "proposal_count": len(state["proposals"]),
            "outbound_actions": len(state["outbound_contributions"]),
        }

    def proposal(self, proposal_id: str) -> dict[str, Any]:
        with self._lock():
            proposal = self._read()["proposals"].get(proposal_id)
        if proposal is None:
            raise contract.QualityError("PROPOSAL_NOT_FOUND", "The local proposal does not exist.")
        return dict(proposal)

    def dismiss(self, proposal_id: str) -> dict[str, Any]:
        with self._lock():
            state = self._read()
            proposal = state["proposals"].get(proposal_id)
            if proposal is None:
                raise contract.QualityError("PROPOSAL_NOT_FOUND", "The local proposal does not exist.")
            proposal["status"] = "dismissed"
            proposal["dismissed_at_utc"] = _utc_text(_utc_now())
            self._write(state)
            return dict(proposal)

    def record_outbound(self, contribution_id: str, issue_url: str) -> None:
        with self._lock():
            state = self._read()
            state["outbound_contributions"][contribution_id] = issue_url
            self._write(state)
