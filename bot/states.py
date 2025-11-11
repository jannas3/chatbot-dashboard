from enum import Enum, auto


class ConversationState(Enum):
    MENU = auto()
    DADOS = auto()
    CONVERSA = auto()
    PHQ9 = auto()
    GAD7 = auto()
    AGENDAMENTO = auto()


