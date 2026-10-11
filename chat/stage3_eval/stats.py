"""Statistics the design names, in plain Python (no scipy): Wilson intervals, the exact McNemar test, a paired
difference interval, and the power and minimum detectable gain of the exact McNemar test.
"""
from math import exp, lgamma, log, sqrt

Z95 = 1.959963984540054


def wilson(successes: int, n: int, z: float = Z95):
    """Wilson 95% score interval (low, high) as proportions; (None, None) when n = 0."""
    if n <= 0:
        return None, None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _log_binom_pmf(k, n, p):
    if p <= 0:
        return 0.0 if k == 0 else float("-inf")
    if p >= 1:
        return 0.0 if k == n else float("-inf")
    return lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1) + k * log(p) + (n - k) * log(1 - p)


def binom_pmf(k, n, p):
    return exp(_log_binom_pmf(k, n, p))


def mcnemar_exact(wins: int, losses: int):
    """Exact two-sided McNemar p-value on the discordant pairs: 2 * P(X <= min(b, c)), X ~ Bin(b + c, 1/2), capped at 1."""
    k = wins + losses
    if k == 0:
        return 1.0
    tail = sum(binom_pmf(i, k, 0.5) for i in range(min(wins, losses) + 1))
    return min(1.0, 2 * tail)


def paired_difference_interval(both: int, only_a: int, only_b: int, neither: int, z: float = Z95):
    """Newcombe's hybrid score interval (method 10) for the paired difference p_a - p_b. Returns (diff, low, high)."""
    n = both + only_a + only_b + neither
    if n == 0:
        return None, None, None
    p1, p2 = (both + only_a) / n, (both + only_b) / n
    l1, u1 = wilson(both + only_a, n, z)
    l2, u2 = wilson(both + only_b, n, z)
    denom = (both + only_a) * (only_b + neither) * (both + only_b) * (only_a + neither)
    phi = (both * neither - only_a * only_b) / sqrt(denom) if denom > 0 else 0.0
    d = p1 - p2
    low = d - sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    high = d + sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    return d, max(-1.0, low), min(1.0, high)


def _rejects(wins, k, alpha):
    return wins > k - wins and mcnemar_exact(wins, k - wins) < alpha


def mcnemar_power(n: int, discordance: float, gain: float, alpha: float = 0.05) -> float:
    """Power of the exact two-sided McNemar test (with more wins than losses) for n paired cases, a discordant share
    `discordance` and a true gain `gain` (agent-only minus baseline-only share). Exact over the discordant count."""
    if not 0 < discordance <= 1 or not 0 <= gain <= discordance:
        raise ValueError("need 0 < discordance <= 1 and 0 <= gain <= discordance")
    q = (discordance + gain) / (2 * discordance)
    # The rejection region on wins for each discordant count k is an upper tail: find its start once per k.
    power = 0.0
    for k in range(n + 1):
        pk = binom_pmf(k, n, discordance)
        if pk < 1e-15:
            continue
        start = next((w for w in range(k // 2 + 1, k + 1) if _rejects(w, k, alpha)), None)
        if start is None:
            continue
        power += pk * sum(binom_pmf(w, k, q) for w in range(start, k + 1))
    return power


def minimum_detectable_gain(n: int, discordance: float, alpha: float = 0.05, power: float = 0.80, step: float = 0.001):
    """Smallest gain (as a proportion) the exact McNemar test detects with the given power; None if none <= discordance."""
    if n <= 0:
        return None
    lo, hi = 0.0, discordance
    if mcnemar_power(n, discordance, hi, alpha) < power:
        return None
    while hi - lo > step:
        mid = (lo + hi) / 2
        if mcnemar_power(n, discordance, mid, alpha) >= power:
            hi = mid
        else:
            lo = mid
    return round(hi, 3)


def percentile(values, q):
    """Nearest-rank percentile (q in 0..100); None for no values."""
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    rank = max(1, -(-len(values) * q // 100))
    return values[int(rank) - 1]
