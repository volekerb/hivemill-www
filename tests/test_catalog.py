"""Tests for tools/catalog.py, run as a subprocess against tests/fixtures/hivemill-mini."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(os.path.dirname(HERE), "tools", "catalog.py")
FIXTURE = os.path.join(HERE, "fixtures", "hivemill-mini")
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}


def git(src, *args):
    env = dict(os.environ, **GIT_ENV)
    return subprocess.run(["git", "-C", src] + list(args), check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def tool(*args):
    return subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True)


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = os.path.join(self.tmp, "src")
        shutil.copytree(FIXTURE, self.src)
        self.commit()
        self.out = os.path.join(self.tmp, "catalog.json")
        self.ov = os.path.join(self.tmp, "overrides.json")
        self.write(self.ov, "{}")

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def commit(self):
        if not os.path.isdir(os.path.join(self.src, ".git")):
            git(self.src, "init", "-q")
        git(self.src, "add", "-A")
        git(self.src, "commit", "-q", "-m", "fixture")

    def build(self):
        r = tool("build", "--src", self.src, "--out", self.out, "--overrides", self.ov)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.out, encoding="utf-8") as fh:
            return json.load(fh)

    def item(self, data, item_id):
        return next(i for i in data["items"] if i["id"] == item_id)

    def test_build_header_sorting_and_format(self):
        data = self.build()
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["source"], {"repo": "volekerb/hivemill", "sha": git(self.src, "rev-parse", "HEAD"),
                                          "date": "2026-01-01"})
        keys = [(i["kind"], i["name"]) for i in data["items"]]
        self.assertEqual(keys, sorted(keys))
        with open(self.out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.endswith("}\n"))
        self.assertIn('\n  "items": [', text)

    def test_roles_skip_common_and_use_heading_purpose(self):
        data = self.build()
        roles = [i["id"] for i in data["items"] if i["kind"] == "role"]
        self.assertEqual(roles, ["role:alpha", "role:beta"])
        self.assertEqual(self.item(data, "role:alpha")["purpose"], "does the first thing")

    def test_role_purpose_fallback_first_line(self):
        data = self.build()
        self.assertEqual(self.item(data, "role:beta")["purpose"], "Beta works without a heading. Second sentence.")

    def test_role_fallback_truncates_to_120(self):
        self.write(os.path.join(self.src, "roles", "gamma.md"), "x" * 200 + "\n")
        self.commit()
        self.assertEqual(len(self.item(self.build(), "role:gamma")["purpose"]), 120)

    def test_role_without_any_purpose_fails_build(self):
        self.write(os.path.join(self.src, "roles", "empty.md"), "# Just a title\n\n")
        self.commit()
        r = tool("build", "--src", self.src, "--out", self.out, "--overrides", self.ov)
        self.assertEqual(r.returncode, 1)
        self.assertIn("roles/empty.md", r.stderr)

    def test_role_snippets_and_skills(self):
        data = self.build()
        sha = data["source"]["sha"]
        alpha = self.item(data, "role:alpha")
        self.assertEqual(alpha["snippets"], [
            "curl -fsSLO https://raw.githubusercontent.com/volekerb/hivemill/%s/roles/alpha.md" % sha])
        beta = self.item(data, "role:beta")
        self.assertEqual(beta["snippets"][1],
                         "git clone --depth 1 https://github.com/volekerb/hivemill && claude "
                         "--plugin-dir hivemill/roles/plugins/beta/beta-skills")
        self.assertEqual(beta["skills"], [{"name": "tidy", "purpose": "Tidy the workspace."}])

    def test_marketplace_listed_plugin_uses_install_lines(self):
        data = self.build()
        self.assertEqual(self.item(data, "skill:hivemill/setup")["snippets"],
                         ["/plugin marketplace add volekerb/hivemill", "/plugin install hivemill@hivemill"])
        self.assertEqual(self.item(data, "skill:hivemill/setup")["purpose"], "Guided install of the mini factory.")

    def test_unlisted_kit_plugin_uses_plugin_dir_and_lists_bins(self):
        data = self.build()
        audit = self.item(data, "skill:mini-tools/audit")
        self.assertEqual(audit["snippets"], ["git clone --depth 1 https://github.com/volekerb/hivemill && "
                                             "claude --plugin-dir hivemill/plugins/kit-tools"])
        self.assertEqual(audit["bins"], ["mini-tool"])
        self.assertEqual(audit["purpose"], "Audit the spend of the mini factory.")

    def test_new_kit_plugin_is_picked_up_without_code_change(self):
        base = os.path.join(self.src, "plugins", "kit-new")
        self.write(os.path.join(base, ".claude-plugin", "plugin.json"),
                   '{"name": "hivemill-new", "description": "New kit."}')
        self.write(os.path.join(base, "skills", "fresh", "SKILL.md"),
                   "---\nname: fresh\ndescription: Fresh skill. More.\n---\n")
        self.commit()
        data = self.build()
        self.assertEqual(self.item(data, "skill:hivemill-new/fresh")["purpose"], "Fresh skill.")
        self.assertEqual(self.item(data, "plugin:hivemill-new")["purpose"], "New kit.")

    def test_plugin_items(self):
        data = self.build()
        plugins = [i["id"] for i in data["items"] if i["kind"] == "plugin"]
        self.assertEqual(plugins, ["plugin:hivemill", "plugin:mini-tools"])

    def test_dashboard_quotes_install_route_verbatim(self):
        data = self.build()
        dash = [i for i in data["items"] if i["kind"] == "dashboard"]
        self.assertEqual(len(dash), 1)
        self.assertEqual(dash[0]["id"], "dashboard:herdr-core")
        self.assertEqual(dash[0]["purpose"], "If you use the Herdr app, the mini factory can live inside it:")
        self.assertEqual(dash[0]["snippets"], [
            "sh plugins/hivemill/scripts/install.sh --herdr-app --dry-run   # show the plan",
            "sh plugins/hivemill/scripts/install.sh --herdr-app --yes"])

    def test_dashboard_without_install_route_fails_build(self):
        path = os.path.join(self.src, "docs", "herdr-app-dashboard.md")
        self.write(path, "# Mini dashboard\n\nIntro line.\n")
        self.commit()
        r = tool("build", "--src", self.src, "--out", self.out, "--overrides", self.ov)
        self.assertEqual(r.returncode, 1)
        self.assertIn("install route", r.stderr)

    def test_overrides_allow_icon_and_media(self):
        self.write(self.ov, json.dumps({"role:alpha": {"icon": "a.svg", "media": "a.png"}}))
        item = self.item(self.build(), "role:alpha")
        self.assertEqual((item["icon"], item["media"]), ("a.svg", "a.png"))

    def test_overrides_reject_purpose_with_exit_2(self):
        self.write(self.ov, json.dumps({"role:alpha": {"purpose": "hand written"}}))
        r = tool("build", "--src", self.src, "--out", self.out, "--overrides", self.ov)
        self.assertEqual(r.returncode, 2)
        self.assertIn("purpose", r.stderr)
        self.assertFalse(os.path.exists(self.out))

    def test_check_passes_when_equal(self):
        self.build()
        r = tool("check", "--src", self.src, "--catalog", self.out, "--overrides", self.ov, "--skip-pages")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_reports_drift_with_diff(self):
        self.build()
        with open(self.out, encoding="utf-8") as fh:
            text = fh.read().replace("does the first thing", "edited by hand")
        self.write(self.out, text)
        r = tool("check", "--src", self.src, "--catalog", self.out, "--overrides", self.ov, "--skip-pages")
        self.assertEqual(r.returncode, 1)
        self.assertIn("-      \"purpose\": \"edited by hand\"", r.stdout)
        self.assertIn("+      \"purpose\": \"does the first thing\"", r.stdout)

    def test_check_rejects_checkout_at_other_sha(self):
        self.build()
        self.write(os.path.join(self.src, "roles", "alpha.md"), "# Role: alpha — changed\n")
        self.commit()
        r = tool("check", "--src", self.src, "--catalog", self.out, "--overrides", self.ov, "--skip-pages")
        self.assertEqual(r.returncode, 2)
        self.assertIn("source.sha", r.stderr)

    def test_verify_snippets_ok(self):
        self.build()
        r = tool("verify-snippets", "--src", self.src, "--catalog", self.out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_verify_snippets_names_missing_role_file(self):
        self.build()
        os.remove(os.path.join(self.src, "roles", "alpha.md"))
        r = tool("verify-snippets", "--src", self.src, "--catalog", self.out)
        self.assertEqual(r.returncode, 1)
        self.assertIn("roles/alpha.md", r.stdout)

    def test_verify_snippets_names_missing_install_script(self):
        self.build()
        os.remove(os.path.join(self.src, "plugins", "hivemill", "scripts", "install.sh"))
        r = tool("verify-snippets", "--src", self.src, "--catalog", self.out)
        self.assertEqual(r.returncode, 1)
        self.assertIn("plugins/hivemill/scripts/install.sh", r.stdout)

    # ------------------------------------------------------------ render (T-1809)

    def render_site(self, extra_overrides=None, icon="ask"):
        """Build the fixture catalog and render it into tmp/site with the real templates."""
        data = self.build()
        ov = {i["id"]: {"icon": icon} for i in data["items"]}
        ov.update(extra_overrides or {})
        self.write(self.ov, json.dumps(ov))
        self.build()
        self.site = os.path.join(self.tmp, "site")
        r = self.run_render()
        return r

    def run_render(self, *extra):
        return tool("render", "--in", self.out, "--out", os.path.join(self.site, "index.html"),
                    "--overrides", self.ov, *extra)

    def page(self, rel):
        with open(os.path.join(self.site, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_render_lists_every_item_once_and_is_deterministic(self):
        r = self.render_site()
        self.assertEqual(r.returncode, 0, r.stderr)
        index = self.page("index.html")
        with open(self.out, encoding="utf-8") as fh:
            ids = [i["id"] for i in json.load(fh)["items"]]
        for item_id in ids:
            self.assertEqual(index.count('data-item-id="%s"' % item_id), 1, item_id)
        first = {rel: self.page(rel) for rel in ("index.html", "role-alpha/index.html")}
        self.assertEqual(self.run_render().returncode, 0)
        for rel, text in first.items():
            self.assertEqual(self.page(rel), text, rel)

    def test_render_without_js_shows_content_and_hides_copy_buttons(self):
        self.render_site()
        index = self.page("index.html")
        self.assertIn('<pre class="code"><code>', index)
        self.assertIn("<button class=\"copy\" type=\"button\" hidden", index)
        self.assertIn('aria-live="polite"', index)
        self.assertNotIn("class=\"chip\"", index)
        self.assertIn('id="roles"', index)
        self.assertIn("2026-01-01", index)
        self.assertIn(git(self.src, "rev-parse", "HEAD")[:12], index)

    def test_render_fails_when_an_item_has_no_icon_or_media(self):
        self.render_site()
        with open(self.ov, encoding="utf-8") as fh:
            ov = json.load(fh)
        del ov["role:alpha"]
        self.write(self.ov, json.dumps(ov))
        r = self.run_render()
        self.assertEqual(r.returncode, 1)
        self.assertIn("role:alpha has no icon or media", r.stderr)

    def test_render_fails_on_unknown_icon(self):
        self.render_site()
        with open(self.ov, encoding="utf-8") as fh:
            ov = json.load(fh)
        ov["role:alpha"] = {"icon": "no-such-icon"}
        self.write(self.ov, json.dumps(ov))
        r = self.run_render()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no-such-icon", r.stderr)

    def test_detail_page_has_full_file_copy_and_links_back(self):
        self.render_site()
        page = self.page("role-alpha/index.html")
        self.assertIn("Copy full file", page)
        with open(os.path.join(self.src, "roles", "alpha.md"), encoding="utf-8") as fh:
            first_line = fh.read().splitlines()[0]
        self.assertIn(first_line.replace("&", "&amp;"), page)
        self.assertIn('href="../../assets/css/catalog.css"', page)
        self.assertIn('href="../"', page)
        self.assertIn("/blob/%s/roles/alpha.md" % git(self.src, "rev-parse", "HEAD"), page)

    def test_check_fails_when_a_page_drifts_and_passes_when_fresh(self):
        self.render_site()
        site_catalog = os.path.join(self.site, "catalog.json")
        shutil.copy(self.out, site_catalog)
        base = ["check", "--src", self.src, "--catalog", site_catalog, "--overrides", self.ov]
        ok = tool(*base)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("pages match", ok.stdout)
        self.write(os.path.join(self.site, "index.html"), self.page("index.html") + "<!-- edit -->")
        bad = tool(*base)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("index.html differs from a fresh render", bad.stdout)
        self.assertEqual(tool(*base, "--skip-pages").returncode, 0)

    def test_check_fails_when_a_detail_page_is_missing(self):
        self.render_site()
        shutil.copy(self.out, os.path.join(self.site, "catalog.json"))
        shutil.rmtree(os.path.join(self.site, "role-beta"))
        r = tool("check", "--src", self.src, "--catalog", os.path.join(self.site, "catalog.json"),
                 "--overrides", self.ov)
        self.assertEqual(r.returncode, 1)
        self.assertIn("role-beta/index.html is missing", r.stdout)

    def test_ios_testflight_release_is_excluded(self):
        self.write(os.path.join(self.src, "plugins", "hivemill", "skills", "ios-testflight-release", "SKILL.md"),
                   "---\nname: ios-testflight-release\ndescription: Ship an iOS build.\n---\n\n# Release\n")
        self.commit()
        data = self.build()
        self.assertNotIn("skill:hivemill/ios-testflight-release", [i["id"] for i in data["items"]])
        self.assertIn("skill:hivemill/setup", [i["id"] for i in data["items"]])

    def test_hm_clean_is_coming_soon_only_while_pieces_are_missing(self):
        adr = os.path.join(self.src, "docs", "adr", "0008-resource-hygiene.md")
        self.write(adr, "# ADR 0008: Resource hygiene (hm-clean)\n\nStatus: accepted\n")
        self.write(os.path.join(self.src, "go", "internal", "kit", "clean", "fsx", "fsx.go"), "package fsx\n")
        self.commit()
        data = self.build()
        clean = self.item(data, "skill:hm-clean")
        self.assertEqual(clean["status"], "soon")
        self.assertEqual(clean["present"], ["go/internal/kit/clean/fsx"])
        self.assertIn("go/cmd/hm-clean", clean["absent"])
        self.assertEqual(clean["snippets"], [])
        self.write(self.ov, json.dumps({i["id"]: {"icon": "ask"} for i in data["items"]}))
        self.build()
        self.site = os.path.join(self.tmp, "site")
        self.assertEqual(self.run_render().returncode, 0)
        page = self.page("skill-hm-clean/index.html")
        self.assertIn("Coming soon.", page)
        self.assertIn("go/internal/kit/clean/fsx", page)
        self.assertNotIn("<pre", page)
        for rel, path in (("go/cmd/hm-clean/main.go", "x"), ("plugins/kit-clean/.keep", "x")):
            self.write(os.path.join(self.src, rel), path)
        self.commit()
        self.write(self.ov, "{}")
        self.assertNotIn("skill:hm-clean", [i["id"] for i in self.build()["items"]])

    def test_rendered_pages_pass_the_public_text_guard(self):
        guard = os.path.join(os.path.expanduser("~"), "factory", "ci", "public_text_guard.py")
        if not os.path.isfile(guard):
            self.skipTest("public_text_guard.py not on this machine; CI runs it on the push")
        self.render_site()
        for rel in ("index.html", "role-alpha/index.html"):
            r = subprocess.run([sys.executable, guard, "--no-terms", "text", os.path.join(self.site, rel)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, rel + r.stdout + r.stderr)

    def test_usage_errors_exit_2(self):
        self.assertEqual(tool("build").returncode, 2)
        self.assertEqual(tool("check", "--src", os.path.join(self.tmp, "nope")).returncode, 2)
        self.assertEqual(tool("bogus").returncode, 2)


if __name__ == "__main__":
    unittest.main()
