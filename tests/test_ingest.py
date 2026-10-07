import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from pipeline import facts, ingest

from .fixtures import dataset_aliases, workbook_bytes

REGISTER = "data-uses-register"


class Ingest(unittest.TestCase):
    """Ingest records an edition's facts and its provenance, and reports what changed."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.raw = root / "raw"
        self.raw.mkdir()
        patch = mock.patch.object(facts, "FACTS_ROOT", root / "facts")
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
        self.assertEqual(
            sorted(facts.read_edition(REGISTER, "august2026")), ["DARS-NIC-1-AAAAA", "DARS-NIC-2-BBBBB"]
        )

    def test_every_edition_is_kept(self):
        self.run_ingest(str(self.workbook("july2026")), str(self.workbook("september2026")))
        self.assertEqual(facts.stored_editions(REGISTER), ["july2026", "september2026"])
        # Each can be built from, not only the newest.
        for edition in ("july2026", "september2026"):
            self.assertEqual(len(facts.read_extract(REGISTER, edition)["agreements"]), 2)

    def test_editions_may_arrive_in_any_order(self):
        self.run_ingest(str(self.workbook("september2026")))
        self.run_ingest(str(self.workbook("july2026")))
        self.assertEqual(facts.stored_editions(REGISTER), ["july2026", "september2026"])

    def test_the_manifest_records_where_each_edition_came_from(self):
        self.run_ingest(str(self.workbook("august2026")))
        (entry,) = facts.read_manifest(REGISTER)
        self.assertEqual(entry["edition"], "august2026")
        self.assertEqual(entry["source_file"], "datausesregister_august2026.xlsx")
        self.assertEqual(len(entry["sha256"]), 64)
        self.assertEqual(entry["counts"]["agreements"], 2)
        self.assertEqual(entry["counts"]["agreement_versions"], 3)
        # Organisations and datasets depend on the alias files, and would date.
        self.assertEqual(set(entry["counts"]), {"agreements", "agreement_versions"})
        self.assertNotIn("has_full_extract", entry)

    def test_a_source_url_is_recorded_when_given(self):
        self.run_ingest("--source-url", "https://example.test/archived.xlsx", str(self.workbook("august2026")))
        self.assertEqual(facts.manifest_entry(REGISTER, "august2026")["source_url"], "https://example.test/archived.xlsx")

    def test_ingesting_the_same_workbook_again_keeps_when_it_was_first_ingested(self):
        path = self.workbook("august2026")
        self.run_ingest(str(path))
        # Dated well before any run, so a rewritten entry could not match it.
        first = {**facts.manifest_entry(REGISTER, "august2026"), "ingested": "2000-01-01T00:00:00+00:00"}
        facts.upsert(REGISTER, first)
        self.run_ingest(str(path))
        self.assertEqual(facts.manifest_entry(REGISTER, "august2026"), first)

    def test_a_source_url_given_again_replaces_only_the_url(self):
        path = self.workbook("august2026")
        self.run_ingest(str(path))
        first = facts.manifest_entry(REGISTER, "august2026")
        self.run_ingest("--source-url", "https://example.test/archived.xlsx", str(path))
        self.assertEqual(
            facts.manifest_entry(REGISTER, "august2026"),
            {**first, "source_url": "https://example.test/archived.xlsx"},
        )

    def test_a_later_edition_reports_what_it_changed(self):
        self.run_ingest(str(self.workbook("july2026")))
        output = self.run_ingest(str(self.workbook("august2026")))
        self.assertIn("vs july2026: +0 added, ~0 amended, -0 removed", output)

    def test_ingesting_the_same_edition_twice_writes_nothing_the_second_time(self):
        path = self.workbook("august2026")
        self.run_ingest(str(path))
        before = {p: p.stat().st_mtime_ns for p in facts.register_dir(REGISTER).rglob("*.json")}
        self.assertIn(facts.manifest_path(REGISTER), before)
        output = self.run_ingest(str(path))
        self.assertIn("facts -> 0 new version states in 0 agreement file(s)", output)
        self.assertIn("0 newly released file(s)", output)
        after = {p: p.stat().st_mtime_ns for p in before}
        self.assertEqual(after, before)

    def test_a_workbook_with_no_agreements_is_refused_rather_than_recorded(self):
        with mock.patch("pipeline.extract.extract", return_value={"agreements": [], "organisations": [], "datasets": []}):
            with self.assertRaises(SystemExit):
                self.run_ingest(str(self.workbook("august2026")))
        self.assertEqual(facts.stored_editions(REGISTER), [])

    def test_a_missing_workbook_is_named(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_ingest(str(self.raw / "datausesregister_june2026.xlsx"))
        self.assertIn("not found", str(caught.exception))

    def test_a_source_url_needs_a_single_workbook(self):
        with self.assertRaises(SystemExit):
            self.run_ingest("--source-url", "https://example.test/x.xlsx",
                            str(self.workbook("july2026")), str(self.workbook("august2026")))

    def test_verify_passes_the_workbooks_that_were_ingested(self):
        july, august = self.workbook("july2026"), self.workbook("august2026")
        self.run_ingest(str(july), str(august))
        with mock.patch("pipeline.extract.extract") as extract:
            output = self.run_ingest("--verify", str(august), str(july))
        extract.assert_not_called()
        self.assertIn("ok       july2026  datausesregister_july2026.xlsx", output)
        self.assertIn("ok       august2026", output)

    def test_verify_names_a_changed_workbook_and_fails(self):
        path = self.workbook("august2026")
        self.run_ingest(str(path))
        path.write_bytes(path.read_bytes()[:-10])
        with self.assertRaises(SystemExit) as caught:
            self.run_ingest("--verify", str(path))
        self.assertIn("do not match the manifest", str(caught.exception))

    def test_verify_fails_when_an_ingested_edition_has_no_workbook(self):
        july, august = self.workbook("july2026"), self.workbook("august2026")
        self.run_ingest(str(july), str(august))
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            ingest.main(["--verify", str(august)])
        self.assertIn("MISSING  july2026  datausesregister_july2026.xlsx", out.getvalue())

    def test_verify_lists_a_new_workbook_without_failing_or_recording_it(self):
        self.run_ingest(str(self.workbook("july2026")))
        output = self.run_ingest("--verify", str(self.raw / "datausesregister_july2026.xlsx"),
                                 str(self.workbook("august2026")))
        self.assertIn("new      august2026", output)
        self.assertEqual(facts.stored_editions(REGISTER), ["july2026"])


if __name__ == "__main__":
    unittest.main()
