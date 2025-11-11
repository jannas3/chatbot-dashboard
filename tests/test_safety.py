import pytest

from bot.safety import crisis_gate, has_crisis_terms


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Quero me matar", True),
        ("Pensei em tirar a vida ontem", True),
        ("Estou sem vontade de viver", True),
        ("Hoje foi difícil, mas vou continuar", False),
        ("", False),
    ],
)
def test_has_crisis_terms(message, expected):
    assert has_crisis_terms(message) is expected


def test_crisis_gate_activates_with_llm_flag():
    assert crisis_gate("Estou tranquilo", True) is True


def test_crisis_gate_false_without_triggers():
    assert crisis_gate("Dia cansativo, mas tudo bem", False) is False


