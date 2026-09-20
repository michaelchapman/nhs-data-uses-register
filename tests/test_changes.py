import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import changes, facts
from pipeline.extract import extract

from .fixtures import NEW_NAME, OLD_NAME, dataset_aliases, workbook_bytes

REGISTER = "test-register"
FIRST = "DARS-NIC-1-AAAAA"
SECOND = "DARS-NIC-2-BBBBB"
V2 = "DARS-NIC-1-AAAAA-v2"


class Changes(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patch = mock.patch.object(facts, "FACTS_ROOT", Path(self.directory.name))
        patch.start()
        self.addCleanup(patch.stop)
        alias_patch = dataset_aliases()
        alias_patch.__enter__()
        self.addCleanup(lambda: alias_patch.__exit__(None, None, None))
        self.versions = {a["base_reference"]: a["versions"] for a in extract(workbook_bytes())["agreements"]}

    def edited(self, base=FIRST, index=-1, **fields):
        changed = copy.deepcopy(self.versions)
        changed[base][index].update(fields)
        return changed

    def record(self, *editions):
        for edition, versions in editions:
            facts.append_edition(REGISTER, edition, versions)

    # Comparing two editions

    def test_the_first_edition_has_nothing_to_compare_with(self):
        self.record(("july2026", self.versions))
        result = changes.diff(REGISTER, "july2026")
        self.assertFalse(result["comparable"])
        self.assertEqual(result["reason"], "first-edition")

    def test_an_unchanged_edition_reports_nothing(self):
        self.record(("july2026", self.versions), ("august2026", copy.deepcopy(self.versions)))
        result = changes.diff(REGISTER, "august2026")
        self.assertTrue(result["comparable"])
        self.assertEqual((result["added"], result["amended"], result["removed"]), ([], [], []))

    def test_an_edited_field_is_an_amendment_that_names_the_field(self):
        self.record(("july2026", self.versions),
                    ("august2026", self.edited(end_date="2031-06-01")))
        result = changes.diff(REGISTER, "august2026")
        self.assertEqual([a["reference"] for a in result["amended"]], [V2])
        self.assertEqual(result["amended"][0]["fields"], ["End date"])
        self.assertEqual(result["amended"][0]["base"], FIRST)

    def test_reformatting_alone_is_not_an_amendment(self):
        # The same title, retyped with a curly apostrophe and doubled spaces.
        retyped = self.versions[FIRST][-1]["title"].replace(" ", "  ")
        self.record(("july2026", self.versions), ("august2026", self.edited(title=retyped)))
        result = changes.diff(REGISTER, "august2026")
        self.assertEqual(result["amended"], [])

    def test_a_controller_restated_in_capitals_is_not_an_amendment(self):
        # The register restated 1,302 controller lists this way in October 2021.
        shouted = [c.upper() for c in self.versions[FIRST][-1]["controllers"]]
        self.record(("july2026", self.versions), ("august2026", self.edited(controllers=shouted)))
        self.assertEqual(changes.diff(REGISTER, "august2026")["amended"], [])
        self.assertEqual(changes.history(REGISTER)[FIRST]["events"], [])

    def test_a_changed_controller_is_still_an_amendment(self):
        other = self.versions[FIRST][-1]["controllers"] + ["A NEW CONTROLLER LTD"]
        self.record(("july2026", self.versions), ("august2026", self.edited(controllers=other)))
        self.assertEqual(
            [a["fields"] for a in changes.diff(REGISTER, "august2026")["amended"]], [["Data controllers"]]
        )

    def test_a_new_agreement_is_new_and_a_new_version_is_a_renewal(self):
        without = {FIRST: copy.deepcopy(self.versions[FIRST][:1])}
        self.record(("july2026", without), ("august2026", self.versions))
        result = changes.diff(REGISTER, "august2026")
        kinds = {a["reference"]: a["kind"] for a in result["added"]}
        self.assertEqual(kinds[V2], "renewal")
        self.assertEqual(kinds["DARS-NIC-2-BBBBB-v1"], "new")

    def test_a_version_that_leaves_the_register_is_removed(self):
        self.record(("july2026", self.versions), ("august2026", {FIRST: self.versions[FIRST]}))
        result = changes.diff(REGISTER, "august2026")
        self.assertEqual([r["reference"] for r in result["removed"]], ["DARS-NIC-2-BBBBB-v1"])

    def test_months_with_no_edition_of_their_own_are_named(self):
        self.record(("july2026", self.versions), ("october2026", copy.deepcopy(self.versions)))
        self.assertEqual(
            changes.diff(REGISTER, "october2026")["skipped"], ["august2026", "september2026"]
        )

    # The point of deriving rather than storing

    def test_a_relabelled_dataset_is_not_an_amendment(self):
        renamed = copy.deepcopy(self.versions)
        for dataset in renamed[SECOND][0]["datasets"]:
            if dataset["name"] == NEW_NAME:
                dataset["name"] = OLD_NAME
        self.record(("july2026", self.versions), ("august2026", renamed))
        # The alias file in force says these two names are one dataset.
        self.assertEqual(changes.diff(REGISTER, "august2026")["amended"], [])

    def test_the_same_stored_editions_answer_differently_under_a_different_alias_file(self):
        renamed = copy.deepcopy(self.versions)
        for dataset in renamed[SECOND][0]["datasets"]:
            if dataset["name"] == NEW_NAME:
                dataset["name"] = OLD_NAME
        self.record(("july2026", self.versions), ("august2026", renamed))
        # Nothing stored changes; only the aliases applied at comparison time.
        result = changes.diff(REGISTER, "august2026", alias_map={})
        self.assertEqual([a["fields"] for a in result["amended"]], [["Datasets"]])

    def test_no_comparison_is_ever_refused(self):
        self.record(("july2026", self.versions), ("august2026", copy.deepcopy(self.versions)))
        result = changes.diff(REGISTER, "august2026")
        self.assertNotIn("fingerprint_version", result)
        self.assertTrue(result["comparable"])

    # The per-agreement timeline

    def test_history_records_when_an_agreement_was_first_listed(self):
        self.record(("july2026", self.versions))
        entry = changes.history(REGISTER)[FIRST]
        self.assertEqual(entry["first_edition"], "july2026")
        self.assertTrue(entry["first_is_earliest"])
        self.assertEqual(sorted(entry["first_versions"]), ["DARS-NIC-1-AAAAA-v1", V2])
        self.assertEqual(entry["events"], [])

    def test_history_names_the_fields_each_edition_moved(self):
        self.record(("july2026", self.versions),
                    ("august2026", self.edited(end_date="2031-06-01")),
                    ("september2026", self.edited(end_date="2031-06-01", commercial="Yes")))
        entry = changes.history(REGISTER)[FIRST]
        self.assertEqual([e["edition"] for e in entry["events"]], ["august2026", "september2026"])
        self.assertEqual(entry["events"][0]["fields"], ["End date"])
        self.assertEqual(entry["events"][1]["fields"], ["Commercial purposes"])
        self.assertEqual(entry["amendments"], 2)

    def test_history_ignores_an_edition_that_only_reformatted(self):
        retyped = self.versions[FIRST][-1]["title"].replace(" ", "  ")
        self.record(("july2026", self.versions), ("august2026", self.edited(title=retyped)))
        self.assertEqual(changes.history(REGISTER)[FIRST]["events"], [])

    def test_history_reaches_every_edition_not_only_the_newest(self):
        self.record(("july2026", self.versions),
                    ("august2026", self.edited(end_date="2031-06-01")),
                    ("september2026", copy.deepcopy(self.versions)))
        entry = changes.history(REGISTER)[FIRST]
        # Reverted in September, so both edits are events.
        self.assertEqual([e["edition"] for e in entry["events"]], ["august2026", "september2026"])

    def test_history_of_an_empty_store_is_empty(self):
        self.assertEqual(changes.history(REGISTER), {})


if __name__ == "__main__":
    unittest.main()
