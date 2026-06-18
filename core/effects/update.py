import random
import numpy as np


class NoiseMixin:
    def add_noise(self, value, noise_level):
        if noise_level is None:
            return value
        if isinstance(value, (np.int32, int, np.float32)):
            return value + random.uniform(-noise_level, noise_level)
        elif isinstance(value, np.ndarray):
            noise = np.random.uniform(-noise_level, noise_level, size=value.shape)
            return value + noise
        return value
