"""world-1: a mechanism-based synthetic Saudi logistics world (Stage 1 of the Suhail mission).

Two layers, strictly apart:
  physical   private discrete-event simulation (where every parcel really is, what really happened)
  observe    what devices, people and systems recorded, and when the gateway received it (V2 evidence)

Everything is synthetic and labelled synthetic. Nothing here reads a clock, the network or a model.
"""
from world.config import WorldConfig, WORLD_VERSION

__all__ = ["WorldConfig", "WORLD_VERSION"]
