"""Durable cooperative claim-review controller. Standard library; no host hooks."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid
import subagent_mode
import agent_cleanup
import agent_pool

ContractError = subagent_mode.ContractError

def require(condition, message):
    if not condition:
        raise ContractError(message)

def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()

def write_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("xb") as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def repair_cycle_limit(config):
    # Missing field identifies a pre-0.12 journal; never expand its authority.
    value = config.get("max_repair_cycles", 3)
    require(type(value) is int and 1 <= value <= 10000, "Invalid repair cycle budget")
    return value

def validate_config(config):
    require(isinstance(config, dict), "Config must be an object")
    for key in ("goal_id", "goal_revision", "objective", "authorization_ref"):
        require(isinstance(config.get(key), str) and config[key].strip(), f"Missing {key}")
    root = Path(config["project_root"]).resolve(strict=True)
    require(root.is_dir(), "project_root must be a directory")
    config = copy.deepcopy(config)
    config["project_root"] = str(root)
    require(isinstance(config.get("evidence"), list) and config["evidence"], "Declare evidence files")
    require(len(config["evidence"]) == len(set(config["evidence"])), "Duplicate evidence paths")
    require(isinstance(config.get("success_criteria"), list) and config["success_criteria"], "Declare success criteria")
    require(all(isinstance(x, str) and x for x in config["success_criteria"]), "Invalid criterion")
    require(len(set(config["success_criteria"])) == len(config["success_criteria"]), "Duplicate criteria")
    actions = config.get("actions")
    require(isinstance(actions, list) and actions, "Declare authorized actions")
    ids = [a["id"] for a in actions]
    require(all(isinstance(x, str) and x for x in ids) and len(set(ids)) == len(ids), "Invalid action IDs")
    for action in actions:
        require(action.get("kind", "work") in ("work", "validate", "repair"), "Invalid action kind")
        require(isinstance(action.get("instruction"), str) and action["instruction"], "Action needs instruction")
        for field in ("required", "requires_review"):
            require(type(action.get(field, True)) is bool, f"{field} must be boolean")
        require(set(action.get("depends_on", [])) <= set(ids) - {action["id"]}, "Unknown/self dependency")
        if action.get("kind") == "repair":
            require(action.get("attempt_id") and action.get("attempt_authorization_ref"), "Repair needs owner-authorized attempt")
            require(action.get("requires_review", True), "Repairs always require review")
        command = action.get("command")
        require(command is None or (isinstance(command, list) and command and all(isinstance(x, str) for x in command)), "Commands must be argv arrays")
        require(type(action.get("timeout_seconds", 300)) is int and 1 <= action.get("timeout_seconds", 300) <= 86400, "Invalid timeout")
    graph = {a["id"]: a.get("depends_on", []) for a in actions}
    def visit(key, chain):
        require(key not in chain, "Dependency cycle")
        for child in graph[key]:
            visit(child, chain | {key})
    for key in graph:
        visit(key, set())
    require(type(config.get("max_dispatches", 100)) is int and 1 <= config.get("max_dispatches", 100) <= 10000, "Invalid dispatch budget")
    command = config.get("reviewer_command")
    require(command is None or (isinstance(command, list) and command and all(isinstance(x, str) for x in command)), "Invalid reviewer command")
    require(type(config.get("max_spawn_attempts", 3)) is int and
            1 <= config.get("max_spawn_attempts", 3) <= 100,
            "max_spawn_attempts must be an integer from 1 to 100")
    repair_cycle_limit(config)
    subagent_mode.validate_config(config)
    agent_pool.validate_config(config)
    return config

def snapshot(config):
    root = Path(config["project_root"])
    files = {}
    identities = set()
    for name in sorted(config["evidence"]):
        rel = Path(name)
        require(not rel.is_absolute() and ".." not in rel.parts and rel.parts, "Evidence must be project-relative")
        path = root / rel
        for part in [path, *path.parents]:
            if part == root:
                break
            require(not subagent_mode.is_link_or_reparse(part), "Evidence may not cross links")
        require(path.resolve().is_relative_to(root), "Evidence escapes project")
        if not path.exists():
            files[name] = None
            continue
        require(path.is_file(), "Evidence must name a file")
        before = path.stat()
        if "agent_pool" in config:
            identity = (before.st_dev, before.st_ino)
            require(before.st_nlink <= 1 and identity not in identities, "Pool evidence cannot use hardlink aliases")
            identities.add(identity)
        sha = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(chunk)
        after = path.stat()
        if "agent_pool" in config:
            require(after.st_nlink <= 1 and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino), "Pool evidence identity changed while reading")
        require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "Evidence changed while reading")
        files[name] = sha.hexdigest()
    return {"files": files, "digest": digest(files)}

class Controller:
    def __init__(self, root):
        self.root = Path(root).resolve()

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "lock").open("a+b") as lock:
            lock.seek(0, 2)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ContractError("Controller busy; retry later") from exc
            try:
                yield
            finally:
                lock.seek(0)
                if os.name == "nt":
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _materialize(self, state):
        freshness = subagent_mode.observe_freshness(state, snapshot)
        subagent_mode.materialize(state, self.root, freshness)
        return freshness

    def _load(self, sync_reports=True):
        events = sorted((self.root / "journal").glob("*.json"))
        require(events, "Initialize the controller first")
        previous = None
        state = None
        for seq, path in enumerate(events, 1):
            event = read_json(path)
            actual = event.pop("digest")
            require(path.name == f"{seq:08d}.json" and event["seq"] == seq and event["previous"] == previous and digest(event) == actual, "Journal integrity failure")
            previous = actual
            state = event["state"]
        if sync_reports:
            self._materialize(state)
        return state, len(events), previous

    def _save(self, state, kind, seq, previous, sync_reports=True):
        journal = self.root / "journal"
        journal.mkdir(exist_ok=True)
        event = {"seq": seq + 1, "previous": previous, "kind": kind, "time": time.time(), "state": state}
        event["digest"] = digest(event)
        path = journal / f"{seq + 1:08d}.json"
        require(not path.exists(), "Journal conflict")
        write_json(path, event)
        if sync_reports:
            self._materialize(state)

    def init(self, config):
        require(isinstance(config, dict), "Config must be an object")
        config = copy.deepcopy(config)
        config.setdefault("max_repair_cycles", 32)
        config.setdefault("max_spawn_attempts", 3)
        config = validate_config(config)
        config = validate_config(agent_pool.configure_new(config))
        current = snapshot(config)
        with self.locked():
            require(not list((self.root / "journal").glob("*.json")), "Already initialized")
            state = {"config": config, "config_digest": digest(config), "control": "active", "complete": False,
                     "actions": {a["id"]: "pending" for a in config["actions"]}, "clearances": {}, "holds": {},
                     "findings": {}, "attempts": {}, "pending": None, "receipts": {}, "dispatches": 0,
                     "snapshot": current, "review_due": True, "review_failures": 0, "preferred": None,
                     "last_review": None}
            subagent_mode.initialize(state, self.root)
            agent_pool.initialize(state)
            self._save(state, "initialized", 0, None)
            return state

    def status(self):
        with self.locked():
            state = self._load(sync_reports=False)[0]
            freshness = self._materialize(state)
            result = dict(state, repair_cycle_limit=repair_cycle_limit(state["config"]))
            if freshness is not None:
                result["freshness"] = freshness
            return result

    def agent_cleanup(self, observation):
        with self.locked():
            state, seq, previous = self._load(sync_reports=False)
            require(subagent_mode.enabled(state['config']), 'Subagent mode is not enabled')
            result = agent_cleanup.plan(state, observation)
            result.update(journal_seq=seq, journal_digest=previous)
            return result

    def spawn_attempt(self, token, observation=None):
        """Reserve one host call durably; a repeated reservation never permits a retry."""
        with self.locked():
            state, seq, previous = self._load(sync_reports=False)
            require(subagent_mode.enabled(state['config']), 'Subagent mode is not enabled')
            pending = agent_pool.get_pending(state, token)
            require(pending is not None, 'No matching in-flight action')
            if token in state['delegations']:
                return {'status': 'RECOVER_BOUND_AGENT', 'delegation': state['delegations'][token]}
            if state['control'] != 'active':
                return {'status': state['control'].upper()}
            if not agent_pool.request_current(state, pending, snapshot(state['config'])):
                return {'status': 'STALE'}
            history = state.get('spawn_attempts', {}).get(token, [])
            limit = state['config'].get('max_spawn_attempts', 3)
            if history and history[-1]['outcome'] != 'thread_limit':
                return {'status': 'RECOVER_SPAWN', 'attempt': history[-1]}
            if len(history) >= limit:
                return {'status': 'SPAWN_BUDGET_EXHAUSTED', 'attempts_used': len(history), 'limit': limit}
            if history:
                if observation is None:
                    return {'status': 'WAITING_FOR_CAPACITY', 'attempts_used': len(history)}
                require(isinstance(observation, dict) and set(observation) == {
                    'host', 'matching_agent_ids', 'capacity_available', 'capacity_evidence_ref'},
                    'Invalid spawn recovery observation')
                agent_cleanup.plan(state, observation['host'])
                require(observation['host']['observed_at'] >= history[-1]['recorded_at'],
                        'Observe the host after the rejected spawn')
                matches = observation['matching_agent_ids']
                require(isinstance(matches, list) and all(isinstance(x, str) and x.strip() for x in matches),
                        'Record token-matching host identities')
                require(type(observation['capacity_available']) is bool, 'capacity_available must be boolean')
                ref = observation['capacity_evidence_ref']
                require(isinstance(ref, str) and ref.strip(), 'Record capacity evidence')
                if matches:
                    return {'status': 'RECOVER_SPAWN', 'matching_agent_ids': matches}
                if not observation['capacity_available']:
                    return {'status': 'WAITING_FOR_CAPACITY', 'attempts_used': len(history)}
                require(all((item.get('recovery') or {}).get('capacity_evidence_ref') != ref for item in history),
                        'Retry needs new capacity evidence, not a reused observation')
            elif observation is not None:
                raise ContractError('Recovery observation applies only after a thread-limit rejection')
            attempt = {'attempt_id': uuid.uuid4().hex, 'number': len(history) + 1,
                       'outcome': 'reserved', 'reserved_at': time.time(), 'recovery': observation}
            state.setdefault('spawn_attempts', {}).setdefault(token, []).append(attempt)
            self._save(state, 'spawn_reserved', seq, previous, sync_reports=False)
            return {'status': 'SPAWN_RESERVED', 'token': token, 'attempt_id': attempt['attempt_id'],
                    'attempts_used': attempt['number'], 'limit': limit}

    def spawn_result(self, token, result):
        """Record rejected/uncertain host calls, without finishing the work token."""
        require(isinstance(result, dict) and set(result) == {
            'attempt_id', 'error', 'source_ref', 'no_agent_created'}, 'Invalid spawn result fields')
        require(all(isinstance(result[k], str) and result[k].strip()
                    for k in ('attempt_id', 'error', 'source_ref')), 'Record attempt, error and host source')
        require(type(result['no_agent_created']) is bool, 'no_agent_created must be boolean')
        with self.locked():
            state, seq, previous = self._load(sync_reports=False)
            require(subagent_mode.enabled(state['config']), 'Subagent mode is not enabled')
            history = state.get('spawn_attempts', {}).get(token, [])
            attempt = next((x for x in history if x['attempt_id'] == result['attempt_id']), None)
            require(attempt is not None, 'Unknown spawn attempt')
            if 'result' in attempt:
                require(attempt['result'] == result, 'Spawn result already recorded with different evidence')
                return {'status': 'ALREADY_RECORDED', 'outcome': attempt['outcome']}
            require(agent_pool.get_pending(state, token) is not None and attempt is history[-1],
                    'No matching in-flight spawn attempt')
            require(token not in state['delegations'], 'Recover the bound agent instead')
            # Exact known host diagnostic plus explicit host evidence of no creation.
            # Substrings in quoted explanations are not recognized as rejections.
            is_limit = re.fullmatch(r'agent thread limit reached[.!]?', result['error'].strip(), re.I)
            attempt.update(result=copy.deepcopy(result), recorded_at=time.time(),
                           outcome='thread_limit' if is_limit and result['no_agent_created'] else 'uncertain')
            self._save(state, 'spawn_result', seq, previous, sync_reports=False)
            return {'status': 'SPAWN_RESULT_RECORDED', 'outcome': attempt['outcome']}

    def control(self, value, reason):
        require(value in ("paused", "stopped", "active"), "Invalid control")
        require(isinstance(reason, str) and reason.strip(), "Record user instruction/reason")
        with self.locked():
            state, seq, prev = self._load(sync_reports=False)
            require(state["control"] != "stopped" or value == "stopped", "Stopped goal cannot auto-resume; initialize a new authorized goal")
            state["control"] = value
            state["control_reason"] = reason
            self._save(state, "control", seq, prev, sync_reports=False)
            result = {"status": value}
            try:
                self._materialize(state)
            except (OSError, ContractError) as exc:
                result["report_error"] = str(exc)
            return result

    def revise(self, revision, objective, criteria, authority):
        require(all(isinstance(x, str) and x.strip() for x in (revision, objective, authority)), "Revision needs explicit objective and authority")
        require(isinstance(criteria, list) and criteria and all(isinstance(x, str) and x for x in criteria) and len(set(criteria)) == len(criteria), "Invalid success criteria")
        with self.locked():
            state, seq, prev = self._load()
            require(revision != state["config"]["goal_revision"], "Use a new goal revision")
            require(not agent_pool.has_pending(state), "Reconcile in-flight action before revising goal")
            state["config"].update(goal_revision=revision, objective=objective, success_criteria=criteria)
            state["config_digest"] = digest(state["config"])
            state.update(complete=False, clearances={}, review_due=True, review_failures=0)
            subagent_mode.invalidate(state)
            agent_pool.invalidate_external(state)
            state["revision_authority"] = authority
            self._save(state, "goal_revised", seq, prev)
            return {"status": "REVISED", "goal_revision": revision}

    def start_agent(self, token, agent_id, source_ref):
        require(agent_pool.is_pool(self), "start-agent requires agent_pool")
        return agent_pool.start_agent(self, token, agent_id, source_ref)

    def check(self, token):
        if agent_pool.is_pool(self):
            return agent_pool.check(self, token)
        with self.locked():
            state, _, _ = self._load()
            require(state["pending"] and state["pending"]["token"] == token, "No matching in-flight action")
            if state["control"] != "active":
                return {"status": state["control"].upper()}
            if (state["pending"]["snapshot"] != snapshot(state["config"]) or
                    state.get("reviewer_contract") != subagent_mode.reviewer_snapshot(state["config"])):
                return {"status": "STALE"}
            return {"status": "READY"}

    def bind_agent(self, token, agent_id, observation=None):
        if agent_pool.is_pool(self):
            return agent_pool.bind_agent(self, token, agent_id, observation)
        require(observation is None, "Reuse observation requires agent_pool")
        """Record observed native host identity; never spawn or repeat a task."""
        require(isinstance(agent_id, str) and agent_id.strip(), "Agent ID required")
        with self.locked():
            state, seq, previous = self._load()
            require(subagent_mode.enabled(state["config"]), "Subagent mode is not enabled")
            require(state["pending"] and state["pending"]["token"] == token, "No matching in-flight action")
            binding = {"agent_id": agent_id, "role": state["pending"]["role"], "delegation_key": token}
            prior = state["delegations"].get(token)
            if prior:
                require(prior == binding, "Token already bound to another agent")
                return {"status": "ALREADY_BOUND", "delegation": prior}
            require(state["control"] == "active", "Cannot bind new work while paused or stopped")
            require(state["pending"]["snapshot"] == snapshot(state["config"]) and
                    state["reviewer_contract"] == subagent_mode.reviewer_snapshot(state["config"]), "Cannot bind stale request")
            state["delegations"][token] = binding
            self._save(state, "agent_bound", seq, previous)
            return {"status": "BOUND", "delegation": binding}

    def _plan_candidate(self, state, patch):
        """Validate a bounded patch without mutating the journal or loaded state."""
        require(isinstance(patch, dict) and set(patch) == {
            "revision_id", "base_config_digest", "add_actions", "dependencies"}, "Invalid plan patch fields")
        require(isinstance(patch["revision_id"], str) and patch["revision_id"].strip(), "Missing plan revision ID")
        require(patch["base_config_digest"] == state["config_digest"], "Stale plan base")
        require(not agent_pool.has_pending(state), "Reconcile in-flight action before revising plan")
        require(state["control"] != "stopped", "Stopped goal cannot revise plan")
        require(patch["revision_id"] not in state.get("plan_revisions", {}), "Plan revision ID already used")
        additions, dependencies = patch["add_actions"], patch["dependencies"]
        require(isinstance(additions, list) and isinstance(dependencies, dict), "Invalid plan action/dependency lists")
        require(additions or dependencies, "Empty plan patch")
        require(all(isinstance(a, dict) and isinstance(a.get("id"), str) and a["id"] for a in additions), "Invalid added action")
        ids = [a["id"] for a in additions]
        require(len(ids) == len(set(ids)) and not set(ids) & state["actions"].keys(), "Cannot reuse or replace action IDs")
        candidate = copy.deepcopy(state["config"])
        actions = {a["id"]: a for a in candidate["actions"]}

        # Old journals lack an execution index. Derive it from committed requests
        # and results so reconciliation cannot disguise already executed work.
        executed, tokens = set(), {}
        for path in sorted((self.root / "journal").glob("*.json")):
            prior = read_json(path)["state"]
            requests = list(prior.get("pool_pending", {}).values())
            if prior.get("pending"):
                requests.append(prior["pending"])
            for request in requests:
                if request["kind"] != "review":
                    tokens[request["token"]] = request["action_id"]
            result = prior.get("last_result")
            if result and result["token"] in tokens and result["result"].get("status") != "not_started":
                executed.add(tokens[result["token"]])
        changed = set(ids)
        for key, parents in dependencies.items():
            require(key in actions, "Dependency edit must name an existing action")
            require(state["actions"][key] == "pending" and key not in executed, "Cannot rewire executed action")
            require(isinstance(parents, list) and all(isinstance(p, str) for p in parents)
                    and len(parents) == len(set(parents)), "Invalid dependency list")
            require(parents != actions[key].get("depends_on", []), "Unchanged dependency edit")
            actions[key]["depends_on"] = copy.deepcopy(parents)
            changed.add(key)
        for action in additions:
            parents = action.get("depends_on", [])
            require(isinstance(parents, list) and all(isinstance(p, str) for p in parents)
                    and len(parents) == len(set(parents)), "Invalid dependency list")
        candidate["actions"].extend(copy.deepcopy(additions))
        candidate["plan_revision"] = patch["revision_id"]
        candidate = validate_config(candidate)
        affected = set(changed)
        while True:
            expanded = affected | {a["id"] for a in candidate["actions"] if set(a.get("depends_on", [])) & affected}
            if expanded == affected:
                break
            affected = expanded
        return candidate, sorted(affected)

    def authorize_plan(self, patch, scope, authority, rationale):
        """Trusted coordinator operation: record, never infer, actual authority."""
        require(scope in ("existing", "expanded"), "Declare existing or expanded scope")
        require(all(isinstance(x, str) and x.strip() for x in (authority, rationale)), "Plan authority and rationale required")
        with self.locked():
            state, seq, prev = self._load()
            self._plan_candidate(state, patch)
            original = state["config"]["authorization_ref"]
            require((scope == "existing" and authority == original) or
                    (scope == "expanded" and authority != original), "Scope requires matching original or distinct new authority")
            attempts = {}
            for action in state["config"]["actions"]:
                if action.get("kind") == "repair":
                    attempts.setdefault(action["attempt_id"], set()).add(action["attempt_authorization_ref"])
            for action in patch["add_actions"]:
                if action.get("kind") != "repair":
                    continue
                key, reference = action["attempt_id"], action["attempt_authorization_ref"]
                if key in attempts:
                    require(attempts[key] == {reference}, "Existing repair attempt authority must be preserved")
                else:
                    require(scope == "expanded" and reference == authority and
                            all(reference not in refs for refs in attempts.values()), "New repair attempt requires distinct expanded authority")
            value = {"patch_digest": digest(patch), "base_config_digest": state["config_digest"],
                     "scope": scope, "authority": authority, "rationale": rationale, "patch": copy.deepcopy(patch)}
            grants = state.setdefault("plan_authorizations", {})
            key = value["patch_digest"]
            if key in grants:
                require(grants[key] == value, "Conflicting plan authority")
                return {"status": "ALREADY_AUTHORIZED", "patch_digest": key}
            grants[key] = value
            self._save(state, "plan_authorized", seq, prev)
            return {"status": "PLAN_AUTHORIZED", "patch_digest": key, "scope": scope}

    def revise_plan(self, patch):
        with self.locked():
            state, seq, prev = self._load()
            key = digest(patch)
            for record in state.get("plan_revisions", {}).values():
                if record["patch_digest"] == key:
                    return {"status": "ALREADY_REVISED", "revision_id": record["revision_id"]}
            candidate, affected = self._plan_candidate(state, patch)
            grant = state.get("plan_authorizations", {}).get(key)
            require(grant is not None and grant["base_config_digest"] == state["config_digest"], "Exact plan authorization required")
            current = snapshot(candidate)
            evidence_changed = current != state["snapshot"]
            invalidated = sorted(state["clearances"] if evidence_changed else set(affected) & state["clearances"].keys())
            state["clearances"] = {k: v for k, v in state["clearances"].items() if k not in invalidated}
            record = {"revision_id": patch["revision_id"], "patch_digest": key,
                      "before_config_digest": state["config_digest"], "after_config_digest": digest(candidate),
                      "affected_actions": affected, "invalidated_clearances": invalidated,
                      "evidence_changed": evidence_changed, "authorization": copy.deepcopy(grant)}
            state["config"] = candidate
            state["config_digest"] = record["after_config_digest"]
            state["actions"].update({a["id"]: "pending" for a in patch["add_actions"]})
            state.update(snapshot=current, complete=False, review_due=True)
            if evidence_changed:
                subagent_mode.invalidate(state)
            agent_pool.invalidate_external(state)
            # Plan changes cannot replenish failed-review or execution budgets.
            if state["preferred"] in affected:
                state["preferred"] = None
            state.setdefault("plan_revisions", {})[patch["revision_id"]] = record
            self._save(state, "plan_revised", seq, prev)
            return {"status": "PLAN_REVISED", **record}

    def next(self, dispatch_id=None):
        if dispatch_id is not None:
            transition = agent_pool.migrate_for_dispatch(self, dispatch_id)
            if transition is not None:
                return transition
        if agent_pool.is_pool(self):
            return agent_pool.next_request(self, dispatch_id)
        require(dispatch_id is None, "dispatch_id requires agent_pool")
        with self.locked():
            state, seq, prev = self._load()
            unchanged = digest(state)
            if state["control"] != "active":
                return {"status": state["control"].upper()}
            if state["pending"]:
                return {"status": "IN_FLIGHT", "request": state["pending"],
                        "delegation": state.get("delegations", {}).get(state["pending"]["token"])}
            current = snapshot(state["config"])
            contract = subagent_mode.reviewer_snapshot(state["config"])
            if current != state["snapshot"] or contract != state.get("reviewer_contract"):
                state.update(snapshot=current, review_due=True, review_failures=0, complete=False, clearances={})
                if subagent_mode.enabled(state["config"]):
                    state["reviewer_contract"] = contract
                    subagent_mode.invalidate(state)
            if state["complete"]:
                return {"status": "COMPLETE", "review": state["last_review"]}
            if state["dispatches"] >= state["config"].get("max_dispatches", 100):
                if digest(state) != unchanged:
                    self._save(state, "budget_exhausted", seq, prev)
                return {"status": "BUDGET_EXHAUSTED"}
            request = None
            if state["review_due"] and state["review_failures"] < 2:
                request = {"kind": "review", "action_id": None, "command": state["config"].get("reviewer_command"), "timeout_seconds": 60}
            else:
                actions = list(state["config"]["actions"])
                dependency_graph = {a["id"]: a.get("depends_on", []) for a in actions}
                def has_held_premise(key):
                    return key in state["holds"] or any(has_held_premise(parent) for parent in dependency_graph[key])
                actions.sort(key=lambda a: a["id"] != state["preferred"])
                for action in actions:
                    key = action["id"]
                    if state["actions"][key] != "pending" or has_held_premise(key):
                        continue
                    if not all(state["actions"][x] == "done" for x in action.get("depends_on", [])):
                        continue
                    if action.get("requires_review", True) and state["clearances"].get(key) != current["digest"]:
                        continue
                    if not subagent_mode.ready(state, action):
                        continue
                    if action.get("kind") == "repair":
                        attempt = state["attempts"].setdefault(action["attempt_id"], {"cycles": 0, "stopped": False, "candidates": [], "finding_sets": []})
                        if attempt["stopped"] or attempt["cycles"] >= repair_cycle_limit(state["config"]):
                            continue
                    request = {"kind": action.get("kind", "work"), "action_id": key, "instruction": action["instruction"],
                               "command": action.get("command"), "timeout_seconds": action.get("timeout_seconds", 300)}
                    if request["kind"] == "repair":
                        request["finding_signature"] = digest(sorted((k, v["evidence"]) for k, v in state["findings"].items()))
                    break
            if request is None:
                if digest(state) != unchanged:
                    self._save(state, "waiting", seq, prev)
                return {"status": "WAITING", "holds": state["holds"], "review_failures": state["review_failures"],
                        "repair_cycle_limit": repair_cycle_limit(state["config"]), "wake_condition": "Evidence change, authorized reconciliation, or concrete owner decision"}
            request.update(token=uuid.uuid4().hex, goal_revision=state["config"]["goal_revision"], snapshot=current,
                           actions=state["actions"], holds=state["holds"], findings=state["findings"],
                           attempts=state["attempts"], config=state["config"])
            request["semantic_digest"] = digest({key: request[key] for key in ("kind", "action_id", "goal_revision", "snapshot", "actions", "holds", "findings", "attempts", "config")})
            subagent_mode.enrich_request(state, request)
            state["pending"] = copy.deepcopy(request)
            state["dispatches"] += 1
            self._save(state, "dispatched", seq, prev)
            return {"status": "DISPATCH", "request": request}

    def _review(self, state, result, current):
        for name in ("holds", "release_holds", "resolved_findings"):
            require(isinstance(result.get(name, {}), dict), f"{name} must be an object")
        for name in ("cleared_actions", "findings", "verified_criteria", "evidence_refs"):
            require(isinstance(result.get(name, []), list), f"{name} must be a list")
        require(all(isinstance(x, dict) for x in result.get("findings", [])), "findings must contain objects")
        require(result.get("review_status") in ("COMPLETE", "PARTIAL", "FAILED"), "Invalid review status")
        require(result.get("decision") in ("CONTINUE", "REPAIR", "VALIDATE", "HOLD_DEPENDENT_ACTION"), "Invalid review decision")
        require(result.get("snapshot_digest") == state["pending"]["snapshot"]["digest"], "Review must bind requested snapshot")
        require(result.get("request_digest") == state["pending"]["semantic_digest"], "Review must bind the complete request, including goal revision")
        if result["review_status"] == "FAILED":
            state["review_failures"] += 1
            state["review_due"] = state["review_failures"] < 2
            state["clearances"] = {}
            return
        require(type(result.get("goal_complete", False)) is bool, "goal_complete must be boolean")
        actions = {a["id"]: a for a in state["config"]["actions"]}
        cleared = result.get("cleared_actions", [])
        require(isinstance(cleared, list) and set(cleared) <= actions.keys(), "Unknown cleared action")
        require(isinstance(result.get("coverage"), str) and result["coverage"].strip(), "State coverage and limits")
        for key, reason in result.get("holds", {}).items():
            require(key in actions and isinstance(reason, str) and reason.strip(), "Invalid hold")
            state["holds"][key] = reason
        releases = result.get("release_holds", {})
        for key, reason in releases.items():
            require(key in state["holds"] and key in cleared and isinstance(reason, str) and reason.strip(), "Hold release needs checked action and resumption evidence")
            del state["holds"][key]
        require(not (set(cleared) & state["holds"].keys()), "Cannot clear held action")
        for finding in result.get("findings", []):
            require(isinstance(finding.get("id"), str) and finding["id"] and isinstance(finding.get("evidence"), str) and finding["evidence"] and isinstance(finding.get("reason"), str) and finding["reason"], "Finding needs ID, evidence, reason")
            state["findings"][finding["id"]] = finding
        for key, reason in result.get("resolved_findings", {}).items():
            require(key in state["findings"] and isinstance(reason, str) and reason.strip(), "Resolution needs finding and evidence rationale")
            del state["findings"][key]
        preferred = result.get("next_action")
        require(preferred is None or preferred in cleared, "Next action must be explicitly cleared")
        if result["decision"] in ("REPAIR", "VALIDATE"):
            expected = result["decision"].lower()
            require(preferred is not None and actions[preferred].get("kind", "work") == expected, "Decision requires matching next action")
        repair_clearances = [key for key in cleared if actions[key].get("kind") == "repair"]
        require(not repair_clearances or (result["decision"] == "REPAIR" and repair_clearances == [preferred]), "Repair clearance requires REPAIR decision and one next action")
        if result["decision"] == "REPAIR":
            attempt_id = actions[preferred]["attempt_id"]
            attempt = state["attempts"].setdefault(attempt_id, {"cycles": 0, "stopped": False, "candidates": [], "finding_sets": []})
            signature = digest(sorted((k, v["evidence"]) for k, v in state["findings"].items()))
            if signature in attempt["finding_sets"]:
                attempt["stopped"] = True
        subagent_mode.apply_review(state, result, current)
        state["clearances"] = {key: current["digest"] for key in cleared}
        state.update(preferred=preferred, review_due=False, review_failures=0, last_review=result)
        if result.get("goal_complete", False):
            require(result["review_status"] == "COMPLETE", "Partial review cannot complete goal")
            require(preferred is None and not cleared, "Completed goal cannot dispatch more work")
            require(not state["findings"] and not state["holds"], "Unresolved findings/holds prevent completion")
            require(all(state["actions"][a["id"]] == "done" for a in actions.values() if a.get("required", True)), "Required work remains")
            require(set(result.get("verified_criteria", [])) == set(state["config"]["success_criteria"]), "All success criteria need verification")
            require(all(x is not None for x in current["files"].values()), "Required evidence is missing")
            require(result.get("evidence_refs"), "Completion requires evidence references")
            state["complete"] = True

    def finish(self, token, result):
        if agent_pool.is_pool(self):
            return agent_pool.finish(self, token, result)
        require(isinstance(result, dict), "Result must be an object")
        with self.locked():
            state, seq, prev = self._load()
            if token in state["receipts"]:
                require(state["receipts"][token] == digest(result), "Conflicting duplicate result")
                return {"status": "ALREADY_RECORDED"}
            pending = state["pending"]
            require(pending and pending["token"] == token, "No matching in-flight action")
            current = snapshot(state["config"])
            if pending["kind"] == "review":
                contract = subagent_mode.reviewer_snapshot(state["config"])
                if current != pending["snapshot"] or contract != state.get("reviewer_contract"):
                    state.update(snapshot=current, clearances={}, review_due=True, review_failures=0, complete=False)
                    if subagent_mode.enabled(state["config"]):
                        state["reviewer_contract"] = contract
                        subagent_mode.invalidate(state)
                    outcome = "STALE_REVIEW"
                else:
                    self._review(state, result, current)
                    outcome = "RECORDED"
            else:
                require(result.get("status") in ("done", "failed", "uncertain", "not_started"), "Invalid action result")
                if current != pending["snapshot"]:
                    subagent_mode.invalidate(state)
                subagent_mode.work_finished(state, pending, result)
                key = pending["action_id"]
                state["actions"][key] = "pending" if result["status"] == "not_started" else result["status"]
                state.update(snapshot=current, clearances={}, review_due=True, review_failures=0)
                action = next(a for a in state["config"]["actions"] if a["id"] == key)
                if pending["kind"] == "repair" and result["status"] != "not_started":
                    attempt = state["attempts"][action["attempt_id"]]
                    attempt["cycles"] += 1
                    if not attempt["candidates"]:
                        attempt["candidates"].append(pending["snapshot"]["digest"])
                    if current["digest"] in attempt["candidates"]:
                        attempt["stopped"] = True
                    attempt["candidates"].append(current["digest"])
                    attempt["finding_sets"].append(pending["finding_signature"])
                outcome = "RECORDED"
            state["last_result"] = {"token": token, "request_semantic_digest": pending["semantic_digest"], "result": result, "disposition": outcome}
            state["receipts"][token] = digest(result)
            state["pending"] = None
            self._save(state, outcome.lower(), seq, prev)
            return {"status": outcome, "goal_complete": state["complete"]}

    def reconcile(self, action_id, outcome, evidence):
        require(outcome in ("done", "pending") and evidence.strip(), "Supply actual outcome and evidence")
        with self.locked():
            state, seq, prev = self._load()
            require(not agent_pool.has_pending(state), "Finish/reconcile the in-flight token first")
            require(state["actions"].get(action_id) in ("uncertain", "failed"), "Only reconcile uncertain/failed actions")
            state["actions"][action_id] = outcome
            state.update(review_due=True, review_failures=0, clearances={}, complete=False)
            subagent_mode.invalidate(state)
            agent_pool.invalidate_external(state)
            state["reconciliation"] = {"action": action_id, "outcome": outcome, "evidence": evidence}
            agent_pool.record_reconciliation(state, action_id, outcome, evidence)
            self._save(state, "reconciled", seq, prev)
            return {"status": "RECONCILED"}

    def run(self, execute=False, watch_seconds=0):
        require(not agent_pool.is_pool(self), "Pool execution requires an explicit concurrent host adapter; run is serial-only")
        require(execute, "Command execution needs --execute; use next/finish for cooperative work")
        require(0 <= watch_seconds <= 86400, "Invalid watch deadline")
        deadline = time.monotonic() + watch_seconds
        delay = 0.2
        while True:
            item = self.next()
            if item["status"] == "WAITING" and time.monotonic() < deadline:
                time.sleep(min(delay, max(0, deadline - time.monotonic())))
                delay = min(delay * 2, 5)
                continue
            if item["status"] != "DISPATCH":
                return item
            request = item["request"]
            if not request["command"]:
                return {"status": "NEEDS_AGENT", "request": request}
            # Dispatch is persisted before execution. A crash leaves IN_FLIGHT,
            # never an automatic replay of an uncertain side effect.
            readiness = self.check(request["token"])["status"]
            if readiness != "READY":
                if request["kind"] == "review":
                    self.finish(request["token"], {"review_status": "FAILED", "decision": "HOLD_DEPENDENT_ACTION", "snapshot_digest": request["snapshot"]["digest"], "request_digest": request["semantic_digest"]})
                else:
                    self.finish(request["token"], {"status": "not_started"})
                if readiness == "STALE":
                    continue
                return {"status": readiness}
            receipts = self.root / "outputs"
            receipts.mkdir(exist_ok=True)
            stdout = receipts / (request["token"] + ".stdout")
            stderr = receipts / (request["token"] + ".stderr")
            try:
                with stdout.open("wb") as out, stderr.open("wb") as err:
                    process = subprocess.run(request["command"], input=encoded(request), cwd=request["config"]["project_root"], stdout=out, stderr=err,
                                             timeout=request["timeout_seconds"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if request["kind"] == "review":
                    require(process.returncode == 0 and stdout.stat().st_size <= 1024 * 1024, "Reviewer execution failed or output too large")
                    result = read_json(stdout)
                else:
                    result = {"status": "done" if process.returncode == 0 else "failed", "exit_code": process.returncode, "stdout": str(stdout), "stderr": str(stderr)}
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                result = ({"review_status": "FAILED", "decision": "HOLD_DEPENDENT_ACTION", "snapshot_digest": request["snapshot"]["digest"], "request_digest": request["semantic_digest"]}
                          if request["kind"] == "review" else {"status": "uncertain"})
                result["error"] = str(exc)
            write_json(receipts / (request["token"] + ".json"), result)
            try:
                self.finish(request["token"], result)
            except (ContractError, TypeError, KeyError) as exc:
                if request["kind"] != "review":
                    raise
                failure = {"review_status": "FAILED", "decision": "HOLD_DEPENDENT_ACTION", "snapshot_digest": request["snapshot"]["digest"], "request_digest": request["semantic_digest"], "error": str(exc)}
                write_json(receipts / (request["token"] + ".rejected.json"), failure)
                self.finish(request["token"], failure)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="Dedicated project-local controller directory")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init"); init.add_argument("--config", required=True)
    commands.add_parser("status"); nxt = commands.add_parser("next"); nxt.add_argument("--dispatch-id")
    bind = commands.add_parser("bind-agent"); bind.add_argument("--token", required=True); bind.add_argument("--agent-id", required=True); bind.add_argument("--observation")
    start = commands.add_parser("start-agent"); start.add_argument("--token", required=True); start.add_argument("--agent-id", required=True); start.add_argument("--source-ref", required=True)
    spawn = commands.add_parser("spawn-attempt"); spawn.add_argument("--token", required=True); spawn.add_argument("--observation")
    spawned = commands.add_parser("spawn-result"); spawned.add_argument("--token", required=True); spawned.add_argument("--result", required=True)
    cleanup = commands.add_parser("agent-cleanup"); cleanup.add_argument("--observation", required=True)
    check = commands.add_parser("check"); check.add_argument("--token", required=True)
    revise = commands.add_parser("revise"); revise.add_argument("--revision", required=True); revise.add_argument("--objective", required=True); revise.add_argument("--criterion", action="append", required=True); revise.add_argument("--authority", required=True)
    grant = commands.add_parser("authorize-plan"); grant.add_argument("--proposal", required=True); grant.add_argument("--scope", choices=("existing", "expanded"), required=True); grant.add_argument("--authority", required=True); grant.add_argument("--rationale", required=True)
    plan = commands.add_parser("revise-plan"); plan.add_argument("--proposal", required=True)
    finish = commands.add_parser("finish"); finish.add_argument("--token", required=True); finish.add_argument("--result", required=True)
    for command in ("pause", "resume", "stop"):
        sub = commands.add_parser(command); sub.add_argument("--reason", required=True)
    recover = commands.add_parser("reconcile"); recover.add_argument("--action", required=True); recover.add_argument("--outcome", choices=("done", "pending"), required=True); recover.add_argument("--evidence", required=True)
    run = commands.add_parser("run"); run.add_argument("--execute", action="store_true"); run.add_argument("--watch-seconds", type=float, default=0)
    args = parser.parse_args()
    controller = Controller(args.state)
    try:
        if args.command == "init": result = controller.init(read_json(args.config))
        elif args.command == "status": result = controller.status()
        elif args.command == "next": result = controller.next(args.dispatch_id)
        elif args.command == "bind-agent": result = controller.bind_agent(args.token, args.agent_id, read_json(args.observation) if args.observation else None)
        elif args.command == "start-agent": result = controller.start_agent(args.token, args.agent_id, args.source_ref)
        elif args.command == "spawn-attempt": result = controller.spawn_attempt(args.token, read_json(args.observation) if args.observation else None)
        elif args.command == "spawn-result": result = controller.spawn_result(args.token, read_json(args.result))
        elif args.command == "agent-cleanup": result = controller.agent_cleanup(read_json(args.observation))
        elif args.command == "check": result = controller.check(args.token)
        elif args.command == "revise": result = controller.revise(args.revision, args.objective, args.criterion, args.authority)
        elif args.command == "authorize-plan": result = controller.authorize_plan(read_json(args.proposal), args.scope, args.authority, args.rationale)
        elif args.command == "revise-plan": result = controller.revise_plan(read_json(args.proposal))
        elif args.command == "finish": result = controller.finish(args.token, read_json(args.result))
        elif args.command in ("pause", "resume", "stop"): result = controller.control({"pause": "paused", "resume": "active", "stop": "stopped"}[args.command], args.reason)
        elif args.command == "reconcile": result = controller.reconcile(args.action, args.outcome, args.evidence)
        else: result = controller.run(args.execute, args.watch_seconds)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
