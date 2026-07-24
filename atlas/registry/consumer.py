"""Stub execution consumer.

This stands in for the future execution engine (the bot). It reads the Registry's
read-only export and reports what it *would* execute — it never places an order,
never touches a broker, never reaches back into research. It exists to prove the
airlock contract: the bot's entire world is `Registry.export_json()`.
"""
from __future__ import annotations

from typing import List


class BotStub:
    def __init__(self, name: str = "bot-stub"):
        self.name = name

    def plan(self, export: List[dict]) -> List[str]:
        """Given the registry export, return a human-readable execution plan.
        Executes nothing."""
        if not export:
            return [f"[{self.name}] nothing approved to execute — idle."]
        lines = [f"[{self.name}] would execute {len(export)} approved strateg"
                 f"{'y' if len(export)==1 else 'ies'} (NO ORDERS PLACED):"]
        for e in export:
            lines.append(
                f"  - {e['strategy_id']} [{e['status']}] alloc={e['allocation']} "
                f"risk={e['risk_limits'] or '{}'} spec_keys={list(e['spec'].keys())}")
        return lines
