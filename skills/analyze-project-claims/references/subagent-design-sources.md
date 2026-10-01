# Subagent design sources and review provenance

This log preserves source provenance from the precursor design/review on
2026-10-01. It records design rationale, not formal map acceptance or proof of
implementation effectiveness. URLs below were inspected during that work; this
packaging pass does not claim to have independently re-fetched them.

## Authoritative architecture guidance

Architecture sources were accessed at 2026-10-01T06:58:49Z.

| ID | Source and inspected sections | Documented guidance and limitation |
| --- | --- | --- |
| S1 | [OpenAI: Orchestration and handoffs](https://developers.openai.com/api/docs/guides/agents/orchestration), orchestration pattern, agents as tools, and adding specialists | A manager can retain ownership while delegating bounded specialist work. SDK guidance does not verify this controller or host. |
| S2 | [OpenAI: Multi-agent](https://developers.openai.com/api/docs/guides/agents-api/multi-agent), when to use subagents and enabling orchestration | Separate contexts support bounded tasks; shared-file writers require coordination. Available host tools and performance must be verified separately. |
| S3 | [OpenAI: Results and state](https://developers.openai.com/api/docs/guides/agents/results), next-turn state and interrupted runs | Continuation carries saved state forward; interrupted execution is not a final result. This does not prove durable host recovery or exactly-once side effects. |
| S4 | [ChatGPT Learn: Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) | Requested `https://developers.openai.com/codex/subagents`, redirected here. Only navigation was extracted; no substantive design claim relies on it. |

S1-S3 were opened and their named substantive sections read. Their requested
and resolved URLs matched. These are paraphrases, not a claim that the guidance
requires every local choice below.

## Project design choices

The baseline durable controller and its workflow supplied the existing token,
review, pause, authority and repair-budget contracts. Their portable successors
are [the controller](../scripts/long_running_controller.py) and
[long-running guide](long-running-mode.md). Reading source alone does not prove
runtime behavior. The following are project design inferences:

| Decision | Rationale sources | Verification obligation |
| --- | --- | --- |
| Coordinator alone commits working claims; bounded worker and reviewer roles | S1, S2, baseline contract | Role permissions and accepted result schema |
| One active token; claims review after each substantive outcome | S1, S2, baseline contract | Ordering, failed/uncertain outcomes and review coverage |
| Persist actual host-agent association and recover before redispatch | S2, S3, baseline contract | Interrupted/unknown outcomes and duplicate dispatch |
| Separate supported premises from affected investigation targets | Baseline evidence rules | Unsupported-premise and premise-free-action tests |
| Derive reports from reviewed journal state without self-citing reports | Baseline controller | Evidence binding, dependent update and regeneration tests |
| Stale/missing review blocks dependent work; reports expose sampled freshness | S3, baseline contract, adverse review cases | Drift, unreadable sources, pending work and historical-completion tests |
| Defer parallel mutation or performance claims | S2, single-writer contract | No parallel speedup or cost/quality advantage has been measured |

## AI Scientist-derived review provenance

The precursor underwent an independent agent review informed by
[The AI Scientist-v2, arXiv 2504.08066v1](https://arxiv.org/html/2504.08066v1)
(2025-04-10), sections 3.2.1-3.2.2 and 4.1-4.2, and the authors'
[pinned README](https://github.com/SakanaAI/AI-Scientist-v2/blob/96bd51617cfdbb494a9fc283af00fe090edfae48/README.md).
The recorded review source access was 2026-10-01. Here `v1` means the first
version of the AI Scientist-v2 paper; it does not name the original AI Scientist
software. SakanaAI software was not executed.

The adopted review method separated stage completion, candidate selection and
scientific evidence, and retained adverse synthetic cases alongside successful
ones. It exposed a stale-report labeling defect despite existing passing tests;
a bounded repair added separate observed freshness without rewriting historical
claim decisions. This is local review history, not a controlled comparison of
review methods or evidence that this mode improves scientific discovery.

## Validation boundary

The precursor local installed controller completed a bounded native worker,
claims-review and report-update cycle after the freshness repair. Private raw
logs, host IDs and machine-specific paths are deliberately not redistributed.
That result remains precursor evidence, not a fresh activation test of this
packaged port. Repository tests cover their synthetic cases only. A current
package/host claim still needs actual invocation under its active source hashes.

Review request hashes bind declared source files, the configured reviewer guides,
and executed controller/module bytes. They do not authenticate the reviewer,
prove a cited location supports a claim, or detect activation of a different
skill at a new path. Host observation and semantic inspection remain required.
Neither these sources nor a passing structural test grants formal evidence
acceptance, general reliability, scientific benefit or publication eligibility.
