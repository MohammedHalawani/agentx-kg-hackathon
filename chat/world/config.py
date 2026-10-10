"""World configuration, the V2 export configuration and Saudi local-time helpers.

All instants are UTC. Saudi Arabia has no daylight saving: local time is UTC+3 throughout.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re

from dataset_v2.contracts import Config, RIYADH, UTC, iso

WORLD_VERSION = "world-1.1"   # 1.1: causes versus exposures, actor-level faults, time-cut export (after independent review)
WORLD_SPLITS = ("history", "development", "held_out")
LOCAL = RIYADH

# Committed over-sampling weights (addendum B4), per scheduled mechanism: (history rate, live rate). A rate is
# the minimum share of a split's shipments on which the mechanism must be the CAUSE of a deviation (a touch
# without consequence does not count); live applies to development and held_out. History and live splits use
# the same rate, so history is a fair prior for the live days and has cases to learn from.
# Scenario weighting, not real frequencies: every world manifest records these rates and the targets they give.
# At .02 a split of 250 shipments carries 5 caused shipments per mechanism; the floor of 10 clean cases per
# mechanism (validate.coverage) needs a larger world, not a denser one (see README "Size and the clean-case floor").
HISTORY_RATE, LIVE_RATE = .02, .02
MECHANISM_RATES = {mechanism: (HISTORY_RATE, LIVE_RATE) for mechanism in (
    "DEVICE_OUTAGE", "PARTIAL_UPLOAD_LOSS", "SCAN_SKIPPED_AT_RECEIPT", "FACILITY_BACKLOG", "LATE_LINEHAUL", "MISSORT",
    "ASSIGNED_NOT_LOADED", "DELIVERY_SCAN_SKIPPED", "RETURN_SCAN_SKIPPED", "CONTRACTOR_RETAINS", "UNRECORDED_HANDOFF",
    "RECIPIENT_UNAVAILABLE", "WRONG_ADDRESS", "WRONG_GATE", "OTP_NOT_RECEIVED", "NEIGHBOUR_RECEIVES", "MISDELIVERY",
    "LABEL_MISREAD", "WRONG_LABEL_APPLIED", "SCALE_DRIFT", "DECLARED_WEIGHT_WRONG", "MANIFEST_ERROR", "TRAFFIC_DISRUPTION",
    "CUSTOMER_COMPLAINT")}

# Truth labels live outside the repository and outside artifacts/ (addendum B1): <root>/<dataset_id>/.
# Override with SUHAIL_EVAL_TRUTH_ROOT or the export command's --truth-root. Backend and operations code never read it.
DEFAULT_TRUTH_ROOT = r"C:\Projects\suhail-eval-truth"
# The physical world state the Stage 4 operational simulator reads (parcel locations, device buffers, recipient
# availability) records what really happened, so causes can be worked out from it. It lives outside the repository
# too, in its own root that only the simulator opens: <root>/<export name>/<dataset_id>/<live split>/.
# Override with SUHAIL_SIM_STATE_ROOT or the export command's --state-root.
DEFAULT_STATE_ROOT = r"C:\Projects\suhail-sim-state"


def uniform_rates(history: float, live: float) -> tuple:
    """A rates tuple giving every scheduled mechanism the same rates (scaled-down test worlds)."""
    return tuple((m, float(history), float(live)) for m in sorted(MECHANISM_RATES))


@dataclass(frozen=True)
class WorldConfig:
    """Size, span and seed of one world.

    split_days: booking days per world split (history, development, held_out). Default for 9 days is the
    plan's 4/3/2 and for 8 days 4/3/1 (four history days, so history cases can be acted on and verified before
    the development window opens); otherwise history = days//3, held_out = max(1, days//6) and development the rest.
    Shipments are spread over booking days in proportion to a weekly demand profile.
    rates: per-mechanism over-sampling rates as ((mechanism, history_rate, live_rate), ...); None means the
    committed MECHANISM_RATES. The scheduler tops every scheduled mechanism up to
    max(1, round(rate * shipments in the split)) affected shipments per world split (scenario weighting, not
    real frequencies); every mechanism also has a real-frequency base rate that applies everywhere.
    """
    total: int = 600
    days: int = 8
    seed: int = 20261010
    dataset_id: str = "DEMO-SUHAIL-WORLD-1"
    start_date: str = "2026-09-10"          # local date of booking day 1 (a Thursday; development is Monday to Wednesday)
    split_days: tuple | None = None
    horizon_days: int = 4                    # simulated days after the last booking day
    session_start: str = "08:00"
    session_end: str = "20:00"
    reconciliation_grace_minutes: int = 60
    rates: tuple | None = None

    def __post_init__(self):
        if type(self.total) is not int or not 30 <= self.total <= 100_000:
            raise ValueError("total must be an integer between 30 and 100000")
        if type(self.days) is not int or not 3 <= self.days <= 60:
            raise ValueError("days must be an integer between 3 and 60")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        if not re.fullmatch(r"DEMO-[A-Z0-9-]+", self.dataset_id):
            raise ValueError("Dataset identity must explicitly be DEMO")
        date.fromisoformat(self.start_date)
        if self.split_days is None:
            if self.days in (8, 9):
                split = (4, 3, self.days - 7)
            else:
                history, held = max(1, self.days // 3), max(1, self.days // 6)
                split = (history, self.days - history - held, held)
            object.__setattr__(self, "split_days", split)
        split = tuple(self.split_days)
        if len(split) != 3 or any(type(v) is not int or v < 1 for v in split) or sum(split) != self.days:
            raise ValueError("split_days must be three positive day counts summing to days")
        object.__setattr__(self, "split_days", split)
        for value in (self.session_start, self.session_end):
            if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
                raise ValueError("Session bounds must be HH:MM")
        if self.session_start >= self.session_end:
            raise ValueError("Session must end after it starts")
        if type(self.horizon_days) is not int or not 2 <= self.horizon_days <= 14:
            raise ValueError("horizon_days must be between 2 and 14")
        rates = tuple(sorted(MECHANISM_RATES.items() if self.rates is None else ((m, (h, l)) for m, h, l in self.rates)))
        if self.rates is not None and {m for m, _ in rates} != set(MECHANISM_RATES):
            raise ValueError("rates must list every scheduled mechanism exactly once")
        if any(not (isinstance(v, float) and 0 <= v <= 1) for _, pair in rates for v in pair):
            raise ValueError("rates must be floats between 0 and 1")
        object.__setattr__(self, "rates", tuple((m, h, l) for m, (h, l) in rates))

    # ------------------------------------------------------------------ calendar
    @property
    def day1(self) -> date:
        return date.fromisoformat(self.start_date)

    @property
    def start_at(self) -> datetime:
        """UTC instant of local midnight on booking day 1."""
        return local_dt(self.day1, "00:00")

    @property
    def end_at(self) -> datetime:
        """UTC end of the simulated horizon (local midnight after the last horizon day)."""
        return local_dt(self.day1 + timedelta(days=self.days + self.horizon_days), "00:00")

    def booking_date(self, day: int) -> date:
        return self.day1 + timedelta(days=day - 1)

    def split_of_day(self, day: int) -> str:
        history, development, _ = self.split_days
        return "history" if day <= history else "development" if day <= history + development else "held_out"

    def days_of(self, split: str) -> list[int]:
        return [d for d in range(1, self.days + 1) if self.split_of_day(d) == split]

    def live_start(self, live_split: str) -> datetime:
        """Local midnight of the live split's first booking day: the live replay clock starts here."""
        return local_dt(self.booking_date(self.days_of(live_split)[0]), "00:00")

    def rate(self, mechanism: str, split: str) -> float:
        """Committed over-sampling rate of one mechanism in one world split (history, or a live split)."""
        history, live = next((h, l) for m, h, l in self.rates if m == mechanism)
        return history if split == "history" else live

    def target(self, mechanism: str, split: str, shipments: int) -> int:
        """Minimum shipments one mechanism must be the cause of a deviation on, in a split holding `shipments` shipments."""
        return max(1, int(self.rate(mechanism, split) * shipments + .5))

    def v2_config(self, counts: dict) -> "WorldV2Config":
        return WorldV2Config(total=sum(counts.values()), history=counts.get("history", 0),
                             development=counts.get("development", 0), held_out=counts.get("held_out", 0),
                             seed=self.seed, normal_fraction=.70, start_at=iso(self.start_at),
                             session_start=self.session_start, session_end=self.session_end,
                             reconciliation_grace_minutes=self.reconciliation_grace_minutes,
                             simulation_days=self.days + self.horizon_days, dataset_id=self.dataset_id)


@dataclass(frozen=True)
class WorldV2Config(Config):
    """The frozen V2 Config, except that an export may hold zero shipments in a split.

    A world export imports earlier booking days in full, feeds one split live and leaves later days out
    entirely, so its held_out count is zero (the foundation Config requires three positive counts).
    split_counts lists only non-empty splits, which is what validate_world compares against.
    normal_fraction is a foundation generator parameter that world-1 does not use (kept at .70).
    """

    def __post_init__(self):
        counts = (self.history, self.development, self.held_out)
        if (type(self.total) is not int or not 30 <= self.total <= 100_000
                or any(type(v) is not int or v < 0 for v in counts) or sum(counts) != self.total
                or self.history < 1 or self.development < 1):
            raise ValueError("World export needs history and development shipments summing to total")
        probe = Config(total=self.total, seed=self.seed, normal_fraction=self.normal_fraction, start_at=self.start_at,
                       session_start=self.session_start, session_end=self.session_end,
                       reconciliation_grace_minutes=self.reconciliation_grace_minutes,
                       simulation_days=self.simulation_days, dataset_id=self.dataset_id)
        del probe  # Every other field is validated exactly as the foundation contract does.

    @property
    def split_counts(self) -> dict[str, int]:
        return {k: v for k, v in zip(("history", "development", "held_out"), (self.history, self.development, self.held_out)) if v}


# ---------------------------------------------------------------------- time helpers
def local_dt(day: date, hhmm: str) -> datetime:
    """UTC instant of a local Saudi wall-clock time on a local date."""
    hour, minute = map(int, hhmm.split(":"))
    return datetime.combine(day, time(hour, minute), tzinfo=LOCAL).astimezone(UTC)


def local_date(when: datetime) -> date:
    return when.astimezone(LOCAL).date()


def local_hour(when: datetime) -> float:
    t = when.astimezone(LOCAL)
    return t.hour + t.minute / 60 + t.second / 3600


def at_local(when: datetime, hhmm: str, *, day_offset: int = 0) -> datetime:
    return local_dt(local_date(when) + timedelta(days=day_offset), hhmm)


def next_local(when: datetime, hhmm: str) -> datetime:
    """The first local hh:mm at or after `when`."""
    candidate = at_local(when, hhmm)
    return candidate if candidate >= when else at_local(when, hhmm, day_offset=1)


def is_friday(day: date) -> bool:
    return day.weekday() == 4


def floor_seconds(when: datetime) -> datetime:
    return when.replace(microsecond=0)
