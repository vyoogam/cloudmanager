"""Offline release regressions using real temporary Git repositories."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = base / "repo"
        self.repo.mkdir()
        self.fakebin = base / "bin"
        self.fakebin.mkdir()
        self.calls = base / "calls"
        self.env = dict(os.environ, GITHUB_REF_NAME="release/v1", GH_STATE="missing",
                        PATH=str(self.fakebin) + os.pathsep + os.environ["PATH"],
                        TEST_CALLS=str(self.calls), PYTHONDONTWRITEBYTECODE="1")
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.env.pop(key, None)
        (self.repo / "scripts").mkdir()
        for name in ("release", "release-tag", "build-version", "build-web", "install"):
            shutil.copy2(ROOT / "scripts" / name, self.repo / "scripts" / name)
        shutil.copy2(ROOT / "Makefile", self.repo / "Makefile")
        (self.repo / "VERSION").write_text("1.2.3\n")
        (self.repo / ".gitignore").write_text("cloudmanager\n")
        self.git("init", "-b", "release/v1")
        self.git("config", "user.name", "Release Test")
        self.git("config", "user.email", "release@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        remote = base / "remote.git"
        self.call("git", "init", "--bare", str(remote))
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-u", "origin", "release/v1")
        self.fake("gh", '''#!/usr/bin/env python3
import json, os, sys
state = os.environ['GH_STATE']
if state == 'missing':
    print('gh: Not Found (HTTP 404)', file=sys.stderr)
    sys.exit(1)
if state == 'error':
    print('gh: Forbidden (HTTP 403)', file=sys.stderr)
    sys.exit(1)
print(json.dumps({'draft': state != 'published', 'assets': [{}] if state == 'partial' else []}))
''')

    def fake(self, name, source):
        path = self.fakebin / name
        path.write_text(source)
        path.chmod(0o755)

    def call(self, *args, ok=True):
        result = subprocess.run(args, cwd=self.repo, env=self.env, text=True, capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def git(self, *args):
        return self.call("git", *args).stdout.strip()

    def tag(self, *args, ok=True):
        return self.call("scripts/release-tag", *args, ok=ok)

    def test_check_does_not_tag_and_create_can_resume_same_commit(self):
        self.tag("v1.2.3", "--check")
        self.assertEqual(self.git("tag"), "")
        head = self.git("rev-parse", "HEAD")
        self.tag("v1.2.3")
        self.assertEqual(self.git("rev-parse", "v1.2.3^{commit}"), head)
        self.tag("v1.2.3")
        self.assertIn("refs/tags/v1.2.3", self.git("ls-remote", "--tags", "origin"))

    def test_published_partial_or_unknown_remote_state_is_rejected(self):
        for state in ("published", "partial", "error"):
            with self.subTest(state=state):
                self.env["GH_STATE"] = state
                self.tag("v1.2.3", "--check", ok=False)
                self.assertEqual(self.git("tag"), "")

    def test_invalid_version_wrong_branch_and_mismatched_pin_are_rejected(self):
        for version in ("v01.2.3", "v1.2.3-rc1", "v1.2.4", "$(touch injected)"):
            with self.subTest(version=version):
                self.tag(version, "--check", ok=False)
        self.assertFalse((self.repo / "injected").exists())
        self.env["GITHUB_REF_NAME"] = "dev/work"
        self.tag("v1.2.3", "--check", ok=False)

    def test_tag_cannot_be_moved(self):
        self.git("tag", "v1.2.3")
        (self.repo / "change").write_text("new\n")
        self.git("add", "change")
        self.git("commit", "-m", "new commit")
        self.git("push", "origin", "release/v1")
        result = self.tag("v1.2.3", "--check", ok=False)
        self.assertIn("another commit", result.stderr)

    def test_dirty_checkout_and_older_version_are_rejected(self):
        (self.repo / "uncommitted").touch()
        self.tag("v1.2.3", "--check", ok=False)
        (self.repo / "uncommitted").unlink()
        self.git("tag", "v1.3.0")
        result = self.tag("v1.2.3", "--check", ok=False)
        self.assertIn("older", result.stderr)

    def test_build_and_version_do_not_bump_version(self):
        self.fake("go", '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_CALLS"\n')
        before = (self.repo / "VERSION").read_bytes()
        self.call("make", "build")
        self.call("make", "version")
        self.assertEqual(before, (self.repo / "VERSION").read_bytes())
        self.assertIn("main.Version=1.2.3-dev.", self.calls.read_text())
        self.git("tag", "v1.2.3")
        self.assertEqual(self.call("scripts/build-version").stdout.strip(), "1.2.3")
        (self.repo / "VERSION").write_text("broken\n")
        previous = self.calls.read_text()
        self.call("make", "build", ok=False)
        self.assertEqual(previous, self.calls.read_text())

    def test_frontend_is_built_before_go(self):
        (self.repo / "web").mkdir()
        (self.repo / "web/package.json").write_text("{}")
        for name in ("npm", "go"):
            self.fake(name, f'#!/bin/sh\nprintf "%s\\n" "{name} $*" >> "$TEST_CALLS"\n')
        self.call("make", "build")
        calls = self.calls.read_text().splitlines()
        self.assertEqual(calls[:2], ["npm ci --no-audit --no-fund", "npm run build"])
        self.assertTrue(calls[2].startswith("go build "))
        self.fake("npm", "#!/bin/sh\nexit 1\n")
        before = self.calls.read_text()
        self.call("make", "build", ok=False)
        self.assertEqual(before, self.calls.read_text())

    def test_embedded_server_cannot_silently_skip_missing_frontend(self):
        (self.repo / "internal/server").mkdir(parents=True)
        (self.repo / "internal/server/static.go").touch()
        self.call("scripts/build-web", ok=False)

    def test_ci_rejects_uncommitted_embedded_assets(self):
        (self.repo / "web").mkdir()
        (self.repo / "web/package.json").write_text("{}")
        assets = self.repo / "internal/server/static"
        assets.mkdir(parents=True)
        (assets / "index.html").write_text("fresh assets")
        # Exercise the CI source/artifact consistency gate independently of compilation.
        self.call("make", "-o", "test", "-o", "build", "ci", ok=False)
        self.git("add", ".")
        self.git("commit", "-m", "frontend and assets")
        self.call("make", "-o", "test", "-o", "build", "ci")
        (assets / "index.html").write_text("stale committed assets")
        self.call("make", "-o", "test", "-o", "build", "ci", ok=False)

    def test_release_prep_only_updates_version(self):
        self.call("scripts/release", "v1.2.4", ok=False)
        self.git("switch", "-c", "dev/next")
        self.call("scripts/release", "v1.2.4")
        self.assertEqual(self.git("diff", "--name-only"), "VERSION")
        self.assertEqual((self.repo / "VERSION").read_text(), "1.2.4\n")

    def test_installer_uses_latest_published_tag_and_mac_universal_archive(self):
        self.fake("uname", '#!/bin/sh\n[ "$1" = -s ] && echo Darwin || echo arm64\n')
        # Stop at archive download: capture its exact URL without installing anything.
        self.fake("curl", '''#!/bin/sh
case "$*" in
  *releases/latest*) printf '%s' 'https://github.com/vyoogam/cloudmanager/releases/tag/v1.2.3'; exit 0 ;;
  *) printf '%s\\n' "$*" >> "$TEST_CALLS"; exit 22 ;;
esac
''')
        self.call("scripts/install", "--binary", "--bin-dir", str(self.repo / "bin"), ok=False)
        self.assertIn("/v1.2.3/cloudmanager_Darwin_all.tar.gz", self.calls.read_text())


if __name__ == "__main__":
    unittest.main()
