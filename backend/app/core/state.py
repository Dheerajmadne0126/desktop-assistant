import time
from enum import Enum

from app.core.events import event_bus
from app.core.logging import get_logger

logger = get_logger("state")


class AgentState(str, Enum):
    IDLE = "IDLE"
    LISTENING_FOR_WAKE_WORD = "LISTENING_FOR_WAKE_WORD"
    LISTENING_FOR_COMMAND = "LISTENING_FOR_COMMAND"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"


_VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.IDLE: {
        AgentState.LISTENING_FOR_WAKE_WORD,
        AgentState.LISTENING_FOR_COMMAND,
        AgentState.THINKING,
    },
    AgentState.LISTENING_FOR_WAKE_WORD: {
        AgentState.LISTENING_FOR_COMMAND,
        AgentState.IDLE,
    },
    AgentState.LISTENING_FOR_COMMAND: {
        AgentState.THINKING,
        AgentState.SPEAKING,
        AgentState.LISTENING_FOR_WAKE_WORD,
        AgentState.IDLE,
    },
    AgentState.THINKING: {
        AgentState.EXECUTING,
        AgentState.SPEAKING,
        AgentState.LISTENING_FOR_COMMAND,
        AgentState.LISTENING_FOR_WAKE_WORD,
        AgentState.IDLE,
    },
    AgentState.EXECUTING: {
        AgentState.THINKING,
        AgentState.SPEAKING,
        AgentState.LISTENING_FOR_COMMAND,
        AgentState.IDLE,
    },
    AgentState.SPEAKING: {
        AgentState.LISTENING_FOR_COMMAND,
        AgentState.LISTENING_FOR_WAKE_WORD,
        AgentState.IDLE,
        AgentState.THINKING,
    },
}


class StateMachine:
    def __init__(self) -> None:
        self._state = AgentState.LISTENING_FOR_WAKE_WORD
        self.last_active_time = time.time()

    @property
    def state(self) -> AgentState:
        return self._state

    def can_transition(self, new_state: AgentState) -> bool:
        return new_state in _VALID_TRANSITIONS[self._state]

    async def set_state(self, new_state: AgentState, message: str = "") -> None:
        if new_state == self._state:
            return
        if not self.can_transition(new_state):
            logger.warning(
                "Invalid state transition %s -> %s (message=%s); forcing.",
                self._state.value,
                new_state.value,
                message,
            )
        self._state = new_state
        if new_state != AgentState.IDLE:
            self.last_active_time = time.time()
        logger.info("State -> %s %s", new_state.value, message)
        await event_bus.publish(
            {"type": "state_change", "state": new_state.value, "message": message}
        )


state_machine = StateMachine()
