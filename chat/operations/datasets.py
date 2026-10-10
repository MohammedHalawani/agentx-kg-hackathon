"""Which databases and datasets the operations layer may run on, and how a frozen dataset configuration is read.

The fixed development databases keep their exact-name allowlist. A mechanism-world database is accepted by its
name pattern (shipments-v2-world-<name>) and may hold a mechanism-world dataset only; a mechanism-world dataset
may live only in such a database or in a scratch test database. Nothing here loosens a rule for any other name.

A world export imports earlier booking days, feeds one split live and leaves later days out, so its frozen V2
configuration has an empty held-out split, which the foundation Config refuses. WorldExportConfig accepts exactly
that and validates every other field as the foundation contract does. This module never imports the world
generator: the operations layer reads only what was imported or fed.
"""
from dataclasses import dataclass
import re

from dataset_v2.contracts import Config

# The foundation replay database and the live provider-feed database (plus its isolated test twins).
OPERATIONS_DATABASES = ("shipments-v2-demo", "shipments-v2-demo-live", "shipments-v2-demo-test", "shipments-v2-demo-test2",
                        "shipments-v2-demo-ci-test")  # ci-test: scratch database for the Neo4j integration tests
# Scratch databases the integration tests recreate; a mechanism-world dataset may be imported there for tests.
SCRATCH_DATABASES = ("shipments-v2-demo-test", "shipments-v2-demo-test2", "shipments-v2-demo-ci-test")
WORLD_DATABASE = re.compile(r"shipments-v2-world-[a-z0-9-]+")
READ_DATABASE = re.compile(r"shipments-v2-demo(?:-[a-z0-9-]+)?")
LIVE_DATASET_PREFIX = "DEMO-SUHAIL-LIVE"
WORLD_DATASET_PREFIX = "DEMO-SUHAIL-WORLD"   # The same prefix dataset_v2.feed widens the gateway's kinds for.


def is_world_database(name):
    return isinstance(name, str) and WORLD_DATABASE.fullmatch(name) is not None


def is_world_dataset(dataset_id):
    return isinstance(dataset_id, str) and dataset_id.startswith(WORLD_DATASET_PREFIX)


def is_feed_dataset(dataset_id):
    """Datasets whose live observations arrive only through the provider gateway (never by replaying imports)."""
    return isinstance(dataset_id, str) and dataset_id.startswith((LIVE_DATASET_PREFIX, WORLD_DATASET_PREFIX))


def operations_database_allowed(name):
    """A database the operations ledger may be written to: the fixed allowlist, or a mechanism-world database."""
    return isinstance(name, str) and (name in OPERATIONS_DATABASES or is_world_database(name))


def read_database_allowed(name):
    """A database the read model may query: the isolated V2 family, or a mechanism-world database."""
    return isinstance(name, str) and (READ_DATABASE.fullmatch(name) is not None or is_world_database(name))


def pairing_error(database, dataset_id):
    """Why this dataset may not be operated in this database, or None. World data and world databases go together;
    the only other place a world dataset may be is a scratch test database."""
    world_db, world_data = is_world_database(database), is_world_dataset(dataset_id)
    if world_db and not world_data:
        return "A mechanism-world database holds a mechanism-world dataset only"
    if world_data and not world_db and database not in SCRATCH_DATABASES:
        return "A mechanism-world dataset runs only in a shipments-v2-world- database (or a scratch test database)"
    return None


def dataset_kind(dataset_id):
    return "mechanism_world" if is_world_dataset(dataset_id) else "live_network" if is_feed_dataset(dataset_id) else "foundation"


@dataclass(frozen=True)
class WorldExportConfig(Config):
    """The frozen V2 Config of a mechanism-world export: history and development are required, held-out may be
    empty (later booking days are not part of the export). Field for field the same record as Config, so
    dataclasses.asdict() equals the imported manifest's config block."""

    def __post_init__(self):
        counts = (self.history, self.development, self.held_out)
        if (type(self.total) is not int or not 30 <= self.total <= 100_000
                or any(type(v) is not int or v < 0 for v in counts) or sum(counts) != self.total
                or self.history < 1 or self.development < 1):
            raise ValueError("A world export needs history and development shipments summing to total")
        # Every other field is validated exactly as the foundation contract does.
        Config(total=self.total, seed=self.seed, normal_fraction=self.normal_fraction, start_at=self.start_at,
               session_start=self.session_start, session_end=self.session_end,
               reconciliation_grace_minutes=self.reconciliation_grace_minutes,
               simulation_days=self.simulation_days, dataset_id=self.dataset_id)

    @property
    def split_counts(self):
        return {k: v for k, v in zip(("history", "development", "held_out"), (self.history, self.development, self.held_out)) if v}


def dataset_config(values):
    """The Config for an imported manifest's config block: the foundation Config, or the world export Config for a
    mechanism-world dataset (the only datasets allowed an empty held-out split)."""
    if not isinstance(values, dict):
        raise ValueError("Manifest configuration must be an object")
    if is_world_dataset(values.get("dataset_id")):
        return WorldExportConfig(**values)
    return Config(**values)
