"""The clinical reasoning graph is a deterministic read model.

These tests pin the invariants that let the graph carry references into an LLM's
context safely: it is byte-identical across runs, it builds with NO LLM path (so
it can never disagree with the spine), every entity that must be grounded carries
a reference, and every edge connects real nodes. The chest-pain undertriage case
is the worked example — the same case the smoke test blocks.
"""

import inspect
import json

from attending import graph as graph_mod
from attending.cli import main
from attending.encounter import Encounter, ProposedTriage, Vitals
from attending.esi import compute_esi
from attending.graph import EDGE_RELS, NODE_KINDS, build_graph
from attending.knowledge import CITATIONS


def _enc(cc, **v):
    vit = Vitals(**{k: v[k] for k in v if k in Vitals.__dataclass_fields__})
    return Encounter(encounter_id="T", chief_complaint=cc,
                     age_years=v.get("age_years", 58), sex="male", vitals=vit)


def _chest_pain():
    enc = _enc("Chest pressure radiating to left arm", hr=96, spo2=97, sbp=148)
    proposed = ProposedTriage(esi_level=3, orders=("cbc", "bmp"),
                              disposition="fast_track",
                              rationale="likely musculoskeletal")
    return enc, proposed


# --- Structural invariants ---

def test_builds_with_no_llm_path():
    """The graph module must not reach the LLM: it is program-aided, so a graph
    built into a judge's context can never disagree with the deterministic
    spine it summarizes (charter: no safety-shaped work on an LLM path)."""
    src = inspect.getsource(graph_mod)
    assert "import llm" not in src and "from .llm" not in src
    assert ".llm" not in src


def test_deterministic():
    enc, proposed = _chest_pain()
    a = build_graph(enc, proposed).to_dict()
    b = build_graph(enc, proposed).to_dict()
    assert a == b
    # And independent of whether the caller pre-computed the assessment.
    c = build_graph(enc, proposed, compute_esi(enc)).to_dict()
    assert a == c


def test_node_kinds_and_edge_rels_are_closed_vocab():
    enc, proposed = _chest_pain()
    g = build_graph(enc, proposed)
    assert all(n.kind in NODE_KINDS for n in g.nodes)
    assert all(e.rel in EDGE_RELS for e in g.edges)


def test_edges_reference_existing_nodes():
    enc, proposed = _chest_pain()
    g = build_graph(enc, proposed)
    ids = {n.id for n in g.nodes}
    for e in g.edges:
        assert e.src in ids, f"dangling edge src {e.src}"
        assert e.dst in ids, f"dangling edge dst {e.dst}"


def test_node_ids_unique():
    enc, proposed = _chest_pain()
    g = build_graph(enc, proposed)
    ids = [n.id for n in g.nodes]
    assert len(ids) == len(set(ids))


# --- Grounding: the reference invariant, made structural ---

def test_red_flag_symptom_and_citation_nodes_carry_a_reference():
    enc, proposed = _chest_pain()
    g = build_graph(enc, proposed)
    for n in g.nodes:
        if n.kind in ("red_flag", "symptom", "citation"):
            assert n.ref, f"{n.kind} node {n.id} has no grounding reference"


def test_citation_nodes_resolve_to_the_knowledge_base():
    enc, proposed = _chest_pain()
    g = build_graph(enc, proposed)
    cites = [n for n in g.nodes if n.kind == "citation"]
    assert cites
    for n in cites:
        assert n.ref == CITATIONS.get(n.attrs["key"], n.attrs["key"])


# --- Worked example: chest-pain undertriage ---

def test_chest_pain_graph_shows_ignored_acs_workup():
    enc, proposed = _chest_pain()
    g = build_graph(enc, proposed)
    by_id = {n.id: n for n in g.nodes}
    assert "red_flag:RF-ACS" in by_id
    # ACS requires ecg + troponin; neither was ordered (cbc/bmp were).
    assert "order:ecg" in by_id and "order:troponin" in by_id
    requires = [e for e in g.edges
                if e.src == "red_flag:RF-ACS" and e.rel == "requires"]
    assert requires and all("NOT ordered" in e.because for e in requires)
    # The anchoring proxy: the proposal ignores a fired red flag entirely.
    assert any(e.rel == "ignores" and e.dst == "red_flag:RF-ACS"
               for e in g.edges)


def test_context_surfaces_citation_and_evidence_span():
    enc, proposed = _chest_pain()
    ctx = build_graph(enc, proposed).to_context()
    assert "CLINICAL REASONING GRAPH" in ctx
    assert CITATIONS["ACS"] in ctx           # the guideline reference is present
    assert "chief_complaint[" in ctx         # the evidence span is present
    assert "--requires-->" in ctx and "--cites-->" in ctx


# --- Vitals: danger-zone and quarantine surface on the graph ---

def test_danger_zone_vital_raises_acuity():
    enc = _enc("cough", hr=118, rr=24, spo2=90, age_years=40)
    g = build_graph(enc, ProposedTriage(esi_level=4))
    assert any(e.rel == "raises_acuity" and e.src.startswith("vital:")
               for e in g.edges)


def test_implausible_vital_is_marked_quarantined():
    enc = _enc("cough", hr=400, age_years=40)
    g = build_graph(enc, ProposedTriage(esi_level=4))
    hr = next(n for n in g.nodes if n.id == "vital:hr")
    assert "quarantined" in hr.attrs["state"]


# --- Surfaces ---

def test_cli_graph_flag_emits_nodes_and_edges(capsys):
    rc = main(["examples/chest_pain_undertriage.json", "--graph", "--json"])
    assert rc == 2  # still a BLOCK; the flag is additive
    out = json.loads(capsys.readouterr().out)
    assert "reasoning_graph" in out
    assert out["reasoning_graph"]["nodes"] and out["reasoning_graph"]["edges"]


def test_llm_graph_context_is_injectable_without_network():
    """The context helper the judge prompts use builds offline and carries the
    references (this is the 'pass references into context' seam)."""
    from attending.llm import _graph_context
    enc, proposed = _chest_pain()
    ctx = _graph_context(enc, proposed)
    assert "CLINICAL REASONING GRAPH" in ctx
    assert "RF-ACS" in ctx
