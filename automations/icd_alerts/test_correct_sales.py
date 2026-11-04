from automations.icd_alerts.correct_sales import apply_correction, match_rep, parse_set


LAST = {"ANDREW DE LA TORRE": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 8, "credit": 2},
        "AARON DE LA TORRE": {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 0},
        "ANNETT CLIMACO": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 2}}


def test_exact_match_beats_partial():
    assert match_rep(LAST, "andrew de la torre") == "ANDREW DE LA TORRE"
    assert match_rep(LAST, "De La Torre") is None          # two of them
    assert match_rep(LAST, "Climaco") == "ANNETT CLIMACO"
    assert match_rep(LAST, "Nobody") is None


def test_only_the_one_metric_changes_and_credit_state_survives():
    new, key, old = apply_correction(LAST, "Andrew De La Torre", "NL", 4)
    assert (key, old) == ("ANDREW DE LA TORRE", 8)
    assert new["ANDREW DE LA TORRE"] == {"Int": 0, "Int Up": 0, "DTV": 0, "NL": 4, "credit": 2}
    assert new["ANNETT CLIMACO"] == LAST["ANNETT CLIMACO"]
    assert LAST["ANDREW DE LA TORRE"]["NL"] == 8          # input untouched


def test_parse_set():
    assert parse_set("NL=4") == ("NL", 4)
    try:
        parse_set("NL")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
