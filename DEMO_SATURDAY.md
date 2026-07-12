# Saturday — Abridge × Anthropic × Lightspeed (3-minute script)

**Stats up top (25s — say these, sourced):**
- Medicare Advantage insurers made **52.8M** prior-auth determinations in
  2024; **4.1M denied (7.7%)**. **Only 11.5% of denials were appealed — and
  80.7% of appeals were overturned** (KFF, 2024 data, published Jan 2026).
  Denial rates spread 3x by insurer (UnitedHealth 12.8% vs Elevance 4.2%).
- Medicaid managed care denies at **12.5%** — more than double MA's rate —
  and its appeal overturn rate is just **36%**, with no automatic external
  review in most states (HHS OIG, OEI-09-19-00350; 2019 data, 2023 report).
- Translation: the appeal that almost nobody files usually wins. The blocker
  is drafting labor and vague denials — exactly what an agent can do, and
  exactly where an unsupervised agent is dangerous.

**Beat 1 — the vague denial (30s).** Open the hosted replay with `?present`
appended (projector type), Act 3. A real-
shaped denial letter: "not medically necessary," no criteria cited. Attending
audits it as a determination: **BLOCK on four gate families at once** — no
resolvable citation (F15), deny outcome (F16), authority not in the pack
(F17), no provenance (F18). "The letter fails the same gates our own agent
has to pass."

**Beat 2 — the supervised appeal (45s).** The agent drafts an appeal. First
draft carries one unsupported claim — withheld, finding names it. Revision
ships: every claim cites a criteria clause **[SLT-01]** and an exact quote
from the clinical note. Click the citations. "Nothing in this letter is
uncited; the engine located every quote."

**Beat 3 — the F14 moment (30s).** Mode B toggle: same criteria run forward —
instant, fully cited **approval**. Then the auto-deny attempt: the code
**raises `PhysicianSignoffRequired`** live. "Approvals can be instant.
Denials structurally require a physician's sign-off token — this demo cannot
produce one, because we never wrote a way to skip it. There is no override
parameter."

**Beat 4 — same chassis (30s).** Flip to Acts 1-2: the same loop supervising
triage drafts for the RN and every patient-facing message (care board,
disclosure gap, RN acknowledgment). "Three surfaces, one verdict vocabulary,
one fail-closed loop. We extended the chassis, not built a new vehicle."

**Close (15s).** "Criteria pack is versioned, hashed, and labeled DRAFT
pending physician review — sign-off flips the label through the same review
flow the triage rules went through. 260 tests, 22 mutation targets all
load-bearing, FN=0 enforced in CI."

*Beats total 2:55 against a 3:00 slot. If running over in rehearsal, cut
the insurer-spread sentence from the stats block first, then Beat 4's
quoted line.*

**Vocabulary for this room:** say "confabulation" (Abridge's term); the
quote-anchored citations are the same instinct as their Linked Evidence —
made deterministic and fail-closed; the OpenEvidence/Nature-Medicine fight
this week is the "validation gap" — the reason our next eval round is a
sealed, independently-authored held-out set (evaluation/heldout/).

**Sources:** KFF, "Medicare Advantage Insurers Made Nearly 53 Million Prior
Authorization Determinations in 2024" (publ. 2026-01-28) — kff.org; HHS OIG
OEI-09-19-00350 (2019 data, 2023 report) — oig.hhs.gov; CMS-0057-F, 89 FR
8758; CA SB 1120; TX SB 815; CMS WISeR CMS-5056-N. Verified 2026-07-12.

**Offline insurance:** everything above is the deterministic replay
(goatnote-inc.github.io/abridge or `make demo`); the playground presets
(vague denial / unsupported claim / auto-deny) run against the local gateway
(`make serve`). Zero API calls required on stage.
