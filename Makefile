# Attending — fail-closed supervising layer for clinical triage agents.
#
# Prefers the project venv interpreter (.venv/bin/python) when it exists,
# otherwise falls back to system python3 (core is stdlib-only, so tests and
# the goldset gate run without any install; lint/typecheck need dev deps).

VENV_PY := $(wildcard .venv/bin/python)
PY      := $(if $(VENV_PY),$(VENV_PY),python3)

.PHONY: install test lint format typecheck goldset smoke check demo demo-live serve mutation coverage review-packet counts

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -e ".[dev,llm]" ruff mypy

# Falls back to system python3 if .venv is absent (core has zero runtime deps;
# pytest must be importable by whichever interpreter is selected).
test:
	PYTHONPATH=src $(PY) -m pytest -q

lint:
	$(PY) -m ruff check src tests scripts

format:
	$(PY) -m ruff format src tests

typecheck:
	$(PY) -m mypy src/attending

# Safety gate: synthetic gold set (physician-reviewed; board governance pending). Exits 1 on ANY false-negative.
goldset:
	PYTHONPATH=src $(PY) -m attending.evaluate
	PYTHONPATH=src $(PY) -m attending.evaluate_coverage

# CLI exit code doubles as a gate: 0 allow, 2 block, 3 escalate.
# The chest-pain undertriage example MUST be blocked, so expect exit 2.
smoke:
	PYTHONPATH=src $(PY) -m attending.cli examples/chest_pain_undertriage.json; \
	rc=$$?; \
	if [ $$rc -ne 2 ]; then echo "smoke: expected BLOCK (exit 2), got exit $$rc"; exit 1; \
	else echo "smoke: BLOCK verdict as expected (exit 2)"; fi

# The two-surface demo: one encounter, decision + communication, fail-closed.
# Replay is a pure function of the fixture (rehearsable, byte-identical).
demo:
	PYTHONPATH=src $(PY) -m attending.demo

# Same choreography, drafts from the live performer (ATTENDING_MODEL; needs key).
demo-live:
	PYTHONPATH=src $(PY) -m attending.demo --live

# Day-of API gateway (FastAPI over the supervised loop). Needs the gateway
# extra: .venv/bin/python -m pip install -e ".[gateway]"
serve:
	PYTHONPATH=src $(PY) -m attending.gateway

# Evidence-count drift guard: every count in the evidence docs must match
# reality (pytest collection, mutation GATES, goldset, adversarial suite).
counts:
	$(PY) scripts/evidence_counts.py --check

# Prove every communication gate is load-bearing: disable each in turn and
# demand test failures, then a green clean run. The stage claim as a command.
mutation:
	$(PY) scripts/mutation_check.py

coverage:
	PYTHONPATH=src $(PY) -m pytest -q --cov=attending --cov=sitrep --cov-report=term-missing

# Regenerate the physician sign-off packet from LIVE code (never hand-edit).
review-packet:
	$(PY) scripts/clinical_review_packet.py

# mutation (23 fault-injected mechanisms) runs as its own target — minutes, not seconds —
# and is REQUIRED in CI; check is the fast local gate.
check: lint typecheck test goldset counts
