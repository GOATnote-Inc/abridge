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


def test_binomial_upper_bound_is_exact():
    from attending.evaluate import binom_upper
    # Closed form for x=0: upper = 1 - alpha^(1/n).
    assert abs(binom_upper(0, 23) - (1 - 0.05 ** (1 / 23))) < 1e-9
    assert binom_upper(0, 300) < 0.01  # the n needed for a ~1% claim
    assert binom_upper(23, 23) == 1.0 and binom_upper(0, 0) == 1.0
