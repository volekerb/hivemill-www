#!/usr/bin/env python3
"""Catalog generator for hivemill-www.

Derives catalog/catalog.json from a read-only checkout of volekerb/hivemill at
a pinned commit. Nothing outside the checkout is read; the only network use is
`verify-snippets --network`. Python 3 stdlib only.

Subcommands
  build           --src CHECKOUT [--out catalog/catalog.json] [--overrides FILE]
  check           --src CHECKOUT [--catalog FILE] [--overrides FILE]
  verify-snippets --src CHECKOUT [--catalog FILE] [--network]

Exit codes: 0 ok, 1 drift / failed derivation / broken snippet, 2 usage error.

JSON schema (schemaVersion 1; consumed by the `render` subcommand)
  {
    "schemaVersion": 1,
    "source": {"repo": "volekerb/hivemill", "sha": "<40 hex>"},
    "items": [Item, ...]          # sorted by kind, then name, then id
  }
  Item (all kinds):
    id        str   "<kind>:<name>" (skill ids are "skill:<plugin-name>/<skill>")
    kind      str   "dashboard" | "plugin" | "role" | "skill"
    name      str
    purpose   str   one line, derived from the source file (never hand-written)
    snippets  [str] copy/install lines, in order
    path      str   source path inside the hivemill repo
    icon, media     optional; only these two keys may come from
                    catalog/overrides.json ({"<item id>": {"icon": ..., "media": ...}})
  role extra:   skills  [{"name", "purpose"}] from roles/plugins/<name>/*/skills/*/SKILL.md
  skill extra:  plugin (str, plugin.json name), bins [str] (files in the plugin's bin/)
  plugin extra: bins [str]
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

REPO = "volekerb/hivemill"
SCHEMA_VERSION = 1
OVERRIDE_KEYS = ("icon", "media")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CATALOG = os.path.join(ROOT, "catalog", "catalog.json")
DEFAULT_OVERRIDES = os.path.join(ROOT, "catalog", "overrides.json")


class CatalogError(Exception):
    """Derivation or verification failed (exit 1)."""


class UsageError(Exception):
    """Bad input from the caller (exit 2)."""


# ---------------------------------------------------------------- helpers

def read(src, rel):
    path = os.path.join(src, rel)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise CatalogError("cannot read %s in checkout: %s" % (rel, exc))


def read_json(src, rel):
    try:
        return json.loads(read(src, rel))
    except json.JSONDecodeError as exc:
        raise CatalogError("%s is not valid JSON: %s" % (rel, exc))


def subdirs(src, rel):
    path = os.path.join(src, rel)
    if not os.path.isdir(path):
        return []
    return sorted(d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)))


def files(src, rel):
    path = os.path.join(src, rel)
    if not os.path.isdir(path):
        return []
    return sorted(f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f)))


def head_sha(src):
    if not os.path.isdir(src):
        raise UsageError("--src %s is not a directory" % src)
    try:
        out = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True,
                             text=True, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise UsageError("--src %s is not a git checkout: %s" % (src, exc))
    return out.stdout.strip()


def first_sentence(text):
    text = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(?:\s|$)", text)
    return m.group(1) if m else text


def strip_links(text):
    return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)


def front_matter(text):
    """Return the simple key: value pairs of a leading --- block."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    data, key = {}, None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val in (">", "|", ">-", "|-"):
                val = ""
            elif len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            data[key] = val
        elif key and line.startswith((" ", "\t")):
            data[key] = (data[key] + " " + line.strip()).strip()
    return data


def skill_meta(src, rel, dirname):
    fm = front_matter(read(src, rel))
    desc = fm.get("description", "").strip()
    if not desc:
        raise CatalogError("%s has no front-matter description" % rel)
    return fm.get("name") or dirname, first_sentence(desc)


# ---------------------------------------------------------------- items

def role_purpose(src, rel):
    lines = read(src, rel).split("\n")
    for line in lines:
        m = re.match(r"^#\s+Role:\s*.+?\s+[—–]\s+(.+?)\s*$", line)
        if m:
            return m.group(1)
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#"):
            return s[:120]
    raise CatalogError("%s: no '# Role: <name> — <purpose>' heading and no paragraph line" % rel)


def role_items(src, sha):
    items = []
    for fname in files(src, "roles"):
        if not fname.endswith(".md") or fname == "_common.md":
            continue
        name = fname[:-3]
        rel = "roles/" + fname
        snippets = ["curl -fsSLO https://raw.githubusercontent.com/%s/%s/%s" % (REPO, sha, rel)]
        skills = []
        for plugin in subdirs(src, "roles/plugins/" + name):
            snippets.append("git clone --depth 1 https://github.com/%s && claude --plugin-dir "
                            "hivemill/roles/plugins/%s/%s" % (REPO, name, plugin))
            sdir = "roles/plugins/%s/%s/skills" % (name, plugin)
            for sk in subdirs(src, sdir):
                srel = "%s/%s/SKILL.md" % (sdir, sk)
                if os.path.isfile(os.path.join(src, srel)):
                    sname, spurpose = skill_meta(src, srel, sk)
                    skills.append({"name": sname, "purpose": spurpose})
        items.append({"id": "role:" + name, "kind": "role", "name": name,
                      "purpose": role_purpose(src, rel), "snippets": snippets,
                      "path": rel, "skills": skills})
    return items


def listed_plugins(src):
    rel = ".claude-plugin/marketplace.json"
    if not os.path.isfile(os.path.join(src, rel)):
        return set()
    return {p.get("name") for p in read_json(src, rel).get("plugins", []) if isinstance(p, dict)}


def plugin_snippets(name, dirname, listed):
    if name in listed:
        return ["/plugin marketplace add " + REPO, "/plugin install %s@hivemill" % name]
    return ["git clone --depth 1 https://github.com/%s && claude --plugin-dir "
            "hivemill/plugins/%s" % (REPO, dirname)]


def plugin_items(src):
    listed = listed_plugins(src)
    items = []
    for d in subdirs(src, "plugins"):
        mrel = "plugins/%s/.claude-plugin/plugin.json" % d
        if not os.path.isfile(os.path.join(src, mrel)):
            continue
        meta = read_json(src, mrel)
        name = meta.get("name")
        if not name:
            raise CatalogError("%s has no name" % mrel)
        snippets = plugin_snippets(name, d, listed)
        bins = files(src, "plugins/%s/bin" % d)
        items.append({"id": "plugin:" + name, "kind": "plugin", "name": name,
                      "purpose": meta.get("description", ""), "snippets": snippets,
                      "path": "plugins/" + d, "bins": bins})
        for sk in subdirs(src, "plugins/%s/skills" % d):
            srel = "plugins/%s/skills/%s/SKILL.md" % (d, sk)
            if not os.path.isfile(os.path.join(src, srel)):
                continue
            sname, purpose = skill_meta(src, srel, sk)
            items.append({"id": "skill:%s/%s" % (name, sk), "kind": "skill", "name": sname,
                          "purpose": purpose, "snippets": snippets, "path": srel,
                          "plugin": name, "bins": bins})
    return items


def dashboard_items(src):
    if not os.path.isdir(os.path.join(src, "plugins/hivemill/herdr-app")):
        return []
    rel = "docs/herdr-app-dashboard.md"
    lines = read(src, rel).split("\n")
    purpose = next((strip_links(l.strip()) for l in lines if l.strip() and not l.startswith("#")), "")
    if not purpose:
        raise CatalogError("%s has no purpose paragraph" % rel)
    snippets, state = [], 0
    for line in lines:
        if state == 0 and re.match(r"^##\s+Install\s*$", line):
            state = 1
        elif state == 1 and line.startswith("```"):
            state = 2
        elif state == 2:
            if line.startswith("```"):
                break
            if line.strip():
                snippets.append(line)
    if not snippets:
        raise CatalogError("%s documents no install route (fenced block under '## Install')" % rel)
    return [{"id": "dashboard:herdr-core", "kind": "dashboard", "name": "herdr-core",
             "purpose": purpose, "snippets": snippets, "path": "plugins/hivemill/herdr-app"}]


def load_overrides(path):
    if not os.path.isfile(path):
        raise UsageError("overrides file %s not found" % path)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise UsageError("overrides file %s is not valid JSON: %s" % (path, exc))
    if not isinstance(data, dict):
        raise UsageError("overrides file %s must be a JSON object" % path)
    for item_id, val in data.items():
        if not isinstance(val, dict):
            raise UsageError("overrides[%s] must be an object" % item_id)
        for key in val:
            if key not in OVERRIDE_KEYS:
                raise UsageError("overrides[%s] has key '%s'; only %s are allowed"
                                 % (item_id, key, ", ".join(OVERRIDE_KEYS)))
    return data


def derive(src, sha, overrides):
    items = role_items(src, sha) + plugin_items(src) + dashboard_items(src)
    ids = {i["id"] for i in items}
    for item_id in overrides:
        if item_id not in ids:
            raise UsageError("overrides names unknown item id '%s'" % item_id)
    for item in items:
        item.update(overrides.get(item["id"], {}))
    items.sort(key=lambda i: (i["kind"], i["name"], i["id"]))
    return {"schemaVersion": SCHEMA_VERSION, "source": {"repo": REPO, "sha": sha}, "items": items}


def dump(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- commands

def cmd_build(args):
    sha = head_sha(args.src)
    data = derive(args.src, sha, load_overrides(args.overrides))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(dump(data))
    print("wrote %s: %d items at %s" % (args.out, len(data["items"]), sha[:12]))
    return 0


def cmd_check(args):
    try:
        with open(args.catalog, encoding="utf-8") as fh:
            old_text = fh.read()
        pinned = json.loads(old_text)["source"]["sha"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise UsageError("cannot read source.sha from %s: %s" % (args.catalog, exc))
    sha = head_sha(args.src)
    if sha != pinned:
        raise UsageError("checkout HEAD %s != catalog source.sha %s; check out the pinned sha"
                         % (sha, pinned))
    new_text = dump(derive(args.src, sha, load_overrides(args.overrides)))
    if new_text == old_text:
        print("catalog matches %s at %s" % (args.src, sha[:12]))
        return 0
    sys.stdout.writelines(difflib.unified_diff(
        old_text.splitlines(True), new_text.splitlines(True),
        fromfile="catalog.json", tofile="derived from " + sha[:12]))
    print("catalog drift: run tools/catalog.py build")
    return 1


RAW_URL = re.compile(r"https://raw\.githubusercontent\.com/[\w.-]+/[\w.-]+/[0-9a-f]{40}/([^\s`'\"]+)")
ANY_URL = re.compile(r"https?://[^\s`'\"]+")
REPO_PATH = re.compile(r"(?<![\w/.-])(?:hivemill/)?((?:roles|plugins)/[^\s`'\"]+)")


def snippet_paths(snippet):
    paths = [m.group(1) for m in RAW_URL.finditer(snippet)]
    rest = ANY_URL.sub(" ", snippet)
    paths += [m.group(1).rstrip(".,;)") for m in REPO_PATH.finditer(rest)]
    return paths


def cmd_verify(args):
    head_sha(args.src)
    try:
        with open(args.catalog, encoding="utf-8") as fh:
            items = json.load(fh)["items"]
    except (OSError, ValueError, KeyError) as exc:
        raise UsageError("cannot read items from %s: %s" % (args.catalog, exc))
    problems = []
    for item in items:
        for snippet in item.get("snippets", []):
            for rel in snippet_paths(snippet):
                if not os.path.exists(os.path.join(args.src, rel)):
                    problems.append("%s: snippet references missing path %s" % (item["id"], rel))
            if args.network:
                for m in re.finditer(r"https://raw\.githubusercontent\.com/[^\s`'\"]+", snippet):
                    url = m.group(0)
                    try:
                        req = urllib.request.Request(url, method="HEAD")
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            code = resp.status
                    except urllib.error.HTTPError as exc:
                        code = exc.code
                    except (urllib.error.URLError, OSError) as exc:
                        problems.append("%s: %s unreachable: %s" % (item["id"], url, exc))
                        continue
                    if code != 200:
                        problems.append("%s: %s answered HTTP %s" % (item["id"], url, code))
    for p in problems:
        print("FAIL " + p)
    if problems:
        return 1
    print("all snippets verified (%d items%s)" % (len(items), ", network" if args.network else ""))
    return 0


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("catalog.py: error: %s\n" % message)
        raise SystemExit(2)


def main(argv=None):
    ap = Parser(prog="catalog.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=Parser)
    b = sub.add_parser("build")
    b.add_argument("--src", required=True)
    b.add_argument("--out", default=DEFAULT_CATALOG)
    b.add_argument("--overrides", default=DEFAULT_OVERRIDES)
    b.set_defaults(fn=cmd_build)
    c = sub.add_parser("check")
    c.add_argument("--src", required=True)
    c.add_argument("--catalog", default=DEFAULT_CATALOG)
    c.add_argument("--overrides", default=DEFAULT_OVERRIDES)
    c.set_defaults(fn=cmd_check)
    v = sub.add_parser("verify-snippets")
    v.add_argument("--src", required=True)
    v.add_argument("--catalog", default=DEFAULT_CATALOG)
    v.add_argument("--network", action="store_true")
    v.set_defaults(fn=cmd_verify)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except UsageError as exc:
        sys.stderr.write("catalog.py: %s\n" % exc)
        return 2
    except CatalogError as exc:
        sys.stderr.write("catalog.py: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
