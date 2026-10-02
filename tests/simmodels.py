"""Response models and signals for the definitions in the tests to name.

SARABI imports whatever a definition names, so these stand in for the likes of
`laura.utils.dynamics`, which the tests should not need installed.
"""

import math


class FirstOrderResponse:
    """A readback that closes on its setpoint with time constant `tau`."""

    def __init__(self, tau: float = 0.5):
        self.tau = tau
        self.value = 0.0

    def __call__(self, target, dt):
        self.value += (target - self.value) * (1 - math.exp(-dt / self.tau))
        return self.value


class Sinusoid:
    def __init__(self, period: float = 10.0, amplitude: float = 1.0):
        self.period = period
        self.amplitude = amplitude

    def __call__(self, t):
        return self.amplitude * math.sin(2 * math.pi * t / self.period)
