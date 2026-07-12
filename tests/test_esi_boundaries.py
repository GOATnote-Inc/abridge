"""Boundary pins for the physician-reviewed clinical thresholds.

The esi.py mutation round (2026-07-12) showed no test held the EXACT
boundary of any life-saving threshold — GCS <=8 vs <8 survived, SpO2 <90
vs <=90 survived, and so on. These values were ruled individually in the
2026-07-09 clinical review; a silent one-unit drift is precisely the
"silently weaken a safety criterion" failure the charter forbids, so every
boundary is pinned at, and adjacent to, its reviewed value. A threshold
change must arrive as a reviewed knowledge/esi change that consciously
updates these pins.
"""

import pytest

from attending import esi
from attending.encounter import Encounter, Vitals


def _enc(**vitals) -> Encounter:
    return Encounter("BND", "boundary check", age_years=40,
                     vitals=Vitals(**vitals))


# (kwargs at threshold, kwargs just outside, label fragment)
_LIFE_SAVING_EDGES = [
    ({"gcs": 8}, {"gcs": 9}, "GCS"),          # gcs <= 8
    ({"spo2": 89}, {"spo2": 90}, "SpO2"),     # spo2 < 90
    ({"rr": 40}, {"rr": 39}, "RR"),           # rr >= 40
    ({"rr": 8}, {"rr": 9}, "RR"),             # rr <= 8
    ({"sbp": 79}, {"sbp": 80}, "SBP"),        # sbp < 80
    ({"hr": 150}, {"hr": 149}, "HR"),         # hr >= 150
]


class TestLifeSavingBoundaries:
    @pytest.mark.parametrize("at,off,label", _LIFE_SAVING_EDGES,
                             ids=[str(e[0]) for e in _LIFE_SAVING_EDGES])
    def test_at_threshold_fires_one_off_does_not(self, at, off, label):
        fired = esi._life_saving(_enc(**at))
        assert fired, f"{at} must be life-saving"
        # the hit must carry the human-readable LABEL (not the citation
        # tuple-mate): the verdict rail displays exactly this string
        assert any(label.lower() in h.lower() for h in fired), fired
        # The off-by-one value must NOT fire *this* rule. (rr 9/39 and
        # hr 149 may still be danger-zone — that is ESI-2 territory, a
        # different rule; life-saving is the ESI-1 list.)
        fired = esi._life_saving(_enc(**off))
        assert not fired, f"{off} must not be on the ESI-1 life-saving list"


class TestAlteredBoundaries:
    def test_gcs_9_to_14_is_altered_8_and_15_are_not(self):
        # _altered covers the open interval 8 < gcs < 15 exactly: 8 belongs
        # to the life-saving rule, 15 is normal.
        assert esi._altered(_enc(gcs=9))
        assert esi._altered(_enc(gcs=14))
        assert esi._altered(_enc(gcs=15)) is None
        assert esi._altered(_enc(gcs=8)) is None   # ESI-1's, not ESI-2's


class TestDangerZoneBoundaries:
    def test_adult_thresholds_are_strict_inequalities(self):
        from attending import knowledge as K
        t = K.DANGER_ZONE_ADULT
        at_hr = Vitals(hr=t["hr_gt"] + 1)
        eq_hr = Vitals(hr=t["hr_gt"])
        assert esi._danger_zone(at_hr, 40)
        assert not esi._danger_zone(eq_hr, 40)     # gt means strictly greater
        at_spo2 = Vitals(spo2=t["spo2_lt"] - 1)
        eq_spo2 = Vitals(spo2=t["spo2_lt"])
        assert esi._danger_zone(at_spo2, 40)
        assert not esi._danger_zone(eq_spo2, 40)   # lt means strictly less

    def test_peds_band_selected_at_band_edge(self):
        from attending import knowledge as K
        # A child exactly at a band's age_max uses THAT band (<=), and the
        # youngest applicable band wins.
        youngest = sorted(K.DANGER_ZONE_PEDS)[0]
        band = K.DANGER_ZONE_PEDS[youngest]
        v = Vitals(hr=band["hr_gt"] + 1)
        assert esi._danger_zone(v, youngest)       # at the edge: peds band
        adult_ok = band["hr_gt"] + 1 <= K.DANGER_ZONE_ADULT["hr_gt"]
        if adult_ok:
            assert not esi._danger_zone(v, None)   # same HR fine for adults


class TestQuarantineInteraction:
    def test_quarantined_implausible_vital_cannot_trip_life_saving(self):
        # An HR of 400 is a capture/typo artifact (outside the plausibility
        # envelope): it must be QUARANTINED — escalated via detectors — and
        # must NOT mint an ESI-1 through the hr_ge_150 rule.
        quarantined, notes = esi.quarantine_implausible_vitals(
            Vitals(hr=400))
        assert "hr" in quarantined and notes
        # The raw value WOULD fire hr_ge_150 — proving the pipeline must
        # quarantine before the life-saving check runs:
        assert esi._life_saving(_enc(hr=400))
        acuity = esi.compute_esi(_enc(hr=400))
        assert acuity.level != 1, "a capture-error HR must not mint ESI-1"
        assert any("Quarantined implausible hr" in r for r in acuity.reasons)


class TestPlausibilityEnvelopeBoundaries:
    def test_envelope_edges_are_inclusive(self):
        # A vital AT the envelope bound is plausible (real bradycardia at
        # the floor is a patient, not a typo); one past it is quarantined.
        from attending import knowledge as K
        lo, hi = K.VITAL_PLAUSIBLE_RANGES["hr"][:2]
        q_at_lo, _ = esi.quarantine_implausible_vitals(Vitals(hr=lo))
        assert "hr" not in q_at_lo
        q_below, _ = esi.quarantine_implausible_vitals(Vitals(hr=lo - 1))
        assert "hr" in q_below
        q_at_hi, _ = esi.quarantine_implausible_vitals(Vitals(hr=hi))
        assert "hr" not in q_at_hi
        q_above, _ = esi.quarantine_implausible_vitals(Vitals(hr=hi + 1))
        assert "hr" in q_above

    def test_multiple_implausible_vitals_all_quarantined(self):
        # kills continue->break: the quarantine walk must not stop at the
        # first implausible vital.
        q, notes = esi.quarantine_implausible_vitals(Vitals(hr=999, rr=999))
        assert "hr" in q and "rr" in q
        assert len(notes) >= 2


class TestDangerZoneRRBoundary:
    def test_adult_rr_gt_is_strict(self):
        from attending import knowledge as K
        t = K.DANGER_ZONE_ADULT
        assert esi._danger_zone(Vitals(rr=t["rr_gt"] + 1), 40)
        assert not esi._danger_zone(Vitals(rr=t["rr_gt"]), 40)
