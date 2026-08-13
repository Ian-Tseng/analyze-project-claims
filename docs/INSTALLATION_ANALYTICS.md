# Privacy-Bounded Installation Analytics

This optional architecture estimates active, consenting installations. It does not measure GitHub downloads,
repository clones, unique people, total users, or
all installations.

No analytics endpoint is bundled or currently claimed as deployed. The feature
is inactive until the owner deploys the API, supplies scoped credentials, and a
user explicitly enables a reviewed endpoint.

```text
user opts in
  -> client creates a random installation UUID locally
  -> no event is sent during enablement
  -> later explicit check-in sends one bounded activation/version event
  -> owner API authenticates and rate-limits it
  -> server stores only a keyed hash of the installation UUID
  -> owner reads aggregate consenting-installation counts
```

## What the metric means

The owner summary metric is
`unique_consenting_activated_installations`. One installation is counted after
its first successful `activated` event and remains one installation across
later version changes until it is erased or ages out under retention.

The metric can undercount because consent is optional, delivery can fail, and
inactive records expire. It can overstate people because one person can use
multiple installations. Reinstallation, copied state, bot use, and shared
machines further limit interpretation. Use the phrase `unique consenting activated installations`
observed by the configured service, not unique people.

## Data contract

Each event contains exactly:

- schema version;
- random event UUID;
- product name and SemVer;
- random installation UUID;
- `activated` or `version_changed`;
- UTC event time.

It contains no project content, findings, prompts, logs, paths, host
diagnostics, GitHub identity, email, IP field, update policy, or problem-report
data. The local policy stores the random installation UUID but never stores an
API token. The service HMAC-hashes installation identity with an owner-held key
before database storage and exposes only aggregate counts to the admin route.

Transport infrastructure may still observe network metadata such as source IP
addresses. Production proxy logs must be minimized, access-controlled, and
covered by the owner's privacy and retention notice.

Review the machine contracts in:

- `skills/analyze-project-claims/references/installation-analytics-event.schema.json`;
- `skills/analyze-project-claims/references/installation-analytics-policy.schema.json`.

## User controls

Nothing is sent by default. `prompt` records only that the choice was shown;
`enable` creates local identity but still sends nothing. `check-in` performs
the first network event. `disable` stops future events without promising
remote deletion. `erase` requests principal-scoped remote deletion and clears
local identity only after the service confirms it.

For an owner-configured deployment:

```powershell
$env:ANALYZE_PROJECT_CLAIMS_ANALYTICS_TOKEN = "<scoped-client-token>"
py -3 .\skills\analyze-project-claims\scripts\installation_analytics.py `
  enable --endpoint https://analytics.example.com/v1/analytics/events

py -3 .\skills\analyze-project-claims\scripts\installation_analytics.py preview
py -3 .\skills\analyze-project-claims\scripts\installation_analytics.py check-in
py -3 .\skills\analyze-project-claims\scripts\installation_analytics.py status
py -3 .\skills\analyze-project-claims\scripts\installation_analytics.py disable
py -3 .\skills\analyze-project-claims\scripts\installation_analytics.py erase
```

Update consent and problem-report consent do not enable analytics. Do not infer
analytics consent from installing, updating, invoking, or reporting a problem.

## Owner API setup

Use distinct high-entropy client and admin tokens and a separate random HMAC
key. Run the service as a dedicated OS account and give it a dedicated state
directory; the reference service rejects symlinked storage and enforces
owner-only POSIX directory and database modes. Store only token hashes in
configuration:

```powershell
$env:ANALYTICS_CLIENT_TOKEN = "<generated-client-token>"
$env:ANALYTICS_ADMIN_TOKEN = "<different-admin-token>"
$env:ANALYTICS_API_TOKEN_HASHES = py -3 -c "import hashlib,os; print(hashlib.sha256(os.environ['ANALYTICS_CLIENT_TOKEN'].encode()).hexdigest())"
$env:ANALYTICS_ADMIN_TOKEN_HASH = py -3 -c "import hashlib,os; print(hashlib.sha256(os.environ['ANALYTICS_ADMIN_TOKEN'].encode()).hexdigest())"
$env:ANALYTICS_ID_HASH_KEY = "<independent-random-key-at-least-32-characters>"

py -3 .\analytics_service\server.py `
  --host 127.0.0.1 `
  --port 8081 `
  --database .\.analytics-service-state\installation-analytics.sqlite3 `
  --retention-days 365
```

The API provides:

| Method and path | Access | Purpose |
|---|---|---|
| `POST /v1/analytics/events` | scoped client | Validate and deduplicate one event |
| `POST /v1/analytics/erasures` | same scoped client | Delete that principal's installation |
| `GET /v1/analytics/summary` | admin | Read aggregate totals and version counts |
| `GET /healthz` | public | Liveness only |

Loopback HTTP is for tests only. Production requires HTTPS termination, a
private service bind, proxy rate limits, the built-in pre-authentication and
principal write limits, encrypted persistent storage, backups, monitoring,
explicit retention, minimized logs, token/key
rotation, and a published privacy contact. A shared client credential is
suitable only for a controlled cohort; a broad public rollout needs an abuse-
resistant credential issuance and rotation design before deployment.

## Validation and evidence limits

Run:

```powershell
py -3 -m unittest discover -s tests -p "test_installation_analytics.py" -v
py -3 -m unittest discover -s tests -p "test_analytics_service.py" -v
```

These tests cover consent state, exact schemas, no-send enablement, retry
identity, erasure, authentication, keyed identity storage, aggregation,
deduplication, and retention on a local service. They do not establish a live
deployment, notification delivery, privacy-law compliance, public abuse
resistance, or a real-world user count.
