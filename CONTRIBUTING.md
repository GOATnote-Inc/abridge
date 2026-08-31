# Contributing

Attending is solo-maintained; issues and small PRs are welcome.

- Setup: `pip install -e ".[dev]"`, then `make check` — ruff, mypy, the full
  test suite, the gold-set FN=0 gate, the mutation harness (`make mutation`),
  and the evidence-count drift guard must all be green.
- Fail-closed is the house rule: "not evaluated" must never read as "safe".
  A new gate ships with the test that proves disabling it fails.
- Synthetic data only — never commit anything derived from a real patient
  record, and never commit `.env` or keys.
- Counts in README/docs are CI-guarded (`scripts/evidence_counts.py --check`);
  regenerate rather than hand-edit.

Security reports: see [SECURITY.md](SECURITY.md).
