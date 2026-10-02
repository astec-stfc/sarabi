"""Response models and signals for the tests, so they need nothing installed."""


class HalfWay:
    """A readback that closes half the remaining gap to its setpoint each step."""

    def __init__(self):
        self.value = 0.0

    def __call__(self, target, dt):
        self.value += (target - self.value) / 2
        return self.value


class Clock:
    """A signal equal to the elapsed time."""

    def __call__(self, t):
        return t
