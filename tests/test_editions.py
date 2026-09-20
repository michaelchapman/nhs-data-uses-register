import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import editions
from pipeline.extract import extract

from .fixtures import dataset_aliases, workbook_bytes

REGISTER = "test-register"


class Store(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patch = mock.patch.object(editions, "EDITION_ROOT", Path(self.directory.name))
        patch.start()
        self.addCleanup(patch.stop)
        alias_patch = dataset_aliases()
        alias_patch.__enter__()
        self.addCleanup(lambda: alias_patch.__exit__(None, None, None))
        self.data = extract(workbook_bytes())

    def test_reading_back_gives_exactly_what_was_extracted(self):
        editions.write_extract(REGISTER, "september2026", self.data)
        again = editions.read_extract(REGISTER, "september2026")
        self.assertEqual(again["agreements"], self.data["agreements"])
        self.assertEqual(again["organisations"], self.data["organisations"])
        self.assertEqual(again["datasets"], self.data["datasets"])

    def test_only_the_versions_are_stored(self):
        editions.write_extract(REGISTER, "september2026", self.data)
        files = sorted((editions.agreements_dir(REGISTER)).glob("*.json"))
        self.assertEqual([f.name for f in files], ["dars-nic-1-aaaaa.json", "dars-nic-2-bbbbb.json"])
        stored = json.loads(files[0].read_text())
        self.assertEqual(sorted(stored), ["base_reference", "versions"])
        self.assertEqual([v["version"] for v in stored["versions"]], ["1", "2"])

    def test_an_unchanged_agreement_is_left_untouched(self):
        editions.write_extract(REGISTER, "august2026", self.data)
        path = editions.agreements_dir(REGISTER) / "dars-nic-1-aaaaa.json"
        before = path.stat().st_mtime_ns
        editions.write_extract(REGISTER, "september2026", extract(workbook_bytes()))
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_an_agreement_no_longer_in_the_register_is_removed(self):
        editions.write_extract(REGISTER, "august2026", self.data)
        fewer = {"agreements": [a for a in self.data["agreements"] if a["slug"] != "dars-nic-2-bbbbb"]}
        editions.write_extract(REGISTER, "september2026", fewer)
        self.assertFalse((editions.agreements_dir(REGISTER) / "dars-nic-2-bbbbb.json").exists())

    def test_the_store_holds_one_edition_and_says_which(self):
        self.assertEqual(editions.stored_editions(REGISTER), [])
        editions.write_extract(REGISTER, "august2026", self.data)
        editions.write_extract(REGISTER, "september2026", self.data)
        self.assertEqual(editions.stored_editions(REGISTER), ["september2026"])
        self.assertEqual(editions.latest_edition(REGISTER), "september2026")

    def test_asking_for_an_edition_that_is_not_stored_explains_what_to_do(self):
        editions.write_extract(REGISTER, "september2026", self.data)
        with self.assertRaises(SystemExit) as caught:
            editions.read_extract(REGISTER, "june2026")
        self.assertIn("only the september2026 edition", str(caught.exception))
        self.assertIn("--workbook", str(caught.exception))

    def test_two_agreements_with_one_file_name_are_refused(self):
        clash = {"agreements": [dict(self.data["agreements"][0]), dict(self.data["agreements"][0])]}
        with self.assertRaises(SystemExit):
            editions.write_extract(REGISTER, "september2026", clash)

    def test_marking_the_extract_updates_the_manifest(self):
        for edition in ("august2026", "september2026"):
            editions.upsert(REGISTER, {"edition": edition, "has_full_extract": False})
        editions.mark_full_extract(REGISTER, "september2026")
        flags = {e["edition"]: e["has_full_extract"] for e in editions.read_manifest(REGISTER)}
        self.assertEqual(flags, {"august2026": False, "september2026": True})


if __name__ == "__main__":
    unittest.main()
