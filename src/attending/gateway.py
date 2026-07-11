"""Day-of API gateway: the supervised control loop over HTTP.

A thin FastAPI wrapper around Attending's two surfaces so a hackathon
front-end (or an EHR-side caller) can drive the screener without importing
Python. Endpoints:

    GET  /health               liveness + package version
    POST /supervise/triage     single-shot screener verdict over one proposal
    POST /loop/triage          the full propose -> verify -> revise loop
    POST /supervise/rendering  communication-surface verdict over one rendering
    GET  /demo                 the frozen two-surface demo transcript (replay)
    /ui                        static front-end, mounted only if web/ exists

FastAPI/uvicorn are a LAZY optional dependency (the ``gateway`` extra):
importing this module never imports them; ``create_app()`` raises
``GatewayUnavailable`` when they are missing. There is deliberately no
module-level ``app`` — run ``main()`` (behind ``make serve``) or call
``create_app()`` yourself.

Fail-closed at the HTTP edge too: a malformed encounter/chart is a 400 (422
for a non-object body) with a clear message, never a 200 carrying a guessed
verdict — and chart vocabulary is validated strictly, because a typo'd flag
or a stringly-typed boolean would silently disarm a gate rather than trip it
(``"discussed": "false"`` must not suppress the disclosure gap). Nothing here
mutates the gold set or fixtures; ``/demo`` replays the frozen fixture
read-only.

Live mode (``/loop/triage`` with ``{"performer": "live"}``, ``/demo?live=1``)
routes drafting through the live performer in ``attending.agent`` and needs
ANTHROPIC_API_KEY (see ``attending.llm``); without a key the performer returns
None and the loop fails closed to a human. The default is always scripted.
"""

# NOTE: no `from __future__ import annotations` in this module — FastAPI must
# evaluate handler annotations at runtime, and stringified annotations cannot
# resolve names scoped inside create_app().

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from sitrep.gates import Rendering
from sitrep.state import EncounterState, Order, Result

from . import __version__, agent
from .cli import _verdict_to_dict
from .comms import supervise_rendering
from .demo import (
    _DEFAULT_FIXTURE,
    _comms_verdict_dict,
    _scripted_proposer,
    _triage_result_dict,
    run_demo,
)
from .encounter import Encounter, ProposedTriage, encounter_from_dict, proposed_from_dict
from .loop import ProposeFn, run_triage_loop
from .supervisor import supervise

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WEB_DIR = _REPO_ROOT / "web"

_INSTALL_HINT = (
    "install the gateway extra: pip install 'attending[gateway]' "
    "(or: python -m pip install fastapi uvicorn)"
)


class GatewayUnavailable(RuntimeError):
    """The gateway extra (fastapi + uvicorn) is not installed."""


# --- edge validation (fastapi-free, importable/testable anywhere) -------------
#
# The core converters are deliberately forgiving (real intake is incomplete;
# a missing field is a safety SIGNAL). The HTTP edge is not: wrong *types* are
# client bugs, and screening garbage as if it were a chart would produce a
# guessed verdict. Every ValueError below is returned as HTTP 400.

_ENCOUNTER_STR_KEYS = ("chief_complaint", "transcript", "history", "sex", "arrival_mode")
_AUDIENCES = ("patient", "nurse", "physician", "consultant")
_ORDER_STATUSES = {"in-progress", "completed", "cancelled"}
_RESULT_FLAGS = {"pending", "normal", "abnormal", "critical"}
_RESULT_STATUSES = {"preliminary", "final", "amended"}
_RESULT_BOOL_KEYS = ("released", "viewed", "discussed")


def _require_object(body: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in body:
        raise ValueError(f"missing required key '{key}'")
    val = body[key]
    if not isinstance(val, dict):
        raise ValueError(f"'{key}' must be a JSON object, got {type(val).__name__}")
    return val


def _object_list(container: dict[str, Any], key: str) -> list[dict[str, Any]]:
    val = container.get(key, [])
    if not isinstance(val, list) or not all(isinstance(x, dict) for x in val):
        raise ValueError(f"'{key}' must be a list of JSON objects")
    return val


def _string_list(container: dict[str, Any], key: str) -> list[str]:
    val = container.get(key, [])
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise ValueError(f"'{key}' must be a list of strings")
    return val


def _build_encounter(payload: dict[str, Any]) -> Encounter:
    """dict -> Encounter; ValueError on shapes that would corrupt the screen."""

    def bad(msg: str) -> ValueError:
        return ValueError(f"malformed encounter: {msg}")

    for key in _ENCOUNTER_STR_KEYS:
        if payload.get(key) is not None and not isinstance(payload[key], str):
            raise bad(f"'{key}' must be a string")
    age = payload.get("age_years")
    if age is not None and not isinstance(age, (int, float)):
        raise bad("'age_years' must be a number")
    vitals = payload.get("vitals")
    if vitals is not None and not isinstance(vitals, dict):
        raise bad("'vitals' must be an object of vital-sign readings")
    for name, reading in (vitals or {}).items():
        if reading is not None and not isinstance(reading, (int, float)):
            raise bad(f"vitals.{name} must be numeric, got {type(reading).__name__}")
    facts = payload.get("structured_facts")
    if facts is not None and not isinstance(facts, dict):
        raise bad("'structured_facts' must be an object")
    try:
        return encounter_from_dict(payload)
    except Exception as exc:
        raise bad(str(exc)) from exc


def _build_proposed(payload: dict[str, Any]) -> ProposedTriage:
    """dict -> ProposedTriage; ValueError on malformed proposals.

    An empty dict is VALID (no acuity proposed) and the supervisor escalates
    it (ATT-000) — that is the fail-closed semantic, not a client error.
    """

    def bad(msg: str) -> ValueError:
        return ValueError(f"malformed proposal: {msg}")

    esi = payload.get("esi_level")
    if esi is not None and (not isinstance(esi, int) or isinstance(esi, bool)
                        or esi not in (1, 2, 3, 4, 5)):
        raise bad("'esi_level' must be an integer 1..5 (or null for no acuity)")
    orders = payload.get("orders")
    if orders is not None and not isinstance(orders, list):
        raise bad("'orders' must be a list of order-name strings")
    for order in orders or []:
        if not isinstance(order, str):
            raise bad(f"order names must be strings, got {type(order).__name__}")
    for key in ("disposition", "rationale"):
        if payload.get(key) is not None and not isinstance(payload[key], str):
            raise bad(f"'{key}' must be a string")
    try:
        return proposed_from_dict(payload)
    except Exception as exc:
        raise bad(str(exc)) from exc


def _build_state(
    orders: list[dict[str, Any]],
    results: list[dict[str, Any]],
    escalations: list[str],
) -> EncounterState:
    """Chart -> EncounterState, in ingestion order: orders, results, escalations.

    Vocabulary is validated strictly: an off-vocabulary flag/status or a
    non-boolean lifecycle field would silently disarm a safety gate rather
    than trip it, which is the fail-open direction.
    """
    state = EncounterState()
    for i, o in enumerate(orders):
        where = f"chart.orders[{i}]"
        oid, name = o.get("id"), o.get("name")
        if not isinstance(oid, str) or not oid:
            raise ValueError(f"{where}: 'id' must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise ValueError(f"{where}: 'name' must be a non-empty string")
        status = o.get("status", "in-progress")
        if status not in _ORDER_STATUSES:
            raise ValueError(f"{where}: status {status!r} not in {sorted(_ORDER_STATUSES)}")
        state.add_order(Order(id=oid, name=name, status=status))
    for i, r in enumerate(results):
        where = f"chart.results[{i}]"
        for key in ("id", "order_id", "name"):
            if not isinstance(r.get(key), str) or not r.get(key):
                raise ValueError(f"{where}: '{key}' must be a non-empty string")
        flag = r.get("flag", "pending")
        if flag not in _RESULT_FLAGS:
            raise ValueError(f"{where}: flag {flag!r} not in {sorted(_RESULT_FLAGS)}")
        status = r.get("status", "preliminary")
        if status not in _RESULT_STATUSES:
            raise ValueError(f"{where}: status {status!r} not in {sorted(_RESULT_STATUSES)}")
        for key in _RESULT_BOOL_KEYS:
            if not isinstance(r.get(key, False), bool):
                raise ValueError(f"{where}: '{key}' must be a boolean")
        try:
            state.add_result(Result(
                id=r["id"], order_id=r["order_id"], name=r["name"],
                value=str(r.get("value", "")), flag=flag, status=status,
                released=r.get("released", False),
                viewed=r.get("viewed", False),
                discussed=r.get("discussed", False),
            ))
        except ValueError as exc:  # orphan result — rejected at ingestion (INV-H)
            raise ValueError(f"{where}: {exc}") from exc
    for reason in escalations:
        state.escalate(reason)
    return state


def _rendering_request(body: dict[str, Any]) -> tuple[Rendering, EncounterState]:
    audience = body.get("audience")
    if not isinstance(audience, str) or audience not in _AUDIENCES:
        # An unknown audience would silently bypass every patient-pane gate —
        # that is fail-open, so it is rejected rather than screened leniently.
        raise ValueError(f"'audience' must be one of {list(_AUDIENCES)}")
    text = body.get("text")
    if not isinstance(text, str):
        raise ValueError("'text' must be a string")
    refs = _string_list(body, "refs")
    chart = body.get("chart", {})
    if not isinstance(chart, dict):
        raise ValueError(f"'chart' must be a JSON object, got {type(chart).__name__}")
    state = _build_state(
        _object_list(chart, "orders"),
        _object_list(chart, "results"),
        _string_list(chart, "escalations"),
    )
    return Rendering(audience=audience, text=text, refs=refs), state


def _loop_request(
    body: dict[str, Any],
) -> tuple[Encounter, list[dict[str, Any]], str, "int | None"]:
    enc = _build_encounter(_require_object(body, "encounter"))
    drafts = _object_list(body, "drafts")
    for i, draft in enumerate(drafts):
        try:
            _build_proposed(draft)  # validate eagerly: malformed drafts 400 up front
        except ValueError as exc:
            raise ValueError(f"drafts[{i}]: {exc}") from exc
    performer = body.get("performer", "scripted")
    if performer not in ("scripted", "live"):
        raise ValueError("'performer' must be 'scripted' or 'live'")
    if performer == "scripted" and not drafts:
        raise ValueError("scripted performer requires at least one entry in 'drafts'")
    cap = body.get("max_revisions")
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int)
                            or not 0 <= cap <= 10):
        raise ValueError("'max_revisions' must be an integer 0..10")
    return enc, drafts, performer, cap


# --- the app -------------------------------------------------------------------


def create_app() -> Any:
    """Build the FastAPI app. Raises GatewayUnavailable when fastapi is absent.

    fastapi is imported dynamically (importlib) so this module imports — and
    mypy stays green — in environments without the ``gateway`` extra.
    """
    try:
        fastapi = importlib.import_module("fastapi")
        staticfiles = importlib.import_module("fastapi.staticfiles")
    except ImportError as exc:
        raise GatewayUnavailable(f"fastapi is not installed — {_INSTALL_HINT}") from exc

    HTTPException = fastapi.HTTPException

    # DEMO-ONLY surface: no authN/authZ/rate-limiting (hackathon threat model,
    # mirroring HealthCraft's MCP HTTP note) — do not expose beyond the demo box.
    app = fastapi.FastAPI(
        title="Attending Gateway",
        version=__version__,
        description="Fail-closed supervised control loop for clinical triage agents, over HTTP.",
    )

    def _bad_request(exc: Exception) -> Any:
        return HTTPException(status_code=400, detail=str(exc))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/supervise/triage")
    def post_supervise_triage(body: dict[str, Any]) -> dict[str, Any]:
        """The pure screener: one fail-closed verdict over {"encounter", "proposed"}."""
        try:
            enc = _build_encounter(_require_object(body, "encounter"))
            proposed = _build_proposed(_require_object(body, "proposed"))
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return _verdict_to_dict(supervise(enc, proposed))

    @app.post("/loop/triage")
    def post_loop_triage(body: dict[str, Any]) -> dict[str, Any]:
        """propose -> verify -> revise -> ship-or-escalate.

        Body: {"encounter": {...}, "drafts": [{...}, ...]}. The default
        performer is "scripted": it replays ``drafts`` in order (the
        demo._scripted_proposer pattern) with max_revisions = len(drafts) so
        every supplied draft gets its turn; exhaustion fails closed.
        {"performer": "live"} swaps in agent.propose_triage — requires
        ANTHROPIC_API_KEY; ``drafts`` is then ignored (default cap: 2).
        """
        try:
            enc, drafts, performer, cap = _loop_request(body)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        propose: ProposeFn
        if performer == "live":
            propose = agent.propose_triage
            max_revisions = 2 if cap is None else cap
        else:
            propose = _scripted_proposer(drafts)
            max_revisions = len(drafts) if cap is None else cap
        return _triage_result_dict(run_triage_loop(enc, propose, max_revisions=max_revisions))

    @app.post("/supervise/rendering")
    def post_supervise_rendering(body: dict[str, Any]) -> dict[str, Any]:
        """Communication-surface verdict: the sitrep gates over one rendering.

        Body: {"audience", "text", "refs": [...], "chart": {"orders": [...],
        "results": [...], "escalations": [...]}}. The chart is rebuilt into an
        EncounterState so state-level gates (disclosure gap, escalation
        persistence) run alongside the text gates.
        """
        try:
            rendering, state = _rendering_request(body)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return _comms_verdict_dict(supervise_rendering(rendering, state))

    @app.get("/demo")
    def get_demo(live: bool = False) -> dict[str, Any]:
        """The two-surface demo transcript. Replay by default (a pure function
        of the frozen fixture); ``?live=1`` drafts via the live performer
        and needs ANTHROPIC_API_KEY. Read-only in both modes."""
        try:
            fixture = json.loads(_DEFAULT_FIXTURE.read_text())
            return run_demo(fixture, live=live)
        except Exception as exc:  # a failed demo must be an error, not a partial 200
            raise HTTPException(status_code=500, detail=f"demo failed: {exc}") from exc

    # Static front-end (built by a sibling agent). Mounted only when present —
    # the API surface must not depend on it.
    if _WEB_DIR.is_dir():
        app.mount("/ui", staticfiles.StaticFiles(directory=str(_WEB_DIR), html=True), name="ui")

    return app


def main(argv: list[str] | None = None) -> int:
    """Run the gateway under uvicorn — the entry point behind ``make serve``."""
    ap = argparse.ArgumentParser(prog="attending-gateway", description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)
    try:
        uvicorn = importlib.import_module("uvicorn")
    except ImportError:
        print(f"attending-gateway: uvicorn is not installed — {_INSTALL_HINT}", file=sys.stderr)
        return 1
    try:
        app = create_app()
    except GatewayUnavailable as exc:
        print(f"attending-gateway: {exc}", file=sys.stderr)
        return 1
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
