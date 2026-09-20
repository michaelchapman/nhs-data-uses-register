import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from pipeline import editions, facts, ingest, snapshot

from .fixtures import dataset_aliases, workbook_bytes

REGISTER = "data-uses-register"


class Ingest(unittest.TestCase):
    """Ingest writes three stores; these cover the facts one it gained last."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.raw = root / "raw"
        self.raw.mkdir()
        for module, attribute in (
            (facts, "FACTS_ROOT"), (editions, "EDITION_ROOT"), (snapshot, "SNAPSHOT_ROOT")
        ):
            patch = mock.patch.object(module, attribute, root / attribute.lower())
            patch.start()
            self.addCleanup(patch.stop)
        alias_patch = dataset_aliases()
        alias_patch.__enter__()
        self.addCleanup(lambda: alias_patch.__exit__(None, None, None))

    def workbook(self, edition: str) -> Path:
        path = self.raw / f"datausesregister_{edition}.xlsx"
        path.write_bytes(workbook_bytes())
        return path

    def run_ingest(self, *argv: str) -> str:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            ingest.main(list(argv))
        return out.getvalue() + err.getvalue()

    def test_ingesting_a_workbook_records_its_facts(self):
        output = self.run_ingest(str(self.workbook("august2026")))
        self.assertIn("facts ->", output)
        self.assertEqual(facts.stored_editions(REGISTER), ["august2026"])
        read = facts.read_edition(REGISTER, "august2026")
        self.assertEqual(sorted(read), ["DARS-NIC-1-AAAAA", "DARS-NIC-2-BBBBB"])

    def test_every_edition_is_kept_not_only_the_newest(self):
        self.run_ingest(str(self.workbook("july2026")), str(self.workbook("september2026")))
        self.assertEqual(facts.stored_editions(REGISTER), ["july2026", "september2026"])
        # The old store still holds exactly one edition; that is the difference.
        self.assertEqual(editions.stored_editions(REGISTER), ["september2026"])

    def test_a_backfill_records_facts_even_with_fingerprints_only(self):
        self.run_ingest(str(self.workbook("september2026")))
        self.run_ingest("--fingerprints-only", str(self.workbook("july2026")))
        self.assertEqual(facts.stored_editions(REGISTER), ["july2026", "september2026"])
        self.assertEqual(editions.stored_editions(REGISTER), ["september2026"])

    def test_ingesting_the_same_edition_twice_writes_nothing_the_second_time(self):
        path = self.workbook("august2026")
        self.run_ingest(str(path))
        output = self.run_ingest(str(path))
        self.assertIn("facts -> 0 new version states in 0 agreement file(s)", output)
        self.assertIn("0 newly released file(s)", output)

    def test_facts_only_leaves_the_stores_the_site_still_uses_alone(self):
        self.run_ingest(str(self.workbook("july2026")))
        before = sorted(p.stat().st_mtime_ns for p in snapshot.snapshot_dir(REGISTER).glob("*"))
        self.run_ingest("--facts-only", str(self.workbook("august2026")))
        self.assertEqual(facts.stored_editions(REGISTER), ["august2026", "july2026"][::-1])
        # No new fingerprint, and the one already written is untouched.
        self.assertEqual(sorted(p.stat().st_mtime_ns for p in snapshot.snapshot_dir(REGISTER).glob("*")), before)
        self.assertEqual(editions.stored_editions(REGISTER), ["july2026"])
        self.assertEqual([e["edition"] for e in editions.read_manifest(REGISTER)], ["july2026"])

    def test_the_legacy_extract_does_not_gain_the_row_by_row_detail(self):
        self.run_ingest(str(self.workbook("august2026")))
        stored = (editions.agreements_dir(REGISTER) / "dars-nic-1-aaaaa.json").read_text()
        self.assertNotIn("released_files", stored)
        self.assertIn("files_released", stored)


if __name__ == "__main__":
    unittest.main()
