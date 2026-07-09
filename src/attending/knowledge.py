"""Clinical knowledge base for Attending's independent triage assessment.

Program-aided, not model-guessed: the ESI v4 decision tree, danger-zone
vitals, red-flag lexicon, and resource estimates live here as inspectable
data with citations. Everything is versioned and carries an approval_status
so a hospital board / department can sign off on the exact ruleset in use
(Brandon's "pending hospital board approved algorithm" requirement).

ALL rule VALUES below are DRAFT pending physician / hospital board review.
Thresholds are taken at guideline level (not invented); the exact
criterion->page mapping and any local tightening are board decisions.

Sources (guideline level; exact criterion->page mapping pending board review):
  ESI     Emergency Severity Index Implementation Handbook v4 (AHRQ / ENA)
  ACS     ACEP Clinical Policy: Suspected Non-ST-Elevation ACS, Ann Emerg Med 2018
  STROKE  AHA/ASA Guidelines for Early Management of Acute Ischemic Stroke, 2019
  SEPSIS  Surviving Sepsis Campaign International Guidelines, 2021
  SI/HI   Joint Commission NPSG 15.01.01 (suicide risk)
  ANAPH   AAAAI/ACAAI Anaphylaxis Practice Parameter, 2020
  DISSECT 2022 ACC/AHA Guideline for Diagnosis and Management of Aortic Disease
  SAH     ACEP Clinical Policy: Acute Headache, Ann Emerg Med 2019
  GIB     ACG Clinical Guideline: Upper GI and Ulcer Bleeding, 2021
  DKA     ADA/EASD consensus report: Hyperglycemic Crises in Adults, 2024
  FN-ONC  IDSA Clinical Practice Guideline: Fever and Neutropenia, 2010 (+ASCO 2018)
  CAUDA   ACEP Clinical Policy: Acute Low Back Pain / NASS cauda equina guidance
  EYE     AAO Preferred Practice Patterns (chemical injury / acute vision loss)
  SICKLE  ASH 2020 Sickle Cell Disease Guidelines (acute pain); NHLBI 2014
  PREE    ACOG Practice Bulletin 222: Gestational Hypertension & Preeclampsia, 2020
  PALS    AHA Pediatric Advanced Life Support vital-sign reference (2020)

Optional externalization: if `configs/knowledge.json` exists at the repo root
and its `ruleset_version` matches RULESET_VERSION, its values REPLACE the
in-module defaults (single reviewable artifact for a board). Any mismatch or
parse problem falls back silently to the in-module data — the code never
fails open because a config file is stale or broken.
"""

from __future__ import annotations

import json
from pathlib import Path

RULESET_VERSION = "esi-v4-attending-0.2.1"
APPROVAL_STATUS = "DRAFT — pending physician / hospital board sign-off"

# --- Danger-zone vitals (ESI Decision Point D). Adult (> 18 yr) thresholds. ---
# Presence of any of these up-triages a resource-based ESI 3 to ESI 2.
DANGER_ZONE_ADULT = {
    "hr_gt": 100,     # tachycardia
    "rr_gt": 20,      # tachypnea
    "spo2_lt": 92,    # hypoxia
}

# Age-banded pediatric danger-zone vitals.
# Values are the ESI v4 Handbook danger-zone table (HR/RR bands, SaO2 < 92%),
# with named bands (neonate/infant/toddler/child/adolescent) for auditability.
# Neonate and infant currently share the ESI "<3 months" thresholds; a stricter
# PALS-based neonate split is a board decision (PALS cited for band naming).
# DRAFT — pending physician/board review.
# Shape: {age_max_years: {"hr_gt", "rr_gt", "spo2_lt", ...}} — consumed by
# esi._danger_zone, which reads only hr_gt / rr_gt / spo2_lt.
DANGER_ZONE_PEDS = {
    0.083: {"label": "neonate (0-1 mo)", "hr_gt": 180, "rr_gt": 50,
            "spo2_lt": 92, "citation": "ESI"},   # ESI <3 mo band; PALS naming
    0.25: {"label": "infant (1-3 mo)", "hr_gt": 180, "rr_gt": 50,
           "spo2_lt": 92, "citation": "ESI"},
    3.0: {"label": "toddler (3 mo-3 yr)", "hr_gt": 160, "rr_gt": 40,
          "spo2_lt": 92, "citation": "ESI"},
    8.0: {"label": "child (3-8 yr)", "hr_gt": 140, "rr_gt": 30,
          "spo2_lt": 92, "citation": "ESI"},
    18.0: {"label": "adolescent (8-18 yr)", "hr_gt": 100, "rr_gt": 20,
           "spo2_lt": 92, "citation": "ESI"},    # ESI ">8 yr" == adult values
}

# --- Physiologic plausibility envelope (shared constant). ---
# Single source of truth for "is this captured vital compatible with a living
# ED patient?". esi.py uses it to QUARANTINE implausible values out of the
# life-saving / danger-zone computations (an impossible HR must not fabricate
# an ESI 1); detectors/transcription_error.py applies the same bounds to fire
# an ESCALATE for re-measurement. Values must stay in sync with that detector.
# Shape: attr -> (hard_min, hard_max, unit).
VITAL_PLAUSIBLE_RANGES = {
    "hr": (20, 300, "bpm"),
    "rr": (3, 80, "/min"),
    "spo2": (40, 100, "%"),
    "sbp": (40, 300, "mmHg"),
    "dbp": (15, 200, "mmHg"),
    "temp_c": (30.0, 44.0, "C"),
    "gcs": (3, 15, ""),
    "pain": (0, 10, "/10"),
}

# --- Life-saving intervention triggers (ESI Decision Point A -> ESI 1). ---
# Each: (id, human label, citation-tag). Vitals thresholds checked in esi.py.
LIFE_SAVING_VITALS = {
    "gcs_le_8": ("GCS <= 8 (unable to protect airway)", "ESI"),
    "spo2_lt_90": ("SpO2 < 90% (severe hypoxia)", "ESI"),
    "rr_ge_40": ("RR >= 40 (impending respiratory failure)", "ESI"),
    "rr_le_8": ("RR <= 8 (hypoventilation / apnea risk)", "ESI"),
    "sbp_lt_80": ("SBP < 80 mmHg (shock)", "ESI"),
    "hr_ge_150": ("HR >= 150 (unstable tachyarrhythmia range)", "ESI"),
}
LIFE_SAVING_PHRASES = {
    "cardiac arrest", "no pulse", "not breathing", "apneic", "apnoea", "apnea",
    "unresponsive", "unconscious", "actively seizing", "status epilepticus",
    "anaphylaxis with stridor", "airway compromise", "cannot protect airway",
    "gunshot", "major hemorrhage", "exsanguinating",
}

# --- Red-flag lexicon (ESI Decision Point B -> high risk -> ESI 2). ---
# requires_orders: the workup that a *safe* proposal must already include; if a
# red flag fired and none of these appear in the proposal, Attending flags the
# workup as incomplete (and blocks a discharge/fast-track disposition).
# esi_floor: most-acute level the flag alone justifies (2 for all current
# flags; airway/hemodynamic collapse reaches ESI 1 via Decision A vitals).
# ALL patterns/thresholds DRAFT — pending physician/board review.
RED_FLAGS: list[dict] = [
    {
        "id": "RF-ACS",
        "label": "Chest pain suggestive of acute coronary syndrome",
        "patterns": [
            r"chest pain", r"chest pressure", r"chest tightness",
            r"pain (?:radiating|down)\s+(?:to\s+)?(?:left|right)?\s*arm",
            r"jaw pain", r"diaphore", r"crushing chest",
        ],
        "esi_floor": 2,
        "requires_orders": ["ecg", "troponin"],
        "citation": "ACS",
        "rationale": "Undifferentiated chest pain requires ECG within 10 min to "
        "exclude STEMI; ACS cannot be excluded at triage.",
    },
    {
        "id": "RF-STROKE",
        "label": "Acute stroke symptoms",
        "patterns": [
            r"facial droop", r"face droop", r"slurred speech", r"aphasi",
            r"one[- ]sided weakness", r"weakness (?:on|to) (?:one|the) (?:side|left|right)",
            r"arm drift", r"last known well", r"sudden.{0,80}(?:numb|weak)",
        ],
        "esi_floor": 2,
        "requires_orders": ["ct_head", "stroke_activation", "ct head"],
        "citation": "STROKE",
        "rationale": "Time-critical: tPA/thrombectomy window depends on "
        "last-known-well; needs immediate non-contrast CT head.",
    },
    {
        "id": "RF-SEPSIS",
        "label": "Possible sepsis / infection with systemic signs",
        "patterns": [
            r"fever.{0,80}(?:confus|letharg|weak|low blood pressure|hypotens)",
            r"(?:confus|letharg).{0,80}fever", r"septic", r"rigors.{0,80}fever",
        ],
        "esi_floor": 2,
        "requires_orders": ["lactate", "blood_cultures", "antibiotics"],
        "citation": "SEPSIS",
        "rationale": "Suspected sepsis needs lactate + cultures + antibiotics "
        "within 1 hour; mortality rises ~4-8%/hour of delay.",
    },
    {
        "id": "RF-SUICIDE",
        "label": "Suicidal / homicidal ideation or intentional overdose",
        "patterns": [
            r"suicid", r"kill (?:myself|himself|herself|themselves)",
            r"homicid", r"overdose", r"took (?:a )?(?:bunch|bottle|handful)",
            r"self[- ]harm", r"wants? to die",
        ],
        "esi_floor": 2,
        "requires_orders": ["1:1_observation", "safety_search", "psych_eval"],
        "citation": "SI/HI",
        "rationale": "Requires 1:1 observation and ligature/means removal; "
        "cannot be placed in an unmonitored waiting area.",
    },
    {
        "id": "RF-ANAPHYLAXIS",
        "label": "Possible anaphylaxis",
        "patterns": [
            r"throat (?:swelling|closing|tight)", r"tongue swelling",
            r"allergic.{0,80}(?:breath|wheez|swell)", r"hives.{0,80}(?:breath|wheez)",
            r"anaphyla",
        ],
        "esi_floor": 2,
        "requires_orders": ["epinephrine"],
        "citation": "ANAPH",
        "rationale": "IM epinephrine is first-line and time-critical; airway "
        "compromise can escalate to ESI 1.",
    },
    {
        "id": "RF-PREG-ABD",
        "label": "Pregnancy with abdominal pain / bleeding (ectopic risk)",
        "patterns": [
            r"pregnan.{0,80}(?:abdominal|belly|pelvic) pain",
            r"pregnan.{0,80}bleed", r"positive pregnancy.{0,80}pain",
        ],
        "esi_floor": 2,
        "requires_orders": ["bhcg", "pelvic_us", "type_and_screen"],
        "citation": "ESI",
        "rationale": "Ruptured ectopic is life-threatening; needs urgent "
        "beta-hCG and pelvic ultrasound.",
    },
    {
        "id": "RF-TORSION",
        "label": "Acute testicular pain (torsion risk)",
        "patterns": [r"testic.{0,80}pain", r"scrotal pain", r"testic.{0,80}swell"],
        "esi_floor": 2,
        "requires_orders": ["scrotal_us", "urology_consult"],
        "citation": "ESI",
        "rationale": "Testicular torsion is a 6-hour surgical emergency; needs "
        "immediate ultrasound and urology.",
    },
    # --- v0.2.0 additions (DRAFT — pending physician/board review) ---
    {
        "id": "RF-DISSECTION",
        "label": "Chest/back pain suggestive of acute aortic dissection",
        "patterns": [
            r"(?:tearing|ripping).{0,40}(?:chest|back)",
            r"(?:chest|back) pain.{0,40}(?:tearing|ripping)",
            r"chest pain.{0,40}(?:radiat|mov|goes|through).{0,25}back",
            r"aortic dissection",
        ],
        "esi_floor": 2,
        "requires_orders": ["cta_chest", "ct_angio", "ct angiogram"],
        "citation": "DISSECT",
        "rationale": "Tearing/ripping chest-to-back pain is the classic "
        "dissection descriptor; mortality rises ~1-2%/hour untreated. Needs "
        "emergent CT angiography; hemodynamic collapse escalates to ESI 1 "
        "via Decision A.",
    },
    {
        "id": "RF-SAH",
        "label": "Thunderclap headache (subarachnoid hemorrhage risk)",
        "patterns": [
            r"worst headache of (?:my|his|her|their) life",
            r"thunderclap",
            r"sudden(?:,? severe| onset(?: of)?(?: severe)?)? headache",
            r"headache.{0,40}(?:maximal|peak).{0,20}(?:instant|second|minute)",
        ],
        "esi_floor": 2,
        "requires_orders": ["ct_head", "ct head", "lumbar_puncture"],
        "citation": "SAH",
        "rationale": "Sudden-onset severe ('worst of life') headache must be "
        "evaluated for SAH with urgent non-contrast CT head (+/- LP); "
        "misdiagnosis of sentinel bleed is a leading cause of preventable "
        "death.",
    },
    {
        "id": "RF-GIB",
        "label": "Significant gastrointestinal bleeding",
        "patterns": [
            r"hematemesis", r"vomit(?:ing|ed)?(?: up)? blood",
            r"coffee[- ]ground", r"melena", r"black,? tarry stools?",
            r"(?:large|copious|significant).{0,30}rectal bleed",
            r"bright red blood per rectum", r"\bbrbpr\b",
        ],
        "esi_floor": 2,
        "requires_orders": ["type_and_screen", "iv_access", "gi_consult"],
        "citation": "GIB",
        "rationale": "Hematemesis/melena/large rectal bleeding can decompensate "
        "rapidly; needs IV access, type & screen, and hemodynamic monitoring "
        "before any low-acuity routing.",
    },
    {
        "id": "RF-DKA",
        "label": "Possible diabetic ketoacidosis / hyperglycemic crisis",
        "patterns": [
            r"diabet.{0,60}(?:vomit|nausea|confus|letharg|drowsy)",
            r"(?:vomit|nausea|confus|letharg|drowsy).{0,60}diabet",
            r"(?:blood sugar|glucose).{0,20}(?:high|hi\b|[3-9]\d\d)",
            r"fruity (?:breath|odor|odour)", r"ketoacidosis", r"\bdka\b",
            r"ketones",
        ],
        "esi_floor": 2,
        "requires_orders": ["glucose", "vbg", "bmp", "insulin"],
        "citation": "DKA",
        "rationale": "Diabetic patient with vomiting, markedly elevated sugar, "
        "or altered mentation may be in DKA; needs immediate glucose/gas/BMP "
        "and cannot wait in a low-acuity queue.",
    },
    {
        "id": "RF-FN",
        "label": "Fever in a chemotherapy / neutropenic patient",
        "patterns": [
            r"chemo(?:therapy)?.{0,80}(?:fever|febrile)",
            r"(?:fever|febrile).{0,80}chemo(?:therapy)?",
            r"neutropeni", r"febrile neutropenia",
        ],
        "esi_floor": 2,
        "requires_orders": ["blood_cultures", "antibiotics", "cbc"],
        "citation": "FN-ONC",
        "rationale": "Febrile neutropenia is an oncologic emergency: cultures "
        "and empiric broad-spectrum antibiotics within 1 hour; a normal exam "
        "does not exclude occult bacteremia.",
    },
    {
        "id": "RF-CAUDA",
        "label": "Back pain with cauda equina features",
        "patterns": [
            r"saddle (?:anesthesia|anaesthesia|numbness)",
            r"back pain.{0,80}(?:urinary retention|can'?t (?:urinate|pee)|"
            r"unable to (?:urinate|void)|incontinen)",
            r"(?:urinary retention|incontinen).{0,80}back pain",
            r"back pain.{0,80}(?:bilateral leg (?:weak|numb)|both legs? "
            r"(?:weak|numb)|weakness in both legs)",
            r"numb.{0,30}(?:groin|perineum|saddle)",
        ],
        "esi_floor": 2,
        "requires_orders": ["mri_spine", "mri", "bladder_scan",
                            "neurosurgery_consult"],
        "citation": "CAUDA",
        "rationale": "Saddle anesthesia, urinary retention/incontinence, or "
        "bilateral leg weakness with back pain suggests cauda equina — a "
        "time-critical surgical emergency needing urgent MRI.",
    },
    {
        "id": "RF-EYE",
        "label": "Acute vision loss or chemical eye exposure",
        "patterns": [
            r"(?:sudden|acute|painless).{0,40}(?:vision loss|loss of vision)",
            r"vision (?:loss|went (?:black|dark)|gone)",
            r"can'?t see (?:out of|from)",
            r"chemical.{0,30}(?:eye|splash)",
            r"(?:bleach|acid|alkali|lye|drain cleaner).{0,30}eye",
            r"eye.{0,30}(?:bleach|acid|alkali|lye|chemical)",
        ],
        "esi_floor": 2,
        "requires_orders": ["visual_acuity", "ocular_irrigation",
                            "ophthalmology_consult", "ph_test"],
        "citation": "EYE",
        "rationale": "Acute vision loss is potentially reversible only within "
        "hours; chemical (especially alkali) exposure needs immediate "
        "irrigation before anything else — neither can wait.",
    },
    {
        "id": "RF-SICKLE",
        "label": "Sickle cell vaso-occlusive pain crisis",
        "patterns": [
            r"sickle.{0,40}(?:crisis|pain)", r"pain.{0,40}sickle",
            r"sickle cell", r"vaso[- ]?occlusive",
        ],
        "esi_floor": 2,
        "requires_orders": ["analgesia", "opioids", "pain_control", "cbc",
                            "reticulocyte"],
        "citation": "SICKLE",
        "rationale": "ESI v4 explicitly lists sickle cell pain crisis as "
        "high-risk (ESI 2): rapid analgesia within 60 min and evaluation for "
        "acute chest syndrome / aplastic crisis.",
    },
    {
        "id": "RF-PREECLAMPSIA",
        "label": "Pregnancy >20 wk with severe hypertension / preeclampsia signs",
        "patterns": [
            r"preeclamp", r"pre-eclamp", r"eclamp",
            r"pregnan.{0,60}(?:severe )?headache",
            r"pregnan.{0,60}(?:blurr|vision changes|seeing spots|scotoma)",
            r"pregnan.{0,60}(?:hypertens|high blood pressure)",
            r"(?:headache|hypertens|high blood pressure).{0,60}pregnan",
        ],
        "esi_floor": 2,
        "requires_orders": ["preeclampsia_labs", "magnesium", "ob_consult",
                            "urine_protein"],
        "citation": "PREE",
        "rationale": "Headache, visual change, or severe-range BP in pregnancy "
        ">20 wk may be preeclampsia; progression to eclampsia is abrupt. "
        "Needs BP confirmation, labs, and OB involvement — not a waiting "
        "room. (Gestational-age gate is textual; board may tighten.)",
    },
]

# Phrases indicating acute altered mental status (ESI 2 via Decision B).
ALTERED_PHRASES = {
    "confused", "confusion", "lethargic", "disoriented", "altered mental",
    "not making sense", "won't wake up", "hard to arouse", "obtunded",
}

# --- Resource estimation lexicon (ESI Decision Point C). ---
# complaint keyword -> (min_resources, max_resources). The spread is the
# primary source of triage uncertainty and drives the confidence interval.
# First match wins; keep more specific complaints earlier.
RESOURCE_ESTIMATES: list[tuple[list[str], int, int]] = [
    (["med refill", "prescription refill", "medication refill", "note for work",
      "suture removal", "recheck"], 0, 0),
    (["sore throat", "cold symptoms", "runny nose", "ear pain", "pink eye",
      "uti symptoms", "rash"], 0, 1),
    (["ankle", "wrist", "finger", "toe", "sprain", "minor laceration",
      "small cut"], 1, 1),
    (["laceration", "foreign body", "abscess"], 1, 2),
    (["abdominal pain", "belly pain", "flank pain", "kidney stone",
      "vomiting and diarrhea", "vaginal bleeding"], 2, 4),
    (["shortness of breath", "difficulty breathing", "palpitations",
      "syncope", "fainting", "weakness"], 2, 4),
    (["headache", "back pain", "dizziness"], 1, 3),
    # --- v0.2.0 additions (appended so existing matches are unchanged) ---
    (["dental pain", "toothache", "tooth pain"], 0, 1),
    (["nosebleed", "epistaxis"], 1, 1),
    (["allergic reaction", "hives"], 1, 2),
    (["cough", "wheezing", "asthma"], 1, 2),
    (["burn"], 1, 2),
    (["fever", "chills"], 1, 3),
    (["migraine"], 1, 3),
    (["fall", "head injury", "hit his head", "hit her head"], 1, 3),
    (["chest pain", "chest pressure", "chest tightness"], 2, 4),
    (["seizure"], 2, 4),
    (["vomiting blood", "hematemesis", "melena", "rectal bleeding"], 2, 4),
    (["motor vehicle", "car accident", "mvc"], 2, 4),
    (["overdose", "ingestion"], 2, 4),
]
RESOURCE_DEFAULT = (1, 2)

# Human-readable citation expansions for rendering.
CITATIONS = {
    "ESI": "ESI Implementation Handbook v4 (AHRQ/ENA)",
    "ACS": "ACEP Clinical Policy: Suspected NSTE-ACS (Ann Emerg Med 2018)",
    "STROKE": "AHA/ASA Acute Ischemic Stroke Guidelines (2019)",
    "SEPSIS": "Surviving Sepsis Campaign (2021)",
    "SI/HI": "Joint Commission NPSG 15.01.01",
    "ANAPH": "AAAAI/ACAAI Anaphylaxis Practice Parameter (2020)",
    "DISSECT": "2022 ACC/AHA Aortic Disease Guideline",
    "SAH": "ACEP Clinical Policy: Acute Headache (Ann Emerg Med 2019)",
    "GIB": "ACG Clinical Guideline: Upper GI and Ulcer Bleeding (2021)",
    "DKA": "ADA/EASD Consensus Report: Hyperglycemic Crises in Adults (2024)",
    "FN-ONC": "IDSA Fever and Neutropenia Guideline (2010); ASCO/IDSA (2018)",
    "CAUDA": "ACEP Clinical Policy: Acute Low Back Pain / NASS cauda equina guidance",
    "EYE": "AAO Preferred Practice Patterns (ocular chemical injury / acute vision loss)",
    "SICKLE": "ASH 2020 SCD Guidelines: Acute Pain; NHLBI Evidence-Based Management of SCD (2014)",
    "PREE": "ACOG Practice Bulletin 222 (2020)",
    "PALS": "AHA PALS vital-sign reference ranges (2020)",
}


# --- Optional external knowledge file (configs/knowledge.json) -----------
# The JSON is EXPORTED from this module (export_json) so there is a single
# source of truth; on import we only adopt it when its ruleset_version matches
# this module's, so a stale file can never silently override reviewed rules.

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "knowledge.json"


def as_dict() -> dict:
    """The full knowledge base as a JSON-serializable dict (board artifact)."""
    return {
        "ruleset_version": RULESET_VERSION,
        "approval_status": APPROVAL_STATUS,
        "danger_zone_adult": DANGER_ZONE_ADULT,
        "danger_zone_peds": {str(k): v for k, v in DANGER_ZONE_PEDS.items()},
        "vital_plausible_ranges": {k: list(v) for k, v in
                                   VITAL_PLAUSIBLE_RANGES.items()},
        "life_saving_vitals": {k: list(v) for k, v in
                               LIFE_SAVING_VITALS.items()},
        "life_saving_phrases": sorted(LIFE_SAVING_PHRASES),
        "red_flags": RED_FLAGS,
        "altered_phrases": sorted(ALTERED_PHRASES),
        "resource_estimates": [[kws, lo, hi] for kws, lo, hi in
                               RESOURCE_ESTIMATES],
        "resource_default": list(RESOURCE_DEFAULT),
        "citations": CITATIONS,
    }


def export_json(path: str | Path = _CONFIG_PATH) -> Path:
    """Write the knowledge base to JSON for board review / external editing."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(as_dict(), indent=2, ensure_ascii=False) + "\n")
    return p


def _adopt(cfg: dict) -> None:
    """Replace module data with values from a version-matched external file.

    ATOMIC: every field is parsed into a staging dict first, so a truncated or
    partially-valid config raises BEFORE any global is touched — a failed
    adopt leaves the reviewed in-module data fully intact (never a hybrid).
    """
    staged = {
        "APPROVAL_STATUS": str(cfg["approval_status"]),
        "DANGER_ZONE_ADULT": dict(cfg["danger_zone_adult"]),
        "DANGER_ZONE_PEDS": {float(k): dict(v) for k, v in
                             cfg["danger_zone_peds"].items()},
        "VITAL_PLAUSIBLE_RANGES": {k: tuple(v) for k, v in
                                   cfg["vital_plausible_ranges"].items()},
        "LIFE_SAVING_VITALS": {k: tuple(v) for k, v in
                               cfg["life_saving_vitals"].items()},
        "LIFE_SAVING_PHRASES": set(cfg["life_saving_phrases"]),
        "RED_FLAGS": list(cfg["red_flags"]),
        "ALTERED_PHRASES": set(cfg["altered_phrases"]),
        "RESOURCE_ESTIMATES": [(list(kws), int(lo), int(hi)) for kws, lo, hi in
                               cfg["resource_estimates"]],
        "RESOURCE_DEFAULT": tuple(cfg["resource_default"]),
        "CITATIONS": dict(cfg["citations"]),
    }
    globals().update(staged)


def _load_external(path: Path = _CONFIG_PATH) -> bool:
    """Adopt configs/knowledge.json iff present and version-matched."""
    try:
        if not path.is_file():
            return False
        cfg = json.loads(path.read_text())
        if cfg.get("ruleset_version") != RULESET_VERSION:
            return False  # stale export; keep reviewed in-module data
        _adopt(cfg)
        return True
    except Exception:
        return False  # malformed file must never fail the safety layer open


KNOWLEDGE_SOURCE = "configs/knowledge.json" if _load_external() else "builtin"
