# Saturday — Abridge × Anthropic × Lightspeed (3-minute script)

**Stats up top (say these, sourced):**
- Medicare Advantage insurers made ~50M prior-auth determinations in 2023;
  ~3.2M denied. **Only 11.7% of denials were appealed — and 81.7% of appeals
  were fully or partially overturned** (KFF, 2023 data).
- Medicaid managed care denies at **12.5%** — more than double MA's rate —
  and its appeal overturn rate is just **36%**, with no automatic external
  review in most states (HHS OIG, OEI-09-19-00350).
- Translation: the appeal that almost nobody files usually wins. The blocker
  is drafting labor and vague denials — exactly what an agent can do, and
  exactly where an unsupervised agent is dangerous.

**Beat 1 — the vague denial (30s).** Open the hosted replay, Act 3. A real-
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

**Sources:** KFF, "Nearly 50 Million Prior Authorization Requests…" (2023
data, publ. 2025) — kff.org; HHS OIG, "High Rates of Prior Authorization
Denials…" OEI-09-19-00350 (2023) — oig.hhs.gov. Numbers verified 2026-07-11.

**Offline insurance:** everything above is the deterministic replay
(goatnote-inc.github.io/abridge or `make demo`); the playground presets
(vague denial / unsupported claim / auto-deny) run against the local gateway
(`make serve`). Zero API calls required on stage.
