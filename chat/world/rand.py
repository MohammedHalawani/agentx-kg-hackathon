"""Deterministic, keyed random draws.

Every draw is a pure function of (seed, key). A parcel's processing jitter therefore does not change when
a mechanism is added elsewhere in the world, and no draw depends on Python hash randomization or on the
order in which entities happen to be visited.
"""
import hashlib
import math
import random
from statistics import NormalDist

_STANDARD = NormalDist()
_SCALE = float(16 ** 13)


class Draws:
    def __init__(self, seed: int):
        self.seed = seed

    def u(self, *key) -> float:
        digest = hashlib.sha256(("%d|" % self.seed + "|".join(map(str, key))).encode()).hexdigest()
        value = int(digest[:13], 16) / _SCALE
        return min(max(value, 1e-12), 1 - 1e-12)

    def uniform(self, a: float, b: float, *key) -> float:
        return a + (b - a) * self.u(*key)

    def normal(self, mu: float, sigma: float, *key) -> float:
        return mu + sigma * _STANDARD.inv_cdf(self.u(*key))

    def lognormal(self, median: float, sigma: float, *key) -> float:
        return median * math.exp(sigma * _STANDARD.inv_cdf(self.u(*key)))

    def expo(self, mean: float, *key) -> float:
        return -mean * math.log(1 - self.u(*key))

    def chance(self, p: float, *key) -> bool:
        return self.u(*key) < p

    def integer(self, a: int, b: int, *key) -> int:
        """Uniform integer in [a, b]."""
        return a + min(int(self.u(*key) * (b - a + 1)), b - a)

    def choice(self, seq, *key):
        seq = list(seq)
        return seq[min(int(self.u(*key) * len(seq)), len(seq) - 1)]

    def weighted(self, pairs, *key):
        """pairs: iterable of (value, weight) in a fixed order."""
        pairs = list(pairs)
        total = sum(w for _, w in pairs)
        target = self.u(*key) * total
        running = 0.0
        for value, weight in pairs:
            running += weight
            if target < running:
                return value
        return pairs[-1][0]

    def rng(self, *key) -> random.Random:
        """A seeded generator for shuffles and samples that belong to one key."""
        digest = hashlib.sha256(("%d|rng|" % self.seed + "|".join(map(str, key))).encode()).hexdigest()
        return random.Random(int(digest[:16], 16))

    def sample(self, seq, k: int, *key) -> list:
        seq = list(seq)
        return self.rng(*key).sample(seq, min(k, len(seq)))

    def shuffled(self, seq, *key) -> list:
        seq = list(seq)
        self.rng(*key).shuffle(seq)
        return seq
