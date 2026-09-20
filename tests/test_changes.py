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

    def with_dataset_attribute(self, key, value):
        changed = copy.deepcopy(self.versions)
        changed[SECOND][0]["datasets"][0][key] = value
        return changed

    def test_a_dataset_released_under_a_new_legal_basis_is_an_amendment(self):
        # December 2022: the register dropped "s261(1) and" from the legal basis
        # cited on 10,066 dataset rows. The fingerprints counted it; so must this.
        self.record(("july2026", self.versions),
                    ("august2026", self.with_dataset_attribute("legal_basis", "Some other legal basis")))
        result = changes.diff(REGISTER, "august2026")
        self.assertEqual([a["fields"] for a in result["amended"]], [["Datasets"]])

    def test_a_dataset_reclassified_as_non_sensitive_is_an_amendment(self):
        self.record(("july2026", self.versions),
                    ("august2026", self.with_dataset_attribute("sensitivity", "Non-Sensitive")))
        self.assertEqual(len(changes.diff(REGISTER, "august2026")["amended"]), 1)

    def test_a_dataset_attribute_retyped_is_not_an_amendment(self):
        original = self.versions[SECOND][0]["datasets"][0]["legal_basis"]
        self.record(("july2026", self.versions),
                    ("august2026", self.with_dataset_attribute("legal_basis", original.upper() + "  ")))
        self.assertEqual(changes.diff(REGISTER, "august2026")["amended"], [])

    def test_a_relabelled_dataset_with_a_new_legal_basis_is_still_an_amendment(self):
        changed = copy.deepcopy(self.versions)
        for dataset in changed[SECOND][0]["datasets"]:
            if dataset["name"] == NEW_NAME:
                dataset["name"] = OLD_NAME  # aliased to the same dataset
                dataset["legal_basis"] = "Some other legal basis"
        self.record(("july2026", self.versions), ("august2026", changed))
        result = changes.diff(REGISTER, "august2026")
        self.assertEqual([a["fields"] for a in result["amended"]], [["Datasets"]])

    def test_a_dataset_that_loses_one_of_several_records_is_an_amendment(self):
        # HES Critical Care went from four records to three in January 2023, with
        # every individual value still present on another row.
        twice = copy.deepcopy(self.versions)
        extra = copy.deepcopy(twice[SECOND][0]["datasets"][0])
        extra["sensitivity"], extra["legal_basis"] = "Non-Sensitive", "Another basis"
        twice[SECOND][0]["datasets"].append(extra)
        third = copy.deepcopy(twice)
        both = copy.deepcopy(extra)
        both["sensitivity"] = twice[SECOND][0]["datasets"][0]["sensitivity"]
        third[SECOND][0]["datasets"].append(both)
        self.record(("july2026", third), ("august2026", twice))
        self.assertEqual(
            [a["fields"] for a in changes.diff(REGISTER, "august2026")["amended"]], [["Datasets"]]
        )

    def test_a_row_shows_its_agreements_organisation_not_the_versions_own(self):
        # DARS-NIC-204580-F5B0C-v0.6 was applied for by a trust; the agreement is
        # now a cancer alliance's, and its page says so.
        older = copy.deepcopy(self.versions)
        older[FIRST][0]["organisation"] = "AN EARLIER APPLICANT"
        self.record(("july2026", older), ("august2026", self.edited(end_date="2031-06-01")))
        # The older version is untouched, so amend it too and look at its row.
        moved = copy.deepcopy(older)
        moved[FIRST][0]["end_date"] = "2031-06-01"
        facts.append_edition(REGISTER, "september2026", moved)
        row = next(a for a in changes.diff(REGISTER, "september2026")["amended"]
                   if a["reference"] == "DARS-NIC-1-AAAAA-v1")
        self.assertEqual(row["org"], older[FIRST][-1]["organisation"])
        self.assertNotEqual(row["org"], "AN EARLIER APPLICANT")

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
