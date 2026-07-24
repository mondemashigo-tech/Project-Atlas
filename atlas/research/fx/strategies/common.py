"""Shared strategy helpers."""
from __future__ import annotations

import pandas as pd


def session_weekday_mask(entry_df: pd.DataFrame, cfg: dict) -> pd.Series:
    """Boolean per-bar mask: True where the bar falls inside the configured
    session window and on an allowed weekday. Honors session.data_utc_offset,
    which shifts broker-server-time stamps back to true UTC first. If no session
    block is present, every bar is tradeable."""
    sess = cfg.get("session")
    if not sess:
        return pd.Series(True, index=entry_df.index)
    tz = sess.get("tz", "UTC")
    data_offset = sess.get("data_utc_offset", 0)
    local = (entry_df.index - pd.Timedelta(hours=data_offset)).tz_convert(tz)
    start = pd.to_datetime(sess["start"]).time()
    end = pd.to_datetime(sess["end"]).time()
    in_sess = pd.Series([start <= t.time() < end for t in local], index=entry_df.index)
    wd = pd.Series(local.weekday, index=entry_df.index)
    allowed = set(cfg.get("weekdays", [0, 1, 2, 3, 4]))
    return in_sess & wd.isin(allowed)
