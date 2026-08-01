class InterruptAgentFlow(Exception):
    """Interrupt the control loop and append the supplied messages."""

    def __init__(self, *messages: dict):
        self.messages = messages
        super().__init__()


class Submitted(InterruptAgentFlow):
    pass


class LimitsExceeded(InterruptAgentFlow):
    pass


class InputTokenLimitExceeded(LimitsExceeded):
    pass


class TotalTokenLimitExceeded(LimitsExceeded):
    pass


class RepeatedActionExceeded(LimitsExceeded):
    pass


class NoProgressExceeded(LimitsExceeded):
    pass


class ConsecutiveToolFailuresExceeded(LimitsExceeded):
    pass


class TimeExceeded(LimitsExceeded):
    pass


class FormatError(InterruptAgentFlow):
    pass
