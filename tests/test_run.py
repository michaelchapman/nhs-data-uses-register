import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import facts, run

from .fixtures import workbook_bytes


def tree(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class WorkbookBuild(unittest.TestCase):
    def test_a_one_off_workbook_build_writes_nothing_to_the_data_store(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "datausesregister_october2099.xlsx"
            workbook.write_bytes(workbook_bytes())
            out = Path(directory) / "site"
            before = tree(run.ROOT / "data")
            argv = ["run", "--workbook", str(workbook), "--output", str(out)]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                run.main()
            after = tree(run.ROOT / "data")
            self.assertTrue((out / "index.html").exists())
        self.assertEqual(before, after)

    def test_a_one_off_workbook_build_shows_none_of_the_stores_history(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "datausesregister_october2099.xlsx"
            workbook.write_bytes(workbook_bytes())
            out = Path(directory) / "site"
            argv = ["run", "--workbook", str(workbook), "--output", str(out)]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"), \
                    mock.patch.object(run.changes_module, "every_edition") as every_edition:
                run.main()
            every_edition.assert_not_called()
            # Only the workbook's own changes page: none for the store's editions.
            self.assertEqual([p.name for p in (out / "changes").iterdir()], ["index.html"])
            changes = (out / "changes" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("Editions processed", changes)
            for edition in facts.stored_editions("data-uses-register"):
                self.assertNotIn(f"/changes/{edition}/", changes)


if __name__ == "__main__":
    unittest.main()
