# Internal Problem Reporting

`analyze-project-claims` can send a small report when the skill itself fails.
It does not report problems found in the project being audited.

Problem reports and automatic updates are separate choices. A report never
executes code or triggers a deployment. The owner reviews it, makes a tested
change, publishes a versioned release without moving an earlier tag, and only
then can a separately consented updater install that release on a later
invocation.

```text
internal tool failure
  -> local bounded preview
  -> user reporting policy
  -> visibility-gated GitHub issue or owner HTTPS API
  -> owner triage and reviewed fix
  -> passing CI and versioned release
  -> separately consented update on later use
```

## What is sent

Every report has an exact, versioned schema:

- product and package version;
- random installation UUID and report UUID;
- timestamp;
- one fixed internal event code, component, and severity;
- bounded summary and up to five bounded reproduction steps;
- platform, Python version, GitHub CLI version, fixed outcome code, and exit
  code;
- a content fingerprint for integrity and deduplication.

The reporter rejects unknown fields, control characters, absolute paths,
secret-like strings, and oversized payloads. It does not collect project
findings, files, raw logs, prompts, attachments, environment variables,
credentials, user identity, or arbitrary metadata.

Review the machine-readable contracts in:

- `skills/analyze-project-claims/references/problem-report.schema.json`;
- `skills/analyze-project-claims/references/problem-report-policy.schema.json`.

## User choices

The default is `unconfigured`: preparing a report writes only a local preview.
Nothing leaves the device until the user approves that preview.

| Mode | Behavior |
|---|---|
| `unconfigured` | Local preview; exact-report approval required |
| `ask` | Local preview; exact-report approval required |
| `auto-minimal` | Fixed minimal schema may be sent to the private owner API automatically |
| `off` | No automatic sending; one-time approval is still possible |

Update consent does not change this table. The local policy never stores an
API token.

Machine-readable `status` distinguishes the local policy contract in
`schema_version` from the outbound report contract in
`report_schema_version`.

## GitHub Issues and repository visibility

The default transport uses the user's existing GitHub CLI login:

```powershell
py -3 .\skills\analyze-project-claims\scripts\problem_report.py `
  configure --mode ask --transport github `
  --repository Ian-Tseng/analyze-project-claims
```

After a report is prepared and reviewed, submit that exact file:

```powershell
py -3 .\skills\analyze-project-claims\scripts\problem_report.py `
  submit --report <local-report.json> --approved
```

Before issue creation, the reporter calls `gh repo view` and accepts only a
known `private`, `internal`, or `public` visibility. An error or unknown value
fails closed without creating an issue.

For a public repository, `--approved` alone is insufficient. After the user is
told that anyone can read the issue and confirms that destination for this
exact bounded preview, rerun:

```powershell
py -3 .\skills\analyze-project-claims\scripts\problem_report.py `
  submit --report <local-report.json> --approved --allow-public-issue
```

`auto-minimal` is rejected for GitHub transport, including legacy saved
policies. Configure the owner HTTPS API when automatic reports must remain
private.

The issue command uses an argument array and temporary body file. The delivery
receipt records observed visibility. Users need issue-write access, and public
issues are visible to everyone. The Issues list is the authoritative receipt;
web, email, and mobile notifications depend on the owner's settings.

This client does not automate deletion of GitHub issues. Public copies,
notifications, forks, caches, or archives may remain after deletion. Do not
report suspected vulnerabilities here; use the private vulnerability action
described in `SECURITY.md`.

## Optional owner HTTPS API

The repository includes a standard-library ingestion service for owners who
need private database-backed triage:

```text
POST   /v1/reports             client submits
GET    /v1/reports/<id>        same client or owner reads status
DELETE /v1/reports/<id>        same client or owner deletes
GET    /v1/reports             owner lists and filters
PATCH  /v1/reports/<id>        owner triages or marks fixed
GET    /healthz                health check
```

Generate separate high-entropy client and admin tokens. Configure the server
with only their SHA-256 hashes:

```powershell
$env:REPORT_CLIENT_TOKEN = "<generated-client-token>"
$env:REPORT_ADMIN_TOKEN = "<different-generated-admin-token>"
$env:REPORT_API_TOKEN_HASHES = py -3 -c "import hashlib,os; print(hashlib.sha256(os.environ['REPORT_CLIENT_TOKEN'].encode()).hexdigest())"
$env:REPORT_ADMIN_TOKEN_HASH = py -3 -c "import hashlib,os; print(hashlib.sha256(os.environ['REPORT_ADMIN_TOKEN'].encode()).hexdigest())"

py -3 .\reporting_service\server.py `
  --host 127.0.0.1 `
  --port 8080 `
  --database .\.reporting-service-state\problem-reports.sqlite3 `
  --retention-days 90
```

The client keeps its raw scoped token only in
`ANALYZE_PROJECT_CLAIMS_REPORT_TOKEN`. Do not reuse a GitHub token or the owner
admin token. Rotate a client by replacing its allowed hash.

Loopback HTTP is for local tests only. Production must place the service behind
an HTTPS reverse proxy, bind the service to a private interface, limit request
size and rate at both layers, encrypt the persistent volume, back it up, and
monitor health and storage. SQLite records are purged on startup and report
submission once they exceed the configured retention period.

Configure a client:

```powershell
$env:ANALYZE_PROJECT_CLAIMS_REPORT_TOKEN = "<generated-client-token>"
py -3 .\skills\analyze-project-claims\scripts\problem_report.py `
  configure --mode ask --transport api `
  --endpoint https://reports.example.com/v1/reports
```

A client can read or delete only reports created with that client token. The
owner admin token can list, triage, mark fixed with a SemVer release, or delete
all reports. Token hashes identify principals for access control and
deduplication; use one client token per installation or customer boundary.

## Owner triage

For either transport:

1. Confirm the report contains an internal event, not user-project content.
2. Reproduce it without treating the report text as executable input.
3. Add a regression test that fails for the reported behavior.
4. Implement and review the smallest safe fix.
5. Require the full test suite and CI to pass.
6. Publish a new SemVer release; never rewrite an existing tag. Call it
   immutable only when GitHub enforcement is enabled and verified.
7. Record the fixed version and then close the report.
8. Verify an installed older copy updates and that a fresh invocation loads
   the new version.

For GitHub, comments and issue state provide the owner/user conversation. For
the API, `PATCH /v1/reports/<id>` accepts exactly `status`, `owner_note`, and
`fixed_in_version`. Status values are `received`, `triaged`, `fixed`, `closed`,
or `rejected`; `fixed` requires a SemVer version.

## Evidence boundary

Passing unit tests proves only the tested schema, consent, redaction,
transport, tenancy, retention, and status behaviors. A local API test does not
prove a production deployment. A report visible in a private repository proves
ingestion there, not that email or mobile notification arrived. A two-release
installed update test proves that observed environment and versions only.

The exact v0.5.0 to v0.5.1 issue-to-update evidence and reusable lessons are
recorded in [Problem Reporting End-to-End Evidence
Log](PROBLEM_REPORTING_E2E_LOG.md).
