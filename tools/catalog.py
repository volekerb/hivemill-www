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
    icon, media     optional; only these two keys may come from
                    catalog/overrides.json ({"<item id>": {"icon": ..., "media": ...}})
  role extra:   skills  [{"name", "purpose"}] from roles/plugins/<name>/*/skills/*/SKILL.md
                permissions {"allow": [str], "deny": [str]} from roles/settings/<name>.json.in (when present)
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
import urllib.request

REPO = "volekerb/hivemill"
SCHEMA_VERSION = 1
OVERRIDE_KEYS = ("icon", "media")
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


def role_permissions(src, name):
    rel = "roles/settings/%s.json.in" % name
    if not os.path.isfile(os.path.join(src, rel)):
        return None
    perms = read_json(src, rel).get("permissions", {})
    out = {k: [str(x) for x in perms.get(k, [])] for k in ("allow", "deny")}
    return out if out["allow"] or out["deny"] else None


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
        item = {"id": "role:" + name, "kind": "role", "name": name,
                "purpose": role_purpose(src, rel), "snippets": snippets,
                "path": rel, "file": read(src, rel), "skills": skills}
        perms = role_permissions(src, name)
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
        item.update(overrides.get(item["id"], {}))
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

KINDS = [("role", "Roles", "roles",
          "Each role is one Markdown file. Copy it next to your own agents and edit it."),
         ("skill", "Skills", "skills",
          "Skills ship inside plugins. Install the plugin that carries the skill."),
         ("plugin", "Plugins", "plugins",
          "A plugin bundles skills and the helper commands they call."),
         ("dashboard", "Dashboard", "dashboard",
          "The dashboard that runs inside herdr-core. The screenshots are real.")]
KIND_LABEL = {k: label for k, label, _, _ in KINDS}
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
    return ('<picture><source type="image/webp" srcset="%s" sizes="(min-width: 52rem) 34rem, 100vw">'
            '<img src="%sassets/img/%s-%d.png" srcset="%s" sizes="(min-width: 52rem) 34rem, 100vw" '
            'width="%d" height="%d" alt="%s"%s decoding="async"></picture>'
            % (srcset("webp"), root, name, sizes[-1], srcset("png"), big["width"], big["height"],
               esc(alt), ' loading="lazy"' if lazy else ""))


def media_alt(name):
    return "herdr-core dashboard" if name == "herdr-panel" else \
        "herdr-core dashboard, %s panel" % name.replace("panel-", "").replace("-", " ")


def snippet_block(item, root):
    if not item["snippets"]:
        return ""
    return ('<div class="snip"><pre class="code"><code>%s</code></pre>'
            '<button class="copy" type="button" hidden data-copy aria-label="Copy install snippet for %s">'
            'Copy</button></div>' % (esc("\n".join(item["snippets"])), esc(item["name"])))


def meta_line(item):
    parts = []
    if item.get("skills"):
        parts.append("<span>Skills: %s</span>" % esc(", ".join(s["name"] for s in item["skills"])))
    if item.get("bins"):
        parts.append("<span>Commands: %s</span>" % esc(", ".join(item["bins"])))
    if item.get("plugin"):
        parts.append("<span>Plugin: %s</span>" % esc(item["plugin"]))
    return '<p class="meta">%s</p>' % " ".join(parts) if parts else ""


def soon_block(item):
    return ('<p class="soon"><strong>Coming soon.</strong> On main at the pinned commit: %s. Not there yet: %s.</p>'
            % (esc(", ".join(item["present"]) or "nothing"), esc(", ".join(item["absent"]))))


def entry(item, ctx):
    root, source = ctx["root"], ctx["source"]
    ov = ctx["overrides"][item["id"]]
    link = "%s/" % slug(item["id"])
    head = ""
    if ov.get("icon"):
        head = icon_svg(root, ov["icon"])
    gallery = ""
    if ov.get("media"):
        gallery = '<div class="shots">%s</div>' % "".join(
            '<figure class="fig">%s</figure>' % picture(root, n, ctx["media"][n], media_alt(n))
            for n in ov["media"])
    status = ' <span class="tag">coming soon</span>' if item.get("status") == "soon" else ""
    return ('<article class="entry" id="%s" data-item-id="%s" data-kind="%s" data-reveal>\n'
            '<div class="entry-main"><h3>%s<a href="%s">%s</a>%s</h3>\n<p class="purpose">%s</p>\n%s%s'
            '<p class="links"><a class="arrow-link" href="%s">Details%s</a> <a href="%s">Source: %s</a></p></div>\n'
            '<div class="entry-snip">%s</div>\n%s</article>'
            % (slug(item["id"]), esc(item["id"]), item["kind"], head, link, esc(item["name"]), status,
               esc(item["purpose"]), meta_line(item), soon_block(item) if item.get("status") == "soon" else "",
               link, icon_svg(root, "arrow"), esc(source_url(source, item)), esc(item["path"]),
               snippet_block(item, root), gallery))


def sections(text):
    """Split a Markdown source file into (heading, body) pairs on '## ' headings."""
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), 0)
        lines = lines[end + 1:]
    out, head, buf, fence = [], "Overview", [], False
    for line in lines:
        if line.startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            out.append((head, buf))
            head, buf = line[3:].strip(), []
        elif not (line.startswith("# ") and not fence and not out and not buf):
            buf.append(line)
    out.append((head, buf))
    return [(h, "\n".join(b).strip("\n")) for h, b in out if "".join(b).strip()]


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
    return [by_id[i] for i in ids if i in by_id]


def detail_page(item, items, ctx):
    root, source = ctx["root"], ctx["source"]
    ov = ctx["overrides"][item["id"]]
    out = ['<section class="page-head wrap detail-head">']
    out.append('<p class="crumb"><a href="../">Catalog</a> / %s</p>' % esc(KIND_LABEL[item["kind"]]))
    out.append("<h1>%s%s</h1>" % (icon_svg(root, ov["icon"], "i i--lg") if ov.get("icon") else "",
                                  esc(item["name"])))
    out.append('<p class="lede">%s</p>' % esc(item["purpose"]))
    out.append("</section>")
    out.append('<div class="wrap detail">')
    if item.get("status") == "soon":
        out.append(soon_block(item))
    if item["snippets"]:
        out.append('<section><h2>Install</h2>%s</section>' % snippet_block(item, root))
    if ov.get("media"):
        out.append('<section><h2>How it looks</h2><div class="shots">%s</div></section>' % "".join(
            '<figure class="fig">%s</figure>' % picture(root, n, ctx["media"][n], media_alt(n))
            for n in ov["media"]))
    meta = meta_line(item)
    if meta:
        out.append("<section><h2>Includes</h2>%s</section>" % meta)
    if item.get("skills"):
        out.append('<section><h2>Skills it ships with</h2><ul class="plain">%s</ul></section>' % "".join(
            "<li><strong>%s</strong> %s</li>" % (esc(s["name"]), esc(s["purpose"])) for s in item["skills"]))
    for head, body in sections(item.get("file", "")) if item.get("file", "").lstrip().startswith(("#", "---")) else []:
        out.append('<section><h2>%s</h2><div class="doc">%s</div></section>' % (esc(head), esc(body)))
    perms = item.get("permissions")
    if perms:
        for key, label in (("allow", "Allowed tools"), ("deny", "Blocked tools")):
            if perms.get(key):
                out.append('<section><h2>%s</h2><ul class="plain mono">%s</ul></section>' % (
                    label, "".join("<li>%s</li>" % esc(p) for p in perms[key])))
    rel = combines(item, items)
    if rel:
        out.append('<section><h2>Combines with</h2><ul class="plain">%s</ul></section>' % "".join(
            '<li><a href="../%s/">%s</a> %s</li>' % (slug(r["id"]), esc(r["name"]), esc(r["purpose"]))
            for r in rel))
    if item.get("file"):
        out.append('<section><h2>Full file</h2><p class="meta"><span>%s</span></p>'
                   '<div class="snip"><pre class="code" id="full"><code>%s</code></pre>'
                   '<button class="copy" type="button" hidden data-copy aria-label="Copy full file for %s">Copy full file</button></div>'
                   "</section>" % (esc(item["path"]), esc(item["file"].rstrip("\n")), esc(item["name"])))
    out.append('<p class="links"><a class="arrow-link" href="%s">Source on GitHub</a></p>'
               % esc(source_url(source, item)))
    out.append("</div>")
    return "\n".join(out)


def index_page(items, ctx):
    source = ctx["source"]
    out = ['<section class="page-head wrap">', "<h1>Catalog</h1>",
           '<p class="lede">The agent roles, kit skills and the herdr-core plugin you can copy into your own factory.</p>',
           '<p class="measure">Copy a role file, install a skill plugin or add the dashboard. Each piece stands on '
           'its own, so take one or combine several into your own factory.</p>',
           '<nav class="kinds" aria-label="Catalog sections">%s</nav>' % " ".join(
               '<a href="#%s">%s <span>%d</span></a>' % (anchor, label, sum(1 for i in items if i["kind"] == k))
               for k, label, anchor, _ in KINDS),
           "</section>", '<div class="wrap catalog">',
           '<p class="sr" role="status" aria-live="polite" id="live"></p>']
    for kind, label, anchor, intro in KINDS:
        group = [i for i in items if i["kind"] == kind]
        if not group:
            continue
        out.append('<section class="group" id="%s" data-group="%s"><div class="group-head"><h2>%s</h2><p>%s</p></div>'
                   % (anchor, kind, label, esc(intro)))
        out.extend(entry(i, ctx) for i in group)
        out.append("</section>")
    out.append("</div>")
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
    for rel, tpl_path, body, root, title in [("index.html", template_path, None, "../", "Catalog")] + [
            ("%s/index.html" % slug(i["id"]), detail_path, i, "../../", i["name"]) for i in items]:
        ctx["root"] = root
        content = index_page(items, ctx) if body is None else detail_page(body, items, ctx)
        pages[rel] = fill(read_text(tpl_path, "template"), {
            "root": root, "content": content, "built": esc(built),
            "title": esc(title + " | Hivemill" if body else "Catalog | Hivemill"),
            "description": esc("The agent roles, kit skills and the herdr-core plugin you can copy into "
                               "your own factory." if body is None else body["purpose"]),
        })
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
