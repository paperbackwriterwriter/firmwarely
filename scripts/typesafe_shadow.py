#!/usr/bin/env python3
"""
Shadow test: would TypeSafe's Jev judge releases better than our regexes?

Two decisions on the site come from keyword regexes in scripts/fetch.py:
  - SECURITY: a release that fixes a vulnerability becomes "critical fix" and the
    subscriber's email says "Security fix". Wording like "security" or "hardening" in
    vendor boilerplate trips it; a fix described without those words is missed.
  - EOL: a vendor saying updates are stopping becomes an end-of-life notice.

For every release in pending_changes.json not judged yet, this asks Jev both as yes/no
questions (Noul) in one request and records its probabilities next to what the regexes
said, in typesafe_shadow.json (committed). It changes nothing else: status, pages and
emails still come from the regexes. scripts/digest.py lists the disagreements in the
daily issue so they can be read before anything switches over.

    python3 scripts/typesafe_shadow.py            # judge new releases (hourly run)
    python3 scripts/typesafe_shadow.py --probe    # one known example: checks key and contract
    python3 scripts/typesafe_shadow.py --report   # agreement so far

Env: TYPESAFE_API_KEY (GitHub secret). Without it the script does nothing and exits 0.
API: https://docs.typesafe.ai/api — POST /v1/systemone, standard library only, no SDK.
Never fails the run: an error or timeout skips that release, which is retried next hour.
"""
import json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "typesafe_shadow.json"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
MAX_PER_RUN = 40      # a normal hour has a handful of releases; a backlog drains over a few runs
TIMEOUT = 20
# Reporting only (the real cut-off gets chosen from this data). A Noul is the probability of
# yes, so the middle band is "unsure" rather than a weak yes: docs.typesafe.ai/primitives/noul.
YES, NO = 0.8, 0.2

QUESTIONS = {
    "security_fix": {
        "type": "noul",
        "instructions": "Do `release_notes` say that this release of `product` fixes a security "
                        "vulnerability in `product` itself?",
        "criteria": {
            "true": "The notes describe fixing a security problem in this product in this release: "
                    "a CVE, a vulnerability, an exploit, an authentication or permission bypass, "
                    "remote code execution, or a similar security flaw.",
            "false": "The notes describe features, bug fixes, performance or dependency updates, or "
                     "mention security only generally (advice to keep firmware updated, a security "
                     "setting or feature, boilerplate) without saying this release fixes a flaw.",
        },
    },
    # the same question without criteria: the Noul guide suggests trying both on real data
    # and keeping whichever does better; questions in one request run in parallel
    "security_fix_plain": {
        "type": "noul",
        "instructions": "Do `release_notes` say that this release of `product` fixes a security "
                        "vulnerability in `product` itself?",
    },
    "end_of_life": {
        "type": "noul",
        "instructions": "Do `release_notes` say that `product` has reached end of life, or that the "
                        "vendor has stopped or will stop providing updates for it?",
        "criteria": {
            "true": "The vendor says updates or support for this product are ending or have ended.",
            "false": "Nothing says updates or support for this product are ending.",
        },
    },
}


def state_for(rec):
    return {"product": fetch.full_name(rec), "version": rec.get("version") or "",
            "previous_version": rec.get("previous") or "", "release_notes": rec.get("notes") or ""}


def ask(state, key, tries=3):
    """One request, both questions. Returns (answers dict, model) or raises."""
    body = json.dumps({"state": state, "model": MODEL, "questions": QUESTIONS}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": fetch.UA})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            return {q: float(a["noul"]) for q, a in data["answers"].items()}, data.get("model")
        except urllib.error.HTTPError as e:
            # 429 rate limit / 529 overloaded: back off and retry, as the API docs ask
            if e.code in (429, 529) and attempt < tries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from None


def regex_verdicts(rec):
    text = f"{rec.get('notes', '')} {rec.get('version', '')}"
    security = bool(fetch.SECURITY.search(text))
    return {"security_fix": security, "security_fix_plain": security,
            "end_of_life": bool(fetch.EOL.search(rec.get("notes") or ""))}


def verdict(p):
    """A Noul as yes / no / unsure."""
    return "yes" if p >= YES else "no" if p <= NO else "unsure"


def load_log():
    try:
        data = json.loads(LOG.read_text())
        if isinstance(data.get("judged"), list):
            return data
    except Exception:
        pass
    return {"_readme": "TypeSafe shadow test; see scripts/typesafe_shadow.py. Nothing here changes the site.",
            "judged": []}


def judge_pending(key, pending=None, log=None, asker=ask):
    pending = pending if pending is not None else fetch.load_pending()
    log = log if log is not None else load_log()
    done = {(j["id"], j["version"]) for j in log["judged"]}
    todo = [r for r in pending.get("devices", {}).values()
            if r.get("version") and (r["id"], r["version"]) not in done]
    if pending.get("forced"):
        todo = []   # a forced test run marks everything changed; not real releases
    judged = failed = 0
    for rec in todo[:MAX_PER_RUN]:
        try:
            answers, model = asker(state_for(rec), key)
        except Exception as e:
            failed += 1
            print(f"  typesafe: {rec['id']} {rec['version']}: {e}", file=sys.stderr)
            continue
        log["judged"].append({
            "id": rec["id"], "version": rec["version"], "name": fetch.full_name(rec),
            "judged_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "notes_chars": len(rec.get("notes") or ""), "model": model,
            "regex": regex_verdicts(rec), "jev": {q: round(p, 4) for q, p in answers.items()}})
        judged += 1
    return log, judged, failed, max(len(todo) - MAX_PER_RUN, 0)


def disagreements(entries, questions=("security_fix", "end_of_life")):
    """(entry, question, kind): kind "differs" when Jev is confident and the regex says the
    opposite, "unsure" when Jev is in the middle band."""
    out = []
    for j in entries:
        for q in questions:
            if q not in j["jev"]:
                continue
            v = verdict(j["jev"][q])
            if v == "unsure":
                out.append((j, q, "unsure"))
            elif (v == "yes") != j["regex"][q]:
                out.append((j, q, "differs"))
    return out


def report(entries):
    lines = [f"{len(entries)} release(s) judged. Jev yes >= {YES}, no <= {NO}, unsure between."]
    for q in QUESTIONS:
        both = [j for j in entries if q in j["jev"]]
        vs = [verdict(j["jev"][q]) for j in both]
        agree = sum(v != "unsure" and (v == "yes") == j["regex"][q] for v, j in zip(vs, both))
        lines.append(f"  {q}: agree {agree}/{len(both)}, differ {sum(v != 'unsure' for v in vs) - agree}, "
                     f"unsure {vs.count('unsure')}; regex yes {sum(j['regex'][q] for j in both)}, "
                     f"Jev yes {vs.count('yes')}")
    for j, q, kind in disagreements(entries, tuple(QUESTIONS)):
        lines.append(f"  - {kind}: {j['name']} {j['version']}: {q} regex={'yes' if j['regex'][q] else 'no'}, "
                     f"Jev={j['jev'][q]:.2f}")
    return "\n".join(lines)


PROBE = {"id": "probe", "brand": "Acme", "model": "Router", "version": "2.1.4", "previous": "2.1.3",
         "notes": "Fixes CVE-2026-1234, an authentication bypass in the web admin interface that let "
                  "unauthenticated users change settings. Also improves Wi-Fi stability."}


def main():
    key = os.environ.get("TYPESAFE_API_KEY")
    if "--report" in sys.argv:
        print(report(load_log()["judged"]))
        return 0
    if not key:
        print("typesafe: no TYPESAFE_API_KEY, shadow test skipped")
        return 0
    if "--probe" in sys.argv:
        answers, model = ask(state_for(PROBE), key)
        print(f"typesafe probe ({model}): {answers}")
        ok = answers.get("security_fix", 0) >= YES and answers.get("end_of_life", 1) <= NO
        print("probe: as expected" if ok else "probe: UNEXPECTED answers for a clear CVE fix")
        return 0 if ok else 1
    log, judged, failed, left = judge_pending(key)
    if judged:
        LOG.write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print(f"typesafe shadow: judged {judged}, failed {failed}, {left} left for the next run")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:   # the shadow test must never stop the firmware check
        print(f"typesafe shadow: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(0 if "--probe" not in sys.argv else 1)
