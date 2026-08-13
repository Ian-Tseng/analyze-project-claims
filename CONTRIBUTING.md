# Contributing

Thanks for helping improve `analyze-project-claims`.

## Before opening an issue

Search existing issues and verify the problem against the latest release.
Public issues are appropriate for ordinary bugs, documentation, and bounded
feature proposals. Follow [SECURITY.md](SECURITY.md) for vulnerabilities and do
not disclose security details publicly.

Do not include private repositories, project artifacts, prompts, credentials,
raw logs, or personal data. Reduce examples to synthetic content whenever
possible.

## Development

The installable skill and its deterministic helpers use the Python standard
library. From the repository root, run:

```powershell
py -3 -m unittest discover -s tests -v
```

Use `python3` instead of `py -3` on macOS or Linux.

For package changes, keep these synchronized:

- `VERSION`;
- `CITATION.cff`;
- `skills/analyze-project-claims/references/package-version.json`;
- `skills/analyze-project-claims/references/package-manifest.json`.

Rebuild and verify the manifest using the commands in [PUBLISHING.md](PUBLISHING.md).
Do not rewrite append-only validation or component-map history.

## Pull requests

Keep each pull request focused. Explain the user-visible behavior, risks, and
evidence. Add a failing regression test before a defect fix and update public
documentation when behavior changes. All matrix CI jobs must pass before a
release.

By contributing, you agree that your contribution is licensed under the
repository's [MIT License](LICENSE).
