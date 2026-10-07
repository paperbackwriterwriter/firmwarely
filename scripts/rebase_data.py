#!/usr/bin/env python3
"""
Put this run's data on top of a branch that moved while the run was checking sources.

The hourly run commits generated pages and data. When a pull request merges during the run,
`git pull --rebase` conflicts on those generated files and the run fails (2026-10-07 11:17).
Hand-merging generated HTML is never right, so instead the workflow saves this run's data,
resets to the branch as it now is, and calls this script; then it re-applies the hand edits
(catalog_edits.py) and rebuilds every page with the merged code.

    python3 scripts/rebase_data.py SAVED_DIR

SAVED_DIR holds this run's copies of DATA. The run's checks win for the files only it writes;
the catalogue files are merged, so a device or source added by the merged change survives:
  - sources.json: the branch's list, plus sources only this run has (discovery adds)
  - devices.json: this run's records (fresh versions), plus devices only the branch has
"""
import json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_OWNS = ["pending_changes.json", "weekly_changes.json", "digest_state.json", "typesafe_shadow.json"]
MERGED = ["sources.json", "devices.json"]
DATA = RUN_OWNS + MERGED


def union(base, extra):
    """base's entries, then extra's entries whose id base doesn't have, in their order."""
    have = {d["id"] for d in base}
    return base + [d for d in extra if d["id"] not in have]


def rebase(saved, root=ROOT):
    saved = Path(saved)
    for name in RUN_OWNS:
        if (saved / name).exists():
            shutil.copyfile(saved / name, root / name)
    for name, run_first in (("sources.json", False), ("devices.json", True)):
        if not (saved / name).exists():
            continue
        run = json.loads((saved / name).read_text())
        branch = json.loads((root / name).read_text()) if (root / name).exists() else {"devices": []}
        doc = dict(run) if run_first else dict(branch)
        doc["devices"] = (union(run["devices"], branch["devices"]) if run_first
                          else union(branch["devices"], run["devices"]))
        (root / name).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(rebase(sys.argv[1]))
