"""The Strategy Registry — the airlock between Atlas (research) and the execution
bot. Atlas writes approved, versioned strategies (human-gated at every
capital-bearing step); the bot reads a read-only export and executes only those.
"""
from .registry import Registry, RegistryError
from .consumer import BotStub

__all__ = ["Registry", "RegistryError", "BotStub"]
