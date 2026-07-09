#!/usr/bin/env python3
"""Render the clinical review packet for physician sign-off.

Program-aided by design: every value is read from the LIVE knowledge base and
gold set at generation time, so the packet can never drift from the code the
way a hand-written document would. Regenerate after any change:

    make review-packet     # writes docs/CLINICAL_REVIEW_PACKET.md (blank template)

Review workflow: the physician marks each item ACCEPT or MODIFY(with change),
edits land as normal versioned changes (RULESET_VERSION bump + export regen +
gold updates), and the sign-off block at the end is filled in. approval_status
then flips from DRAFT to physician-reviewed, with scope stated honestly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from attending import knowledge as K  # noqa: E402

OUT = REPO / "docs" / "CLINICAL_REVIEW_PACKET.md"

# Curated by the build process: the judgment calls most deserving of expert
# attention, with the reasoning that produced them. Everything else in the
# packet is closer to guideline transcription.
HIGH_ATTENTION = [
    ("RF-DKA requirement group", "Insulin was REMOVED as a triage-time "
     "requirement (K+ must precede insulin); confirmatory labs (glucose/BMP/VBG) "
     "are the required group. Confirm this matches your practice."),
    ("RF-SAH requirement group", "Lumbar puncture was REMOVED as a stand-alone "
     "satisfier; non-contrast CT head is the required first action. LP is a "
     "post-CT decision."),
    ("RF-PREG-ABD requirement groups", "type_and_screen was REMOVED as a "
     "satisfier (it alone cleared the workup pre-0.3.0); now requires "
     "beta-hCG AND pelvic ultrasound."),
    ("RF-SUICIDE requirement groups", "Two groups: means-safety "
     "(1:1/sitter/safety search) AND psych evaluation. Confirm both are "
     "hard triage requirements in your model."),
    ("Severe pain >= 7/10 -> ESI 2", "Straight from ESI v4 Decision B, but the "
     "highest false-positive risk in real traffic. Confirm or add modifiers."),
    ("Adult danger zone HR>100 / RR>20 / SpO2<92", "ESI v4 danger-zone table; "
     "up-triages resource-based ESI 3 to ESI 2 when present."),
    ("Peds bands: neonate & infant share the ESI '<3 mo' thresholds",
     "A stricter PALS-based neonate split is a deliberate open decision."),
    ("Life-saving thresholds (Decision A)", "GCS<=8, SpO2<90, RR>=40 or <=8, "
     "SBP<80, HR>=150 -> ESI 1. HR>=150 will catch stable SVT: acceptable "
     "over-triage or add a perfusion modifier?"),
    ("Discharge-word list gates BLOCK severity", "Incomplete red-flag workup "
     "blocks only when disposition releases the patient (discharge/fast-track/"
     "lobby...); otherwise it WARNs. Confirm that boundary."),
]


def _rf_section() -> list[str]:
    lines = ["## 2. Red flags (Decision B -> ESI 2 floors)", ""]
    for rf in K.RED_FLAGS:
        groups = K.normalize_requires(rf["requires_orders"])
        req = "  AND  ".join("(" + " OR ".join(g) + ")" for g in groups)
        lines += [
            f"### {rf['id']} — {rf['label']}",
            f"- **Triggers (regex):** `{'` · `'.join(rf['patterns'])}`",
            f"- **ESI floor:** {rf['esi_floor']}",
            f"- **Required workup:** {req}",
            f"- **Citation:** {K.CITATIONS.get(rf['citation'], rf['citation'])}",
            f"- **Rationale:** {rf['rationale']}",
            "- [ ] ACCEPT   [ ] MODIFY: ____________________",
            "",
        ]
    return lines


def _vitals_sections() -> list[str]:
    lines = ["## 3. Danger-zone vitals (Decision D up-triage)", "",
             f"- **Adult (>18y):** HR>{K.DANGER_ZONE_ADULT['hr_gt']}, "
             f"RR>{K.DANGER_ZONE_ADULT['rr_gt']}, "
             f"SpO2<{K.DANGER_ZONE_ADULT['spo2_lt']}",
             "- [ ] ACCEPT   [ ] MODIFY: ____________________", ""]
    for age_max, band in sorted(K.DANGER_ZONE_PEDS.items()):
        lines += [f"- **{band.get('label', age_max)}:** HR>{band['hr_gt']}, "
                  f"RR>{band['rr_gt']}, SpO2<{band['spo2_lt']}  "
                  f"(cite: {band.get('citation', 'ESI')})",
                  "  - [ ] ACCEPT   [ ] MODIFY: ____________________"]
    lines += ["", "## 4. Life-saving thresholds (Decision A -> ESI 1)", ""]
    for key, (label, cite) in K.LIFE_SAVING_VITALS.items():
        lines += [f"- `{key}`: {label} (cite: {cite})",
                  "  - [ ] ACCEPT   [ ] MODIFY: ____________________"]
    lines += ["", f"- **Phrase triggers:** {', '.join(sorted(K.LIFE_SAVING_PHRASES))}",
              "  - [ ] ACCEPT   [ ] MODIFY: ____________________", ""]
    lines += ["## 5. Physiologic plausibility envelope (quarantine bounds)", ""]
    for attr, (lo, hi, unit) in K.VITAL_PLAUSIBLE_RANGES.items():
        lines.append(f"- {attr}: [{lo}, {hi}] {unit}")
    lines += ["- [ ] ACCEPT ALL   [ ] MODIFY: ____________________", ""]
    lines += ["## 6. Resource estimates (Decision C)", "",
              "| complaint keywords | min-max resources |", "|---|---|"]
    for kws, lo, hi in K.RESOURCE_ESTIMATES:
        lines.append(f"| {', '.join(kws[:4])}{'…' if len(kws) > 4 else ''} | {lo}-{hi} |")
    lines += [f"| (default) | {K.RESOURCE_DEFAULT[0]}-{K.RESOURCE_DEFAULT[1]} |",
              "", "- [ ] ACCEPT ALL   [ ] MODIFY: ____________________", ""]
    return lines


def _gold_section() -> list[str]:
    lines = ["## 7. Gold set (every case = a supervised scenario + expected verdict)", ""]
    for raw in (REPO / "evaluation" / "goldset.jsonl").read_text().splitlines():
        if not raw.strip():
            continue
        c = json.loads(raw)
        e, p, x = c["encounter"], c.get("proposed", {}), c.get("expect", {})
        vit = ", ".join(f"{k} {v}" for k, v in (e.get("vitals") or {}).items())
        exp = x.get("decision")
        exp = "/".join(exp) if isinstance(exp, list) else exp
        crit = f" [{x['criterion']}]" if x.get("criterion") else ""
        esi = f" -> rec ESI {x['recommended_esi']}" if x.get("recommended_esi") else ""
        lines += [
            f"### {c['id']}",
            f"- {c.get('note', '')}",
            f"- **Pt:** {e.get('age_years')}y — {e.get('chief_complaint')} | {vit}",
            f"- **Agent proposed:** ESI {p.get('esi_level')}, "
            f"orders {p.get('orders')}, dispo {p.get('disposition')}",
            f"- **Expected:** {exp}{esi}{crit}",
            "- [ ] ACCEPT   [ ] MODIFY: ____________________",
            "",
        ]
    return lines


def main() -> int:
    completed = sorted((REPO / "docs" / "reviews").glob("*.md"))
    lines = [
        "# Clinical review packet — Attending  (BLANK TEMPLATE)",
        "",
        "> **This is the unfilled review template for the NEXT review round,**",
        "> regenerated from live code so it can never drift. Completed, dated",
        "> review records live in `docs/reviews/`"
        + (f" — latest: `{completed[-1].relative_to(REPO)}`." if completed else "."),
        "",
        f"*Generated from live code. Ruleset `{K.RULESET_VERSION}` · status: "
        f"{K.APPROVAL_STATUS}*",
        "",
        "**How to review:** mark each item ACCEPT or MODIFY (say what changes). "
        "Modifications land as versioned changes (RULESET_VERSION bump, export "
        "regen, gold-set updates), then the sign-off block below is completed "
        "and `approval_status` flips to physician-reviewed.",
        "",
        "## 1. High-attention items (the builder's judgment calls)",
        "",
    ]
    for title, why in HIGH_ATTENTION:
        lines += [f"- **{title}** — {why}",
                  "  - [ ] ACCEPT   [ ] MODIFY: ____________________"]
    lines.append("")
    lines += _rf_section()
    lines += _vitals_sections()
    lines += _gold_section()
    lines += [
        "## 8. Sign-off",
        "",
        "- Reviewer: ______________________  (name, credentials)",
        "- Date: ______________",
        "- Scope: single-physician review for hackathon demonstration; NOT a "
        "hospital governance/board approval; NOT a clinical deployment release.",
        "- Items modified: ____ (listed above)   Items accepted: ____",
        "",
    ]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT} ({len(lines)} lines, ruleset {K.RULESET_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
