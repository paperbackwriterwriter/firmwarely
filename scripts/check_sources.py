#!/usr/bin/env python3
"""
Check every source in sources.json actually resolves, without writing anything.

Runs the same check_* functions as the nightly fetcher, in parallel, and reports what
each source returned. Nothing is fetched twice and no file is touched, so it is safe to
run on a pull request.

  python3 scripts/check_sources.py            # all sources
  python3 scripts/check_sources.py --only id1,id2

Exit code is 1 only for a source that is definitively wrong — a GitHub repo that does not
exist or has no stable release. Timeouts, rate limits and vendor pages that reject CI
runners come and go on their own, so they are reported but never fail the run.
"""
import json, os, sys, concurrent.futures as cf
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch

WORKERS = 12
HARD = "no repo or no stable release"   # the message check_github raises for a 404


def check(src):
    """-> (src, status, detail) where status is ok | skipped | soft | hard."""
    if src["type"] == "manual":
        return src, "skipped", "not tracked"
    if src["type"] == "browser" and not (fetch.RENDERED / (src["id"] + ".html")).exists():
        return src, "skipped", "needs scripts/fetch_browser.py first"
    try:
        if src["type"] == "github":
            r = fetch.check_github(src)
        elif src["type"] == "feed":
            r = fetch.check_feed(src)
        else:
            r = fetch.check_html(src, {})
        return src, "ok", f"{r['version']} ({r['released']})"
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:150]}"
        return src, "hard" if HARD in str(e) else "soft", msg


def main():
    only = None
    for i, a in enumerate(sys.argv):
        if a == "--only" and i + 1 < len(sys.argv):
            only = {x.strip() for x in sys.argv[i + 1].split(",") if x.strip()}
    srcs = json.loads((fetch.ROOT / "sources.json").read_text())["devices"]
    if only:
        srcs = [s for s in srcs if s["id"] in only]
        missing = only - {s["id"] for s in srcs}
        if missing:
            print(f"no such device id: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    results = []
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for src, status, detail in ex.map(check, srcs):
            results.append((src, status, detail))
            if status in ("hard", "soft"):
                print(f"  {status.upper():4s} {src['id']:44s} {detail}")

    counts = {k: sum(1 for _, s, _ in results if s == k) for k in ("ok", "skipped", "soft", "hard")}
    print(f"\n{len(results)} sources: {counts['ok']} ok, {counts['hard']} broken, "
          f"{counts['soft']} unreachable this run, {counts['skipped']} not tracked")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = [f"### Source check — {counts['ok']} ok, {counts['hard']} broken, "
                 f"{counts['soft']} unreachable, {counts['skipped']} not tracked", ""]
        for label, key, note in (("Broken", "hard", "the entry is wrong — fix `repo`/`url` or set `type: \"manual\"`"),
                                 ("Unreachable this run", "soft", "transient: timeout, rate limit, or a page that blocks CI")):
            rows = [(s, d) for s, st, d in results if st == key]
            if not rows:
                continue
            lines += [f"**{label}** — {note}", "", "| device | type | detail |", "| --- | --- | --- |"]
            for s, d in rows:
                lines.append("| `%s` | %s | %s |" % (s["id"], s["type"], d.replace("|", r"\|")))
            lines.append("")
        if not counts["hard"] and not counts["soft"]:
            lines.append("Every tracked source resolved. ✅")
        Path(summary).write_text("\n".join(lines) + "\n")

    return 1 if counts["hard"] else 0


if __name__ == "__main__":
    sys.exit(main())
