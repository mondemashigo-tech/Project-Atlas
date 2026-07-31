"""The capital gate — the single authorization point before any order.

Hard rules (vNext spec 21.3):
- No live order unless live capital is explicitly enabled for this instance.
- A kill switch, once active, blocks ALL orders (even simulated) and **persists
  across restarts** — it lives in a file, not memory, and stays active until
  explicitly cleared.
- Every decision is returned with a reason so it can be audited.

This gate does not itself send anything; it says yes or no. The executor must
consult it before every order and honour a `False`.
"""
from __future__ import annotations

import json
import os
from typing import Optional, Tuple

from .broker import AccountMode, OrderRequest


class GateError(Exception):
    pass


class CapitalGate:
    def __init__(self, root: str = ".", live_enabled: bool = False):
        self.root = root
        self.live_enabled = live_enabled          # must be True for MICRO_LIVE/LIVE
        self._ks_path = os.path.join(root, "execution", "killswitch.json")

    # -- kill switch (persistent) ------------------------------------------
    def _read_ks(self) -> dict:
        try:
            with open(self._ks_path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {"active": False}

    def kill_switch_active(self) -> bool:
        return bool(self._read_ks().get("active"))

    def activate_kill_switch(self, reason: str = "manual") -> None:
        from ..schemas import utcnow_iso
        os.makedirs(os.path.dirname(self._ks_path), exist_ok=True)
        with open(self._ks_path, "w", encoding="utf-8") as f:
            json.dump({"active": True, "reason": reason, "at": utcnow_iso()}, f)

    def clear_kill_switch(self, cleared_by: str = "human") -> None:
        from ..schemas import utcnow_iso
        os.makedirs(os.path.dirname(self._ks_path), exist_ok=True)
        with open(self._ks_path, "w", encoding="utf-8") as f:
            json.dump({"active": False, "cleared_by": cleared_by,
                       "at": utcnow_iso()}, f)

    # -- the authorization decision ----------------------------------------
    def authorize(self, mode: AccountMode,
                  req: Optional[OrderRequest] = None) -> Tuple[bool, str]:
        """Return (allowed, reason). Called before EVERY order attempt."""
        if self.kill_switch_active():
            return (False, "kill switch active")
        if mode.sends_orders and not self.live_enabled:
            return (False, f"live capital not enabled for {mode.value} "
                           "(explicit approval + enable required)")
        return (True, "")

    def require(self, mode: AccountMode, req: Optional[OrderRequest] = None) -> None:
        """Raise GateError unless the order is authorized."""
        ok, reason = self.authorize(mode, req)
        if not ok:
            raise GateError(reason)
