"""Clinical reasoning graph — the encounter's evidence as nodes + edges.

Attending already reasons over references (a red flag cites a guideline, a
finding quotes an evidence span, the ESI tree records a decision point), but
those references live in parallel lists on the assessment. This module folds
them into ONE typed graph: nodes are clinical entities (complaint, symptom,
vital, red flag, ESI decision, required order, citation, proposal), edges are
the *why* that connects them (``evidences``, ``requires``, ``cites``,
``raises_acuity``, ``ignores``).

The graph is a **read model**: it is built deterministically FROM the ESI
assessment (``build_graph`` runs no LLM and makes no safety decision — the
spine in ``esi.py`` / ``supervisor.py`` is untouched). Its job is to carry the
encounter's references INTO context so a screener judge reasons over structure
instead of raw prose (``to_context``), and to give a connecting judge / auditor
a navigable evidence trail (``to_dict`` -> {"nodes": [...], "edges": [...]}).

Every red-flag node carries its citation reference and every symptom node its
evidence span, so "which fact, backed by which guideline, drove which decision"
is answerable by walking edges — the grounding invariant, made structural.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import knowledge as K
from .encounter import Encounter, ProposedTriage
from .esi import EsiAssessment, compute_esi

# Node kinds and edge relations are a small, closed vocabulary so the context
# rendering and any downstream consumer can rely on them.
NODE_KINDS = (
    "encounter", "complaint", "symptom", "vital",
    "red_flag", "esi_decision", "order", "citation", "proposal",
)
EDGE_RELS = (
    "presents", "evidences", "raises_acuity", "requires",
    "cites", "orders", "ignores",
)


@dataclass(frozen=True)
class Node:
    """One clinical entity. ``ref`` is the grounding reference (a citation
    string, an evidence span, or a captured value) — never empty for the
    entities that must be grounded (red flags, symptoms, citations)."""

    id: str
    kind: str
    label: str
    ref: str = ""
    attrs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    """A directed, typed relation. ``because`` is the human-readable reason
    the edge exists (the reasoning step it encodes)."""

    src: str
    dst: str
    rel: str
    because: str = ""


@dataclass(frozen=True)
class ReasoningGraph:
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]

    def to_dict(self) -> dict:
        """JSON-serializable {"nodes": [...], "edges": [...]} — the artifact a
        connecting judge / auditor pulls."""
        return {
            "nodes": [
                {"id": n.id, "kind": n.kind, "label": n.label,
                 "ref": n.ref, "attrs": n.attrs}
                for n in self.nodes
            ],
            "edges": [
                {"src": e.src, "dst": e.dst, "rel": e.rel, "because": e.because}
                for e in self.edges
            ],
        }

    def to_context(self) -> str:
        """Compact nodes+edges block for LLM context. References are surfaced
        in [brackets] so the judge can reason over — and cite — them."""
        lines = ["CLINICAL REASONING GRAPH (deterministic; references in [brackets])",
                 "NODES:"]
        for n in self.nodes:
            ref = f"  [ref: {n.ref}]" if n.ref else ""
            lines.append(f"  ({n.kind}) {n.label}{ref}")
        lines.append("EDGES:")
        for e in self.edges:
            because = f"  — {e.because}" if e.because else ""
            src = _label_of(self.nodes, e.src)
            dst = _label_of(self.nodes, e.dst)
            lines.append(f"  {src} --{e.rel}--> {dst}{because}")
        return "\n".join(lines)


def _label_of(nodes: tuple[Node, ...], node_id: str) -> str:
    for n in nodes:
        if n.id == node_id:
            return n.label
    return node_id


def _canonical_order(group: tuple[str, ...]) -> str:
    """Stable display/id name for a requirement group (its first member)."""
    return group[0].lower()


def build_graph(
    enc: Encounter,
    proposed: ProposedTriage,
    assessment: EsiAssessment | None = None,
) -> ReasoningGraph:
    """Fold an encounter + its ESI assessment + the proposal into a reasoning
    graph. Pure and deterministic: no LLM, no I/O. If ``assessment`` is not
    supplied it is re-derived with the deterministic ``compute_esi`` — so the
    graph never disagrees with the spine it describes.
    """
    if assessment is None:
        assessment = compute_esi(enc)

    nodes: list[Node] = []
    edges: list[Edge] = []
    seen: set[str] = set()

    def add_node(node: Node) -> None:
        if node.id not in seen:
            seen.add(node.id)
            nodes.append(node)

    # --- Encounter root + chief complaint. ---
    demo = ", ".join(
        p for p in (
            f"{enc.age_years:g}y" if enc.age_years is not None else "",
            enc.sex or "",
            (enc.arrival_mode or "").replace("_", " "),
        ) if p
    )
    add_node(Node("encounter", "encounter", f"Encounter {enc.encounter_id}"
                  + (f" ({demo})" if demo else ""),
                  attrs={"encounter_id": enc.encounter_id}))
    if enc.chief_complaint:
        add_node(Node("complaint", "complaint", enc.chief_complaint,
                      ref="chief_complaint"))
        edges.append(Edge("encounter", "complaint", "presents"))

    # --- Captured vitals (the grounded numeric facts a grounding judge needs).
    quarantined = set(assessment.quarantined_vitals)
    for attr, val in enc.vitals.present().items():
        vid = f"vital:{attr}"
        state = "quarantined (implausible)" if attr in quarantined else "captured"
        add_node(Node(vid, "vital", f"{attr.upper()} {val:g}",
                      ref=f"vitals.{attr}",
                      attrs={"attr": attr, "value": val, "state": state}))
        edges.append(Edge("encounter", vid, "presents", because=state))

    # --- ESI decision node (Attending's independent acuity). ---
    add_node(Node("esi", "esi_decision",
                  f"Attending ESI {assessment.level} (Decision {assessment.decision_point})",
                  ref=K.CITATIONS.get("ESI", "ESI"),
                  attrs={"level": assessment.level,
                         "decision_point": assessment.decision_point}))

    # --- Danger-zone vitals raise acuity. ---
    for dz in assessment.danger_zone:
        # dz reads like "HR 118 > 100"; link the corresponding vital if present.
        attr = dz.split(" ", 1)[0].lower()
        vid = f"vital:{attr}"
        if vid in seen:
            edges.append(Edge(vid, "esi", "raises_acuity", because=dz))

    # --- Red flags: symptom -> red_flag -> {citation, required orders, esi}. ---
    proposed_orders = set(proposed.orders_lower)
    for rf in assessment.red_flags:
        rid = f"red_flag:{rf.id}"
        add_node(Node(rid, "red_flag", f"{rf.id}: {rf.label}",
                      ref=rf.evidence_ref,
                      attrs={"id": rf.id, "esi_floor": rf.esi_floor,
                             "rationale": rf.rationale}))
        # Symptom node = the exact source text that triggered the flag.
        sid = f"symptom:{rf.id}"
        add_node(Node(sid, "symptom", f'"{rf.matched}"', ref=rf.evidence_ref,
                      attrs={"source": rf.source, "span": list(rf.span or ())}))
        edges.append(Edge("encounter", sid, "presents"))
        edges.append(Edge(sid, rid, "evidences",
                          because=f"matched in {rf.source or 'record'}"))
        edges.append(Edge(rid, "esi", "raises_acuity",
                          because=f"red-flag floor ESI {rf.esi_floor}"))
        # Citation node (the guideline reference behind the flag).
        cid = f"citation:{rf.citation}"
        add_node(Node(cid, "citation", rf.citation,
                      ref=K.CITATIONS.get(rf.citation, rf.citation),
                      attrs={"key": rf.citation}))
        edges.append(Edge(rid, cid, "cites"))
        # Required workup: one node per requirement group, marked satisfied/not.
        for group in rf.requires_orders:
            canon = _canonical_order(group)
            oid = f"order:{canon}"
            satisfied = bool(proposed_orders & {o.lower() for o in group})
            add_node(Node(oid, "order", canon,
                          attrs={"required_by": [], "aliases": list(group)}))
            edges.append(Edge(rid, oid, "requires",
                              because="ordered" if satisfied else "NOT ordered"))

    # --- Proposal node + what it actually ordered. ---
    if (proposed.esi_level is not None or proposed.orders
            or proposed.disposition or proposed.rationale):
        plabel = "; ".join(
            p for p in (
                f"proposed ESI {proposed.esi_level}"
                if proposed.esi_level is not None else "no acuity proposed",
                f"disposition {proposed.disposition}" if proposed.disposition else "",
            ) if p
        )
        add_node(Node("proposal", "proposal", plabel,
                      ref="proposal.rationale" if proposed.rationale else "",
                      attrs={"esi_level": proposed.esi_level,
                             "disposition": proposed.disposition,
                             "orders": list(proposed.orders_lower),
                             "rationale": proposed.rationale}))
        for o in proposed.orders_lower:
            oid = f"order:{o}"
            add_node(Node(oid, "order", o, attrs={"aliases": [o]}))
            edges.append(Edge("proposal", oid, "orders"))

        # Anchoring proxy (deterministic, descriptive): a fired red flag with
        # ZERO of its required workup engaged is one the proposal ignored.
        for rf in assessment.red_flags:
            engaged = any(
                proposed_orders & {o.lower() for o in group}
                for group in rf.requires_orders
            )
            if not engaged:
                edges.append(Edge("proposal", f"red_flag:{rf.id}", "ignores",
                                  because="no required workup ordered"))

    return ReasoningGraph(nodes=tuple(nodes), edges=tuple(edges))
