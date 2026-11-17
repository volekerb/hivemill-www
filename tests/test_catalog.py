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
        self.assertEqual(data["source"], {"repo": "volekerb/hivemill", "sha": git(self.src, "rev-parse", "HEAD")})
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
        r = tool("check", "--src", self.src, "--catalog", self.out, "--overrides", self.ov)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_reports_drift_with_diff(self):
        self.build()
        with open(self.out, encoding="utf-8") as fh:
            text = fh.read().replace("does the first thing", "edited by hand")
        self.write(self.out, text)
        r = tool("check", "--src", self.src, "--catalog", self.out, "--overrides", self.ov)
        self.assertEqual(r.returncode, 1)
        self.assertIn("-      \"purpose\": \"edited by hand\"", r.stdout)
        self.assertIn("+      \"purpose\": \"does the first thing\"", r.stdout)

    def test_check_rejects_checkout_at_other_sha(self):
        self.build()
        self.write(os.path.join(self.src, "roles", "alpha.md"), "# Role: alpha — changed\n")
        self.commit()
        r = tool("check", "--src", self.src, "--catalog", self.out, "--overrides", self.ov)
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

    def test_usage_errors_exit_2(self):
        self.assertEqual(tool("build").returncode, 2)
        self.assertEqual(tool("check", "--src", os.path.join(self.tmp, "nope")).returncode, 2)
        self.assertEqual(tool("bogus").returncode, 2)


if __name__ == "__main__":
    unittest.main()
