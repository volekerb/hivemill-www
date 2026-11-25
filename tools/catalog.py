#!/usr/bin/env python3
"""Catalog generator for hivemill-www.

Derives catalog/catalog.json from a read-only checkout of volekerb/hivemill at
a pinned commit. Nothing outside the checkout is read; the only network use is
`verify-snippets --network`. Python 3 stdlib only.

Subcommands
  build           --src CHECKOUT [--out catalog/catalog.json] [--overrides FILE]
  check           --src CHECKOUT [--catalog FILE] [--overrides FILE] [--skip-pages]
                  also fails when catalog/index.html or a detail page differs from a fresh render
  verify-snippets --src CHECKOUT [--catalog FILE] [--network]
  render          --in catalog/catalog.json --out catalog/index.html
                  writes the index page and one catalog/<slug>/index.html per item; deterministic

Exit codes: 0 ok, 1 drift / failed derivation / broken snippet, 2 usage error.

JSON schema (schemaVersion 1; consumed by the `render` subcommand)
  {
    "schemaVersion": 1,
    "source": {"repo": "volekerb/hivemill", "sha": "<40 hex>", "date": "YYYY-MM-DD (commit date)"},
    "items": [Item, ...]          # sorted by kind, then name, then id
  }
  Item (all kinds):
    id        str   "<kind>:<name>" (skill ids are "skill:<plugin-name>/<skill>")
    kind      str   "dashboard" | "plugin" | "role" | "skill"
    name      str
    purpose   str   one line, derived from the source file (never hand-written)
    snippets  [str] copy/install lines, in order
    path      str   source path inside the hivemill repo
    file      str   full text of the source file (omitted for items without one)
    icon, media     optional; presentation assets from catalog/overrides.json
                    Curated summary/use_when/requirements overrides affect HTML only;
                    source-derived purpose, files and snippets remain unchanged.
  role extra:   skills  [{"name", "purpose"}] from roles/plugins/<name>/*/skills/*/SKILL.md
                permissions {"allow": [str], "deny": [str]} from roles/settings/<name>.json.in (when present)
                Option B lane roles come from roles/hivemill/<name>.md (purpose: first sentence of
                the first paragraph) with permissions from roles/hivemill/<name>.json.in (else roles/settings/<name>.json.in);
                _*.md and README.md there are not roles
  planned item  {"status": "soon", "present": [path], "absent": [path]}: named by an ADR in the
                checkout but not shipped; lists which of its paths exist and which do not
  skill extra:  plugin (str, plugin.json name), bins [str] (files in the plugin's bin/)
  plugin extra: bins [str]
"""
import argparse
import difflib
import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from site_metadata import apply_metadata

REPO = "volekerb/hivemill"
SCHEMA_VERSION = 1
OVERRIDE_KEYS = ("icon", "media", "summary", "use_when", "requirements")
# Items that exist in hivemill but are not factory pieces to share (owner decision, M40888).
EXCLUDED_IDS = frozenset({"skill:hivemill/ios-testflight-release"})
# Pieces an ADR names that may not be on main yet: id, name, ADR, paths of the finished piece.
# Listed as "soon" only while a path of the finished piece is absent from the checkout.
PLANNED = [{"id": "skill:hm-clean", "name": "hm-clean", "doc": "docs/adr/0008-resource-hygiene.md",
            "paths": ["go/internal/kit/clean/fsx", "go/cmd/hm-clean", "plugins/kit-clean"]}]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CATALOG = os.path.join(ROOT, "catalog", "catalog.json")
DEFAULT_OVERRIDES = os.path.join(ROOT, "catalog", "overrides.json")
DEFAULT_TEMPLATE = os.path.join(ROOT, "catalog", "template.html")
DEFAULT_DETAIL = os.path.join(ROOT, "catalog", "detail-template.html")
DEFAULT_SOURCES = os.path.join(ROOT, "assets", "img", "SOURCES.json")
DEFAULT_ICONS = os.path.join(ROOT, "assets", "icons", "icons.svg")


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


def head_date(src):
    try:
        out = subprocess.run(["git", "-C", src, "show", "-s", "--format=%cs", "HEAD"],
                             capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise UsageError("--src %s: cannot read the commit date: %s" % (src, exc))
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


def lane_purpose(src, rel):
    """First sentence of the first paragraph of a lane prompt (roles/hivemill/*.md)."""
    para = []
    for line in read(src, rel).split("\n"):
        s = line.strip()
        if s and not s.startswith("#"):
            para.append(s)
        elif para:
            break
    if not para:
        raise CatalogError("%s: no paragraph after the heading" % rel)
    return first_sentence(strip_links(" ".join(para)))


def role_permissions(src, name, rel=None):
    rel = rel if rel and os.path.isfile(os.path.join(src, rel)) else "roles/settings/%s.json.in" % name
    if not os.path.isfile(os.path.join(src, rel)):
        return None
    perms = read_json(src, rel).get("permissions", {})
    out = {k: [str(x) for x in perms.get(k, [])] for k in ("allow", "deny")}
    return out if out["allow"] or out["deny"] else None


def role_sources(src):
    """(name, prompt path, purpose function, settings path) for every role prompt."""
    for fname in files(src, "roles"):
        if fname.endswith(".md") and fname != "_common.md":
            yield fname[:-3], "roles/" + fname, role_purpose, None
    # Option B lane: roles/hivemill/<name>.md with settings roles/hivemill/<name>.json.in.
    for fname in files(src, "roles/hivemill"):
        if fname.endswith(".md") and not fname.startswith("_") and fname.lower() != "readme.md":
            yield fname[:-3], "roles/hivemill/" + fname, lane_purpose, "roles/hivemill/%s.json.in" % fname[:-3]


def role_items(src, sha):
    items, seen = [], set()
    for name, rel, purpose, settings in role_sources(src):
        if name in seen:
            raise CatalogError("%s: role name '%s' is already used by another prompt" % (rel, name))
        seen.add(name)
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
        item = {"id": "role:" + name, "kind": "role", "name": name,
                "purpose": purpose(src, rel), "snippets": snippets,
                "path": rel, "file": read(src, rel), "skills": skills}
        perms = role_permissions(src, name, settings)
        if perms:
            item["permissions"] = perms
        items.append(item)
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
                      "path": "plugins/" + d, "file": read(src, mrel), "bins": bins})
        for sk in subdirs(src, "plugins/%s/skills" % d):
            srel = "plugins/%s/skills/%s/SKILL.md" % (d, sk)
            if not os.path.isfile(os.path.join(src, srel)):
                continue
            sname, purpose = skill_meta(src, srel, sk)
            items.append({"id": "skill:%s/%s" % (name, sk), "kind": "skill", "name": sname,
                          "purpose": purpose, "snippets": snippets, "path": srel,
                          "file": read(src, srel), "plugin": name, "bins": bins})
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
             "purpose": purpose, "snippets": snippets, "path": "plugins/hivemill/herdr-app",
             "file": read(src, rel)}]


def planned_items(src, have):
    items = []
    for plan in PLANNED:
        if plan["id"] in have or not os.path.isfile(os.path.join(src, plan["doc"])):
            continue
        present = [p for p in plan["paths"] if os.path.exists(os.path.join(src, p))]
        absent = [p for p in plan["paths"] if p not in present]
        if not absent:
            continue
        title = next((l for l in read(src, plan["doc"]).split("\n") if l.startswith("# ")), "")
        m = re.match(r"^#\s+ADR\s+\d+:\s+(.+?)(?:\s+\(.*\))?\s*$", title)
        if not m:
            raise CatalogError("%s has no '# ADR <n>: <title>' heading" % plan["doc"])
        items.append({"id": plan["id"], "kind": "skill", "name": plan["name"], "purpose": m.group(1),
                      "snippets": [], "path": plan["doc"], "status": "soon",
                      "present": present, "absent": absent})
    return items


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
            if key in ("summary", "use_when", "requirements") and (not isinstance(val[key], str) or not val[key].strip()):
                raise UsageError("overrides[%s].%s must be a nonempty string" % (item_id, key))
    return data


def derive(src, sha, overrides):
    items = role_items(src, sha) + plugin_items(src) + dashboard_items(src)
    items = [i for i in items if i["id"] not in EXCLUDED_IDS]
    items += planned_items(src, {i["id"] for i in items})
    ids = {i["id"] for i in items}
    for item_id in overrides:
        if item_id not in ids:
            raise UsageError("overrides names unknown item id '%s'" % item_id)
    for item in items:
        item.update({key: value for key, value in overrides.get(item["id"], {}).items() if key in ("icon", "media")})
    items.sort(key=lambda i: (i["kind"], i["name"], i["id"]))
    return {"schemaVersion": SCHEMA_VERSION, "source": {"repo": REPO, "sha": sha, "date": head_date(src)}, "items": items}


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
        if args.skip_pages:
            return 0
        problems = pages_drift(args)
        for p in problems:
            print("FAIL " + p)
        if problems:
            print("page drift: run tools/catalog.py render --in catalog/catalog.json --out catalog/index.html")
            return 1
        print("catalog pages match a fresh render")
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


# ---------------------------------------------------------------- render

KINDS = [("role", "Roles", "roles", "Markdown instructions for individual agents. Planner, task and task judge run on the Hivemill runner; the others belong to the paused legacy pipeline."),
         ("skill", "Skills", "skills", "Reusable workflows installed through the plugin that carries them."),
         ("plugin", "Plugins", "plugins", "Installable bundles of skills and helper commands."),
         ("dashboard", "Dashboard", "dashboard", "A desktop view of your factory.")]
KIND_LABEL = {k: label for k, label, _, _ in KINDS}
KIND_ANCHOR = {k: anchor for k, _, anchor, _ in KINDS}
ICON_ID = re.compile(r'<symbol id="([^"]+)"')


def slug(item_id):
    return re.sub(r"[^a-z0-9]+", "-", item_id.lower()).strip("-")


def esc(text):
    return html.escape(text, quote=True)


def read_text(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise UsageError("cannot read %s %s: %s" % (what, path, exc))


def media_table(sources_path):
    """name -> {width: (png/webp file stem pair)} from SOURCES.json, with sizes."""
    try:
        entries = json.loads(read_text(sources_path, "image sources"))
    except json.JSONDecodeError as exc:
        raise UsageError("%s is not valid JSON: %s" % (sources_path, exc))
    table = {}
    for e in entries:
        m = re.match(r"^(.+)-(\d+)\.(webp|png)$", e["file"])
        if m:
            table.setdefault(m.group(1), {}).setdefault(int(m.group(2)), {})[m.group(3)] = e
    return table


def source_url(source, item):
    kind = "blob" if "." in item["path"].rsplit("/", 1)[-1] else "tree"
    return "https://github.com/%s/%s/%s/%s" % (source["repo"], kind, source["sha"], item["path"])


def icon_svg(root, name, cls="i"):
    return ('<svg class="%s" aria-hidden="true"><use href="%sassets/icons/icons.svg#%s"/></svg>'
            % (cls, root, esc(name)))


def picture(root, name, widths, alt, lazy=True):
    sizes = sorted(widths)
    big = widths[sizes[-1]]["png"]
    srcset = lambda ext: ", ".join("%sassets/img/%s-%d.%s %dw" % (root, name, w, ext, w) for w in sizes)
    slot = ("(min-width: 85rem) 52rem, (min-width: 48rem) 66vw, 100vw" if name == "herdr-panel" else
            "(min-width: 85rem) 25rem, (min-width: 48rem) 32vw, (min-width: 32rem) 48vw, 100vw")
    return ('<picture><source type="image/webp" srcset="%s" sizes="%s">'
            '<img src="%sassets/img/%s-%d.png" srcset="%s" sizes="%s" '
            'width="%d" height="%d" alt="%s"%s decoding="async"></picture>'
            % (srcset("webp"), slot, root, name, sizes[-1], srcset("png"), slot, big["width"], big["height"],
               esc(alt), ' loading="lazy"' if lazy else ""))


def media_alt(name):
    return "herdr-core dashboard" if name == "herdr-panel" else \
        "herdr-core dashboard, %s panel" % name.replace("panel-", "").replace("-", " ")


def display_name(item):
    if item["kind"] == "plugin" and item.get("file"):
        return json.loads(item["file"]).get("displayName") or item["name"]
    if item["id"] == "dashboard:herdr-core":
        return "Herdr dashboard"
    if item["name"] in ("qa", "pm"):
        return item["name"].upper()
    if item["name"].startswith("hm-"):
        return item["name"]
    return item["name"].replace("-", " ").capitalize()


def description(item, overrides=None):
    if overrides and overrides.get("summary"):
        return overrides["summary"]
    if item["id"] == "dashboard:herdr-core":
        return "Factory status, alerts and budgets inside the Herdr desktop app."
    purpose = item["purpose"]
    return purpose[:1].upper() + purpose[1:] + ("." if purpose and purpose[-1] not in ".:!?" else "")


def choosing_component(item, overrides):
    """Human-facing selection guidance; full source and copy/install behavior stay intact."""
    if item.get("status") == "soon":
        return ''
    defaults = {
        "role": ("Use this role when assembling or adapting your factory's agent team.",
                 "A Hivemill factory checkout. Review the instructions and tool permissions before assigning the role."),
        "skill": ("Add this skill when you need its workflow in Claude Code.",
                  "Claude Code with the containing plugin installed. Check the source instructions for workflow-specific prerequisites."),
        "plugin": ("Install this plugin to add its commands and bundled skills to Claude Code.",
                   "Claude Code. Follow the installation guide for the plugin's host and runtime requirements."),
        "dashboard": ("Use this dashboard to watch your factory from the Herdr desktop app.",
                      "A Hivemill installation and the Herdr app for Mac. Apply the dashboard integration from your factory checkout."),
    }
    when, requires = defaults[item["kind"]]
    return ('<section class="component-section" id="use"><h2>When to use it</h2><p>%s</p>'
            '<h3>Requirements</h3><p>%s</p></section>' %
            (esc(overrides.get("use_when", when)), esc(overrides.get("requirements", requires))))


def search_title(item):
    label = {"role": "agent role", "skill": "skill", "plugin": "plugin", "dashboard": "for Hivemill"}[item["kind"]]
    return display_name(item) + " " + label + " | Hivemill"


def source_file(item):
    if item["kind"] == "dashboard":
        return "docs/herdr-app-dashboard.md"
    if item["kind"] == "plugin":
        return item["path"] + "/.claude-plugin/plugin.json"
    return item["path"]


def code_block(content, label, button_label, accessible_label, code_id=None):
    return ('<div class="snip"><div class="snippet-bar"><span>%s</span>'
            '<button class="copy" type="button" hidden data-copy aria-label="%s">%s</button></div>'
            '<pre class="code"%s><code>%s</code></pre></div>'
            % (esc(label), esc(accessible_label), esc(button_label),
               ' id="%s"' % code_id if code_id else "", esc(content)))


def install_panel(item):
    snippets = item["snippets"]
    if not snippets:
        return ""
    if item["kind"] == "role" and len(snippets) > 1:
        groups = [("Role file · Terminal", snippets[:1]), ("Optional role skills · Terminal", snippets[1:])]
    else:
        label = "Claude Code" if snippets[0].startswith("/plugin ") else "Terminal"
        groups = [(label, snippets)]
    if item["kind"] == "role":
        direction = "Download the role file and adapt its instructions for your agent."
    elif item["kind"] == "dashboard":
        direction = "From your Hivemill checkout, preview the changes before applying them."
    elif item["kind"] == "skill" and item.get("plugin"):
        direction = "Install the %s plugin to add this skill." % item["plugin"]
    else:
        direction = ("Run these commands in Claude Code." if snippets[0].startswith("/plugin ")
                     else "Run this command in your terminal to load the plugin in Claude Code.")
    return ('<section class="component-section" id="install"><h2>Install</h2><p>%s</p>%s</section>'
            % (esc(direction), "".join(code_block("\n".join(lines), label, "Copy", "Copy %s commands for %s" % (label, item["name"]))
                      for label, lines in groups)))


def entry(item, ctx):
    identifier = slug(item["id"])
    icon = ctx["overrides"][item["id"]].get("icon", "catalog")
    keywords = [item["id"], item["path"], item.get("plugin", "")] + item.get("bins", [])
    keywords.extend(s["name"] for s in item.get("skills", []))
    status = '<span class="catalog-status">Coming soon</span>' if item.get("status") == "soon" else ""
    return ('<article class="entry" id="%s" data-item-id="%s" data-kind="%s" data-search="%s">'
            '<a class="entry-link" href="%s/" aria-labelledby="%s-title" aria-describedby="%s-purpose">'
            '<span class="entry-emblem">%s</span><h3 id="%s-title">%s%s</h3>'
            '<p id="%s-purpose">%s</p>%s</a></article>'
            % (identifier, esc(item["id"]), item["kind"], esc(" ".join(keywords)), identifier, identifier, identifier,
               icon_svg(ctx["root"], icon), identifier, esc(display_name(item)), status, identifier, esc(description(item, ctx["overrides"][item["id"]])),
               icon_svg(ctx["root"], "arrow", "entry-arrow")))


def sections(text):
    """Split a Markdown source file into (heading, body) pairs on '## ' headings."""
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), 0)
        lines = lines[end + 1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    out, head, buf, fence = [], "Overview", [], False
    for line in lines:
        if line.lstrip().startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            out.append((head, buf))
            head, buf = line[3:].strip(), []
        elif not (line.startswith("# ") and not fence and not out and not buf):
            buf.append(line)
    out.append((head, buf))
    return [(h, "\n".join(b).strip("\n")) for h, b in out if "".join(b).strip()]


INLINE_TOKEN = re.compile(r"`([^`\n]+)`|\*\*(.+?)\*\*|!?\[([^\]\n]+)\]\(([^()\s]+)\)")
LIST_ITEM = re.compile(r"^( *)([-*]|\d+\.)\s+(.*)$")


def doc_inline(text, url):
    """Format the inline syntax used in component files. All source text is escaped."""
    out, end = [], 0
    for token in INLINE_TOKEN.finditer(text):
        out.append(esc(text[end:token.start()]))
        code, strong, label, href = token.groups()
        if code is not None:
            out.append("<code>%s</code>" % esc(code))
        elif strong is not None:
            out.append("<strong>%s</strong>" % doc_inline(strong, url))
        else:
            dest = urllib.parse.urljoin(url, href)
            if urllib.parse.urlsplit(dest).scheme in ("http", "https"):
                out.append('<a href="%s">%s</a>' % (esc(dest), esc(label)))
            else:
                out.append(esc(label))
        end = token.end()
    return "".join(out) + esc(text[end:])


def doc_blocks(text, url):
    """Render source paragraphs, lists, headings, tables and fenced examples."""
    lines, out, i = text.splitlines(), [], 0

    def block_start(line):
        return (not line.strip() or line.lstrip().startswith(("```", "#", "|"))
                or LIST_ITEM.match(line))

    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        if line.startswith("```"):
            code = []
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append('<pre><code>%s</code></pre>' % esc("\n".join(code)))
        elif line.startswith("|"):
            rows = [line]
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            cells = [row.strip("|").split("|") for row in rows if not re.fullmatch(r"[ |:\-]+", row)]
            out.append('<div class="doc-table"><table>')
            for j, row in enumerate(cells):
                tag = "td" if j else "th"
                out.append("<tr>%s</tr>" % "".join("<%s>%s</%s>" % (tag, doc_inline(c.strip(), url), tag)
                                                  for c in row))
            out.append("</table></div>")
        elif re.match(r"^#{1,6} ", line):
            out.append("<h4>%s</h4>" % doc_inline(line.lstrip("# "), url))
        elif LIST_ITEM.match(lines[i - 1]):
            first = LIST_ITEM.match(lines[i - 1])
            indent = len(first[1])
            ordered = first[2].endswith(".")
            tag = "ol" if ordered else "ul"
            start = ' start="%d"' % int(first[2][:-1]) if ordered and first[2] != "1." else ""
            out.append("<%s%s>" % (tag, start))
            i -= 1
            while i < len(lines):
                match = LIST_ITEM.match(lines[i])
                if not match or len(match[1]) != indent or match[2].endswith(".") != ordered:
                    break
                body = [match[3]]
                i += 1
                while i < len(lines):
                    subline = lines[i]
                    if subline and len(subline) - len(subline.lstrip()) > indent:
                        body.append(subline[min(indent + len(match[2]) + 1,
                                                len(subline) - len(subline.lstrip())):])
                    elif not subline.strip() and i + 1 < len(lines) and lines[i + 1].startswith(" " * (indent + 1)):
                        body.append("")
                    else:
                        break
                    i += 1
                out.append("<li>%s</li>" % doc_blocks("\n".join(body), url))
            out.append("</%s>" % tag)
        else:
            para = [line]
            while i < len(lines) and not block_start(lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>%s</p>" % doc_inline(" ".join(para), url))
    return "".join(out)


def combines(item, items):
    by_id = {i["id"]: i for i in items}
    ids = []
    if item["kind"] == "skill" and item.get("plugin"):
        ids = ["plugin:" + item["plugin"]] + [i["id"] for i in items
                                              if i["kind"] == "skill" and i.get("plugin") == item["plugin"]
                                              and i["id"] != item["id"]]
    elif item["kind"] == "plugin":
        ids = [i["id"] for i in items if i["kind"] == "skill" and i.get("plugin") == item["name"]]
    elif item["kind"] == "dashboard":
        ids = [i["id"] for i in items if i["kind"] == "plugin" and i["path"] == "plugins/hivemill"]
    elif item["kind"] == "role":
        ids = [i["id"] for i in items if i["kind"] == "role" and i != item
               and re.search(r"\b%s\b" % re.escape(i["name"]), item.get("file", ""), re.I)][:3]
    return [by_id[i] for i in ids if i in by_id]


def detail_page(item, items, ctx):
    root, source = ctx["root"], ctx["source"]
    ov = ctx["overrides"][item["id"]]
    kind = item["kind"]
    anchor = KIND_ANCHOR[kind]
    file_path = source_file(item)
    source_link = source_url(source, item)
    file_link = "https://github.com/%s/blob/%s/%s" % (source["repo"], source["sha"], file_path)
    icon = icon_svg(root, ov.get("icon", "catalog"), "component-symbol")
    out = ['<header class="component-hero wrap"><nav aria-label="Breadcrumb" class="component-crumb">'
           '<a href="../">Catalog</a><span aria-hidden="true">/</span><a href="../#%s">%s</a></nav>'
           % (anchor, KIND_LABEL[kind]),
           '<div class="component-heading"><div><h1>%s</h1><p>%s</p></div>'
           '<div class="component-mark" aria-hidden="true">%s</div></div></header>'
           % (esc(display_name(item)), esc(description(item, ov)), icon),
           '<div class="wrap component-layout"><div class="component-body">']
    if item.get("status") == "soon":
        out.append('<section class="component-section"><h2>Availability</h2><p><strong>Coming soon.</strong> '
                   'The implementation is in progress at this revision.</p><dl class="component-facts">'
                   '<dt>Present</dt><dd>%s</dd><dt>Still needed</dt><dd>%s</dd></dl></section>'
                   % (esc(", ".join(item["present"]) or "None"), esc(", ".join(item["absent"]))))
    out.append(choosing_component(item, ov))
    out.append(install_panel(item))
    if ov.get("media"):
        out.append('<section class="component-section"><h2>Dashboard preview</h2>'
                   '<p>Herdr desktop screenshots with fictional demo data. Select a view to open its source image.</p>'
                   '<div class="catalog-shots">')
        for name in sorted(ov["media"], key=lambda n: n != "herdr-panel"):
            widths = ctx["media"][name]
            original = widths[min(widths)]["png"]
            url = "https://github.com/%s/blob/%s/%s" % (original["source_repo"], original["source_sha"],
                                                        original["source_path"])
            caption = "Desktop overview" if name == "herdr-panel" else name.removeprefix("panel-").replace("-", " ").capitalize()
            out.append('<figure class="%s"><a href="%s">%s<span>%s <span aria-hidden="true">↗</span></span></a></figure>'
                       % ("shot-wide" if name == "herdr-panel" else "", esc(url),
                          picture(root, name, widths, media_alt(name)), esc(caption)))
        out.append("</div></section>")
    if item.get("skills"):
        out.append('<section class="component-section"><h2>Bundled skills</h2><dl class="bundled-skills">%s</dl></section>'
                   % "".join('<div><dt>%s</dt><dd>%s</dd></div>' % (esc(s["name"]), esc(s["purpose"]))
                             for s in item["skills"]))
    if item.get("file", "").lstrip().startswith(("#", "---")):
        doc = sections(item["file"])
        if doc:
            out.append('<section class="component-section" id="documentation"><h2>Documentation</h2>')
            for index, (heading, body) in enumerate(doc):
                out.append('<details class="doc-section"%s><summary>%s</summary><div class="doc">%s</div></details>'
                           % (" open" if index == 0 else "", doc_inline(heading, file_link), doc_blocks(body, file_link)))
            out.append("</section>")
    if item.get("permissions"):
        out.append('<section class="component-section"><h2>Tool permissions</h2>')
        for key, label in (("allow", "Allowed tools"), ("deny", "Blocked tools")):
            tools = item["permissions"].get(key, [])
            if tools:
                out.append('<details class="doc-section"><summary>%s <small>%d</small></summary>'
                           '<ul class="tool-list">%s</ul></details>'
                           % (label, len(tools), "".join("<li><code>%s</code></li>" % esc(tool) for tool in tools)))
        out.append("</section>")
    if item.get("file"):
        out.append('<section class="component-section"><details class="raw-source"><summary>Full source file</summary>'
                   '%s</details></section>' % code_block(item["file"].rstrip("\n"), file_path, "Copy full file",
                                                         "Copy full file for " + item["name"], "full"))
    out.append('</div><aside aria-label="Component information"><div class="component-aside">'
               '<section><h2>Component details</h2><dl class="component-facts"><dt>Type</dt><dd>%s</dd>'
               '<dt>Name</dt><dd><code>%s</code></dd>' % (kind.capitalize(), esc(item["name"])))
    if item.get("plugin"):
        out.append('<dt>Plugin</dt><dd>%s</dd>' % esc(item["plugin"]))
    if item.get("bins"):
        out.append('<dt>Commands</dt><dd>%s</dd>' % ", ".join('<code>%s</code>' % esc(b) for b in item["bins"]))
    out.append('<dt>Revision</dt><dd><a href="https://github.com/%s/commit/%s"><code>%s</code></a></dd>'
               '</dl><a class="catalog-text-link" href="%s">View source on GitHub <span aria-hidden="true">↗</span></a>'
               '</section>' % (esc(source["repo"]), esc(source["sha"]), esc(source["sha"][:12]), esc(source_link)))
    related = combines(item, items)
    if related:
        out.append('<section><h2>%s</h2><ul class="component-related">%s</ul></section>'
                   % ("Mentioned roles" if kind == "role" else "Related components", "".join(
                       '<li><a href="../%s/">%s<span>%s</span><span aria-hidden="true">↗</span></a></li>'
                       % (slug(r["id"]), icon_svg(root, ctx["overrides"][r["id"]].get("icon", "catalog")),
                          esc(display_name(r))) for r in related)))
    out.append('</div></aside></div>')
    return "\n".join(out)


def index_page(items, ctx):
    root = ctx["root"]
    counts = {kind: sum(i["kind"] == kind for i in items) for kind, *_ in KINDS}
    out = ['<header class="catalog-intro wrap"><div class="catalog-lead">'
           '<p class="catalog-kicker">Developer library</p><h1>Factory catalog<span>.</span></h1>'
           '<p class="catalog-deck">Reusable agent roles, skills and plugins for building your own software factory.</p>'
           '</div>']
    if any(i["id"] == "plugin:hivemill" for i in items):
        out.append('<a class="catalog-feature" href="plugin-hivemill/">'
                   '<div class="feature-caption"><span class="feature-label">Featured plugin</span>'
                   '<strong>Legacy pipeline installer</strong></div><span class="feature-arrow" aria-hidden="true">↗</span></a>')
    out.append('</header><div class="catalog wrap" id="library">'
               '<aside class="catalog-collections"><div class="collections-sticky">'
               '<h2 id="collections-title">Collections</h2><nav aria-labelledby="collections-title">'
               '<a href="#library" data-filter="all" aria-current="true"><span>All components</span>'
               '<span class="collection-count">%d</span></a>' % len(items))
    for kind, label, anchor, _ in KINDS:
        if counts[kind]:
            out.append('<a href="#%s" data-filter="%s"><span>%s</span><span class="collection-count">%d</span></a>'
                       % (anchor, kind, label, counts[kind]))
    out.append('</nav><a class="catalog-text-link catalog-guide" href="%sguides/install/">Installation guide '
               '<span aria-hidden="true">↗</span></a></div></aside>'
               '<div class="catalog-results"><div class="catalog-search" role="search" hidden>'
               '%s<label class="sr" for="catalog-q">Search components</label><input id="catalog-q" '
               'type="search" placeholder="Search components…" autocomplete="off" spellcheck="false">'
               '<kbd aria-hidden="true">/</kbd></div><p class="sr" role="status" aria-live="polite" id="live"></p>'
               % (root, icon_svg(root, "researcher")))
    for kind, label, anchor, intro in KINDS:
        if not counts[kind]:
            continue
        out.append('<section class="group" id="%s" data-group="%s" aria-labelledby="%s-title">'
                   '<header class="group-head"><h2 id="%s-title">%s <small>%d</small></h2><p>%s</p></header>'
                   % (anchor, kind, anchor, anchor, label, counts[kind], esc(intro)))
        out.extend(entry(i, ctx) for i in items if i["kind"] == kind)
        out.append("</section>")
    out.append('<div class="catalog-empty" hidden><h2>No components found</h2>'
               '<p>Try another search or browse all components.</p><button type="button" data-reset>Clear filters</button>'
               '</div></div></div>')
    return "\n".join(out)


def fill(template, values):
    for key, val in values.items():
        template = template.replace("{{%s}}" % key, val)
    return template


def render_site(catalog_path, overrides_path, template_path, detail_path, sources_path, icons_path):
    """Return {relative path under the catalog dir: text}. Pure function of its input files."""
    try:
        data = json.loads(read_text(catalog_path, "catalog"))
        items, source = data["items"], data["source"]
        source["date"]
    except (ValueError, KeyError, TypeError) as exc:
        raise UsageError("%s is not a catalog.json this tool wrote (%s); run tools/catalog.py build"
                         % (catalog_path, exc))
    overrides = load_overrides(overrides_path)
    media = media_table(sources_path)
    icons = set(ICON_ID.findall(read_text(icons_path, "icon sprite")))
    for item in items:
        ov = overrides.get(item["id"])
        if not ov or not (ov.get("icon") or ov.get("media")):
            raise CatalogError("item %s has no icon or media: add it to catalog/overrides.json"
                               % item["id"])
        if ov.get("icon") and ov["icon"] not in icons:
            raise CatalogError("item %s: icon '%s' is not in the icon sprite" % (item["id"], ov["icon"]))
        for name in ov.get("media", []):
            need = media.get(name, {})
            if not need or any(set(v) != {"png", "webp"} for v in need.values()):
                raise CatalogError("item %s: media '%s' has no png and webp derivatives in SOURCES.json"
                                   % (item["id"], name))
    ctx = {"source": source, "overrides": overrides, "media": media}
    built = "Built from %s at %s (%s)." % (source["repo"], source["sha"][:12], source["date"])
    pages = {}
    for rel, tpl_path, body, root in [("index.html", template_path, None, "../")] + [
            ("%s/index.html" % slug(i["id"]), detail_path, i, "../../") for i in items]:
        ctx["root"] = root
        content = index_page(items, ctx) if body is None else detail_page(body, items, ctx)
        text = fill(read_text(tpl_path, "template"), {
            "root": root, "content": content, "built": esc(built),
            "title": esc(search_title(body) if body else "AI agent roles, skills and plugins | Hivemill catalog"),
            "description": esc("Browse reusable AI agent roles, skills, plugins and a desktop dashboard. Inspect the source and install components for your Hivemill factory."
                               if body is None else description(body, overrides[body["id"]])),
        })
        pages[rel] = apply_metadata(text, "catalog/" + rel)
    return pages


def render_args(args):
    return (args.catalog, args.overrides, args.template, args.detail_template, args.sources, args.icons)


def cmd_render(args):
    pages = render_site(*render_args(args))
    outdir = os.path.dirname(os.path.abspath(args.out))
    for rel, text in pages.items():
        path = args.out if rel == "index.html" else os.path.join(outdir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    print("wrote %d pages under %s" % (len(pages), outdir))
    return 0


def pages_drift(args):
    """Problems between a fresh render and the pages on disk (empty list = no drift)."""
    pages = render_site(*render_args(args))
    outdir = os.path.dirname(os.path.abspath(args.catalog))
    problems = []
    for rel, text in pages.items():
        path = os.path.join(outdir, rel)
        try:
            with open(path, encoding="utf-8") as fh:
                on_disk = fh.read()
        except OSError:
            problems.append("catalog/%s is missing" % rel)
            continue
        if on_disk != text:
            problems.append("catalog/%s differs from a fresh render" % rel)
    for d in subdirs(outdir, "."):
        if os.path.isfile(os.path.join(outdir, d, "index.html")) and d + "/index.html" not in pages:
            problems.append("catalog/%s/index.html belongs to no catalog item" % d)
    return problems


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("catalog.py: error: %s\n" % message)
        raise SystemExit(2)


def add_render_options(p):
    p.add_argument("--template", default=DEFAULT_TEMPLATE)
    p.add_argument("--detail-template", default=DEFAULT_DETAIL)
    p.add_argument("--sources", default=DEFAULT_SOURCES)
    p.add_argument("--icons", default=DEFAULT_ICONS)


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
    c.add_argument("--skip-pages", action="store_true",
                   help="do not compare the rendered pages (unit tests of the derivation only)")
    add_render_options(c)
    c.set_defaults(fn=cmd_check)
    v = sub.add_parser("verify-snippets")
    v.add_argument("--src", required=True)
    v.add_argument("--catalog", default=DEFAULT_CATALOG)
    v.add_argument("--network", action="store_true")
    v.set_defaults(fn=cmd_verify)
    r = sub.add_parser("render")
    r.add_argument("--in", dest="catalog", default=DEFAULT_CATALOG)
    r.add_argument("--out", required=True)
    r.add_argument("--overrides", default=DEFAULT_OVERRIDES)
    add_render_options(r)
    r.set_defaults(fn=cmd_render)
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
