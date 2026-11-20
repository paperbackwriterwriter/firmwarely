"""Cloudflare Pages output: the site as Vercel serves it, plus _headers and _redirects.

    python3 scripts/cf_pages.py [dist]     # the Cloudflare Pages build command

vercel.json stays the one source of truth. The hourly workflow rewrites its redirects
(build_pages.write_redirects) and commits it; this script turns it into Cloudflare's two
files on every Cloudflare build, so the rules can never drift from the pages. build_pages
also writes the two files at the repo root through write_config(), for a local look; those
copies are gitignored, because the workflow only commits the files it names and a tracked
file it leaves modified would stop its `git rebase`.

The build copies the site into its own folder (dist/) and leaves out what was never meant to
be public: the code (api/, lib/, scripts/, functions/), CI config, docs, and the JSON state
files. Of the JSON files only devices.json is read by the pages, so it is the one that ships.
Pages Functions are not affected: Cloudflare reads functions/ from the repo root.

Vercel `redirects` sources like /devices/:id(a|b|c) are regexes Cloudflare does not
understand, so each alternative becomes a static line of its own (see redirect_lines for
how the slashless spelling is covered). Cloudflare allows 2,000 static and 100 dynamic
lines; the build fails rather than publish a set Cloudflare would silently cut short.
"""
import json, os, re, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MAX_STATIC, MAX_DYNAMIC = 2000, 100

# Top-level names never copied to the output. Anything starting with "." is skipped too.
PRIVATE = {"api", "lib", "scripts", "functions", "docs", "node_modules", "dist", "rendered",
           "README.md", "vercel.json", "wrangler.toml", "package.json", "package-lock.json",
           "digest.md", "_headers", "_redirects", "_routes.json"}
# The only JSON a page fetches (index.html, my-devices.html, dashboard.html: fetch("/devices.json")).
PUBLIC_JSON = {"devices.json"}
SKIP_ANYWHERE = {"__pycache__", ".DS_Store"}
SKIP_SUFFIXES = {".py", ".pyc", ".mjs", ".md", ".toml"}

# Root pages Vercel serves at their .html address. Cloudflare would 308 those to the
# extensionless form; a 200 rewrite keeps the address people and the API's redirects use.
HTML_PAGES = ("my-devices.html", "dashboard.html")

GROUP = re.compile(r"^(/[^:()*]*?)/:\w+\(([^()]*)\)(/?)$")


def expand(source):
    """A Vercel source as (literal paths it matches, folder prefix if it was a group), or None."""
    if not re.search(r"[:()*]", source):
        return [source], None
    m = GROUP.match(source)
    if not m or not re.fullmatch(r"[A-Za-z0-9._~|-]+", m.group(2)):
        return None
    return [f"{m.group(1)}/{alt}{m.group(3)}" for alt in m.group(2).split("|")], m.group(1)


def redirect_lines(cfg):
    """vercel.json -> _redirects lines.

    Spelling every group alternative out twice (/devices/x and /devices/x/) comes to ~2,800
    static lines, over Cloudflare's 2,000. So a group gives only its /x/ lines, and one
    dynamic line per folder sends any /folder/x without the slash to /folder/x/, where the
    static line (or the page) answers. Static lines always win over dynamic ones on
    Cloudflare, so the exact rules (permanent moves, family models) keep both spellings and
    answer in one hop. A file sitting directly in such a folder (devices/index.html) gets a
    static line of its own, or the slash rule would send it to /devices/index.html/.
    """
    if cfg.get("rewrites") or cfg.get("cleanUrls") or cfg.get("trailingSlash") is not None:
        raise SystemExit("vercel.json has rewrites/cleanUrls/trailingSlash: teach scripts/cf_pages.py about them")
    lines, seen, folders = [], set(), []
    for r in cfg.get("redirects", []):
        got = expand(r["source"])
        if got is None:
            raise SystemExit(f"cf_pages: can't express Vercel source {r['source']!r} for Cloudflare")
        paths, folder = got
        if re.search(r"[:*]", r["destination"]):
            raise SystemExit(f"cf_pages: destination with a placeholder: {r['destination']!r}")
        if folder is not None:
            if folder not in folders:
                folders.append(folder)
            paths = [p for p in paths if p.endswith("/")]   # the slashless twin: the folder rule
        # Vercel: permanent -> 308, temporary -> 307. The owner asked for the classic 301/302;
        # for a GET (all a browser or crawler sends to these) they behave the same.
        code = 301 if r.get("permanent", True) else 302
        for p in paths:
            if p in seen:
                continue                    # first match wins on both platforms
            seen.add(p)
            lines.append(f"{p} {r['destination']} {code}")
    for page in HTML_PAGES:
        if (ROOT / page).is_file() and f"/{page}" not in seen:
            lines.append(f"/{page} /{page[:-5]} 200")
    for folder in folders:
        here = ROOT / folder.strip("/")
        for f in sorted(here.glob("*")) if here.is_dir() else []:
            if f.is_file() and f"{folder}/{f.name}" not in seen:
                target = f"{folder}/" if f.name == "index.html" else f"{folder}/{f.name}"
                lines.append(f"{folder}/{f.name} {target} 200")
        lines.append(f"{folder}/:name {folder}/:name/ 301")
    dynamic = [l for l in lines if re.search(r"[:*]", l.split()[0])]
    static = len(lines) - len(dynamic)
    if static > MAX_STATIC or len(dynamic) > MAX_DYNAMIC:
        raise SystemExit(f"cf_pages: {static} static / {len(dynamic)} dynamic redirects "
                         f"is over Cloudflare's {MAX_STATIC}/{MAX_DYNAMIC} limit")
    return lines


def headers_text(cfg):
    out = []
    for block in cfg.get("headers", []):
        if block["source"] != "/(.*)":
            raise SystemExit(f"cf_pages: header source {block['source']!r} needs translating by hand")
        out.append("/*")
        out += [f"  {h['key']}: {h['value']}" for h in block["headers"]]
        # Pages adds this to every static file; Vercel doesn't. Keep devices.json same-origin.
        out.append("  ! Access-Control-Allow-Origin")
    return "\n".join(out) + "\n"


def write_config(folder, cfg=None):
    """Write _headers and _redirects for vercel.json into `folder`. Returns the rule count."""
    cfg = cfg if cfg is not None else json.loads((ROOT / "vercel.json").read_text())
    lines = redirect_lines(cfg)
    folder = Path(folder)
    (folder / "_redirects").write_text(
        "# Generated from vercel.json by scripts/cf_pages.py. Do not edit: edit vercel.json / redirects.json.\n"
        + "\n".join(lines) + "\n")
    (folder / "_headers").write_text(
        "# Generated from vercel.json by scripts/cf_pages.py. Do not edit.\n" + headers_text(cfg))
    return len(lines)


def public(rel):
    parts = rel.parts
    if any(p.startswith(".") or p in SKIP_ANYWHERE for p in parts):
        return False
    if parts[0] in PRIVATE:
        return False
    if rel.suffix in SKIP_SUFFIXES:
        return False
    if len(parts) == 1 and rel.suffix == ".json" and rel.name not in PUBLIC_JSON:
        return False
    return True


def build(out):
    out = Path(out)
    if not out.is_absolute():
        out = ROOT / out
    if out == ROOT or ROOT not in out.parents:
        raise SystemExit("cf_pages: the output folder must be inside the repo, and not the repo itself")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    copied = 0
    top = out.relative_to(ROOT).parts[0]
    for dirpath, dirs, files in os.walk(ROOT):
        here = Path(dirpath).relative_to(ROOT)
        # prune private folders (and .git) instead of walking through them
        dirs[:] = sorted(d for d in dirs if d != top and public(here / d / "x.html"))
        for name in sorted(files):
            rel = here / name
            if not public(rel):
                continue
            dest = out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dest)
            copied += 1
    n = write_config(out)
    print(f"cf_pages: {copied} files into {out.relative_to(ROOT)}/, {n} redirect lines, _headers")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "dist")
