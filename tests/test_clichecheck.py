import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from pipeline import clichecheck


def run(*argv: str, actions: bool = False) -> tuple[int, str]:
    out = io.StringIO()
    env = {"GITHUB_ACTIONS": "true"} if actions else {}
    with mock.patch.dict(os.environ, env, clear=False), redirect_stdout(out):
        if not actions:
            os.environ.pop("GITHUB_ACTIONS", None)
        code = clichecheck.main(list(argv))
    return code, out.getvalue()


class Advisory(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.dirty = Path(self.directory.name) / "dirty.md"
        self.dirty.write_text("We delve into the register.\n")
        self.clean = Path(self.directory.name) / "clean.md"
        self.clean.write_text("Plain words.\n")

    def test_a_finding_fails_by_default(self):
        code, output = run(str(self.dirty))
        self.assertEqual(code, 1)
        self.assertIn("delve", output)

    def test_advisory_reports_the_finding_but_passes(self):
        code, output = run("--advisory", str(self.dirty))
        self.assertEqual(code, 0)
        self.assertIn("1 finding(s)", output)

    def test_a_clean_file_passes_either_way(self):
        self.assertEqual(run(str(self.clean))[0], 0)
        self.assertEqual(run("--advisory", str(self.clean))[0], 0)

    def test_under_github_actions_a_finding_becomes_a_warning_annotation(self):
        _, output = run("--advisory", str(self.dirty), actions=True)
        self.assertRegex(output, r"::warning file=.*dirty\.md,line=1,title=clichecheck::")

    def test_no_annotation_outside_github_actions(self):
        _, output = run("--advisory", str(self.dirty))
        self.assertNotIn("::warning", output)


class Annotate(unittest.TestCase):
    def test_escapes_what_github_would_misread(self):
        line = "a.md:3: [x] label — 100% sure"
        self.assertEqual(clichecheck.annotate(line), "::warning file=a.md,line=3,title=clichecheck::[x] label — 100%25 sure")

    def test_a_line_that_is_not_a_finding_is_ignored(self):
        self.assertIsNone(clichecheck.annotate("clichecheck: clean"))


if __name__ == "__main__":
    unittest.main()
