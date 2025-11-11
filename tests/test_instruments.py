import pytest

from bot.instruments import (
    gad7_bucket,
    gad7_score,
    phq9_bucket,
    phq9_item9_flag,
    phq9_score,
)


PHQ9_CASES = [
    ([0, 0, 0, 0, 0, 0, 0, 0, 0], 0, "Sem sintomas"),
    ([1, 1, 1, 1, 0, 0, 0, 0, 0], 4, "Sem sintomas"),
    ([1, 1, 1, 1, 1, 0, 0, 0, 0], 5, "Mínimos"),
    ([1, 1, 1, 1, 1, 1, 1, 1, 1], 9, "Mínimos"),
    ([2, 1, 1, 1, 1, 1, 1, 1, 1], 10, "Leves"),
    ([2, 2, 2, 2, 1, 1, 1, 1, 1], 14, "Leves"),
    ([2, 2, 2, 2, 2, 2, 1, 1, 1], 15, "Moderados"),
    ([2, 2, 2, 2, 2, 2, 2, 2, 1], 19, "Moderados"),
    ([3, 3, 3, 3, 2, 2, 2, 1, 1], 20, "Graves"),
    ([3, 3, 3, 3, 3, 3, 3, 3, 3], 27, "Graves"),
]


@pytest.mark.parametrize("responses,total,label", PHQ9_CASES)
def test_phq9_scores_and_buckets(responses, total, label):
    assert phq9_score(responses) == total
    assert phq9_bucket(total) == label


def test_phq9_item9_flag_triggers_when_response_positive():
    responses = [0, 0, 0, 0, 0, 0, 0, 0, 1]
    assert phq9_item9_flag(responses) is True


def test_phq9_item9_flag_false_when_zero():
    responses = [0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert phq9_item9_flag(responses) is False


GAD7_CASES = [
    ([0, 0, 0, 0, 0, 0, 0], 0, "Mínima"),
    ([1, 1, 1, 1, 0, 0, 0], 4, "Mínima"),
    ([1, 1, 1, 1, 1, 0, 0], 5, "Leve"),
    ([1, 1, 1, 1, 1, 1, 1], 7, "Leve"),
    ([2, 2, 1, 1, 1, 1, 2], 10, "Moderada"),
    ([2, 2, 2, 2, 2, 2, 2], 14, "Moderada"),
    ([3, 2, 2, 2, 2, 2, 2], 15, "Grave"),
    ([3, 3, 3, 3, 3, 3, 3], 21, "Grave"),
]


@pytest.mark.parametrize("responses,total,label", GAD7_CASES)
def test_gad7_scores_and_buckets(responses, total, label):
    assert gad7_score(responses) == total
    assert gad7_bucket(total) == label


