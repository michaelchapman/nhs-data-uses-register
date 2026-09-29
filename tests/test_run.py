import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import facts, run, sources
from pipeline.extract import extract
from pipeline.rules import Rules

from .fixtures import dataset_aliases, workbook_bytes


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

    def test_a_build_reads_the_alias_lineage_and_exclusion_files_once(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "datausesregister_october2099.xlsx"
            workbook.write_bytes(workbook_bytes())
            argv = ["run", "--workbook", str(workbook), "--output", str(Path(directory) / "site")]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"), \
                    mock.patch.object(Rules, "load", wraps=Rules.load) as load:
                run.main()
        load.assert_called_once_with()


class FromStore(unittest.TestCase):
    """The review tools (`sectors`, `relations`) read the newest edition this way."""

    def test_the_newest_edition_can_be_read_without_passing_rules(self):
        with tempfile.TemporaryDirectory() as directory, dataset_aliases(), \
                mock.patch.object(facts, "FACTS_ROOT", Path(directory)):
            versions = {a["base_reference"]: a["versions"] for a in extract(workbook_bytes())["agreements"]}
            facts.append_edition("data-uses-register", "september2026", versions)
            data, edition, _ = run.from_store(sources.registers("data-uses-register")[0], None)
        self.assertEqual(edition, "september2026")
        self.assertEqual(len(data["agreements"]), len(versions))


if __name__ == "__main__":
    unittest.main()
