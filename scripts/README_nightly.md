# Atlas nightly autopilot

`atlas_nightly.ps1` runs the lab unattended: refresh data → discover forex ideas
from the web and test them → sweep the core hypotheses through the governed loop.
Results land in the vault; open the dashboard in the morning to review.

**Nothing here ever promotes to capital.** Discovery and the loop stop at the
research gates — capital-bearing status stays human-gated inside Atlas.

## Run it once by hand (to see it work)

```
cd C:\Users\monde\Atlas-Lab
powershell -ExecutionPolicy Bypass -File .\scripts\atlas_nightly.ps1
```

## Schedule it every night at 02:00

Run this once (Command Prompt or PowerShell). It registers a Windows Task that
runs as you, so it inherits your `ANTHROPIC_API_KEY`:

```
schtasks /Create /TN "AtlasNightly" /SC DAILY /ST 02:00 /F ^
  /TR "powershell -ExecutionPolicy Bypass -File C:\Users\monde\Atlas-Lab\scripts\atlas_nightly.ps1"
```

Check / run / remove it:

```
schtasks /Query  /TN "AtlasNightly"
schtasks /Run    /TN "AtlasNightly"
schtasks /Delete /TN "AtlasNightly" /F
```

## Notes

- **Data refresh needs MetaTrader open.** If the terminal is closed the export
  step is skipped and the loop runs on the data already on disk — the run still
  completes.
- **Discovery needs `ANTHROPIC_API_KEY`.** If it isn't set, that step is skipped
  and only the loop runs.
- **Logs** are written to `vault\logs\nightly_<timestamp>.log`.
- **Cost:** each night makes a handful of Claude calls for discovery (search +
  one read per article). Cents per night at these settings, not free. Trim the
  `$Discover` list in the script to spend less.
- **Timezone offset** defaults to `3` (London sessions). Override by setting
  `ATLAS_DATA_UTC_OFFSET` before the run.
