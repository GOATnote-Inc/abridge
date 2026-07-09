"""The gold set as a CI gate. FN=0 is non-negotiable and blocks merge."""

from attending.evaluate import evaluate, summarize


def test_no_false_negatives():
    """The cardinal safety contract: no unsafe proposal is ever ALLOWed."""
    s = summarize(evaluate())
    assert s["false_negatives"] == 0, (
        f"{s['false_negatives']} unsafe proposal(s) not stopped — "
        "fail-closed contract violated"
    )


def test_full_goldset_passes():
    """Every labeled case matches (decision + acuity + criterion)."""
    results = evaluate()
    failed = [r.id for r in results if not r.ok]
    assert not failed, f"gold-set regressions: {failed}"
