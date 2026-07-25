class InterruptAgentFlow(Exception):
    """Interrupt the control loop and append the supplied messages."""

    def __init__(self, *messages: dict):
        self.messages = messages
        super().__init__()


class Submitted(InterruptAgentFlow):
    pass


class LimitsExceeded(InterruptAgentFlow):
    pass


class TimeExceeded(LimitsExceeded):
    pass


class FormatError(InterruptAgentFlow):
    pass
