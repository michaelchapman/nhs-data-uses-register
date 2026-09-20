import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import editions, facts
from pipeline.extract import extract

from .fixtures import dataset_aliases, workbook_bytes

REGISTER = "test-register"
FIRST = "DARS-NIC-1-AAAAA"
SECOND = "DARS-NIC-2-BBBBB"


def versions_by_base(data: dict) -> dict:
    return {a["base_reference"]: a["versions"] for a in data["agreements"]}


class Store(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patch = mock.patch.object(facts, "FACTS_ROOT", Path(self.directory.name))
        patch.start()
        self.addCleanup(patch.stop)
        alias_patch = dataset_aliases()
        alias_patch.__enter__()
        self.addCleanup(lambda: alias_patch.__exit__(None, None, None))
        self.versions = versions_by_base(extract(workbook_bytes()))

    def edited(self, base=FIRST, index=-1, **fields):
        """A copy of the register with one version's fields changed."""
        changed = copy.deepcopy(self.versions)
        changed[base][index].update(fields)
        return changed

    # The record

    def test_reading_an_edition_back_gives_exactly_what_was_recorded(self):
        facts.append_edition(REGISTER, "september2026", self.versions)
        self.assertEqual(facts.read_edition(REGISTER, "september2026"), self.versions)

    def test_a_state_holds_the_fields_and_the_record_holds_the_reference(self):
        facts.append_edition(REGISTER, "september2026", self.versions)
        stored = facts.read_agreement(REGISTER, FIRST)
        self.assertEqual(sorted(stored), ["base_reference", "versions"])
        record = stored["versions"][0]
        self.assertEqual(sorted(record), ["reference", "states", "version"])
        self.assertEqual(record["reference"], "DARS-NIC-1-AAAAA-v1")
        # The two identifying fields live on the record, never in a state, so
        # the two cannot disagree.
        self.assertNotIn("reference", record["states"][0])
        self.assertNotIn("version", record["states"][0])
        self.assertIn("title", record["states"][0])

    def test_versions_are_stored_in_version_order(self):
        facts.append_edition(REGISTER, "september2026", self.versions)
        stored = facts.read_agreement(REGISTER, FIRST)
        self.assertEqual([r["version"] for r in stored["versions"]], ["1", "2"])

    def test_the_edition_index_names_a_state_for_every_version(self):
        facts.append_edition(REGISTER, "september2026", self.versions)
        index = facts.edition_index(REGISTER, "september2026")
        self.assertEqual(index, {"DARS-NIC-1-AAAAA-v1": 0, "DARS-NIC-1-AAAAA-v2": 0, "DARS-NIC-2-BBBBB-v1": 0})

    # Append-only

    def test_recording_the_same_edition_again_writes_nothing(self):
        facts.append_edition(REGISTER, "september2026", self.versions)
        paths = sorted(facts.agreements_dir(REGISTER).glob("*.json"))
        before = {p: p.stat().st_mtime_ns for p in paths}
        counts = facts.append_edition(REGISTER, "september2026", versions_by_base(extract(workbook_bytes())))
        self.assertEqual(counts["files_written"], 0)
        self.assertEqual(counts["new_states"], 0)
        self.assertEqual({p: p.stat().st_mtime_ns for p in paths}, before)

    def test_an_unchanged_agreement_is_untouched_by_a_later_edition(self):
        facts.append_edition(REGISTER, "august2026", self.versions)
        untouched = facts.agreements_dir(REGISTER) / "dars-nic-2-bbbbb.json"
        before = untouched.stat().st_mtime_ns
        facts.append_edition(REGISTER, "september2026", self.edited(title="Maternity study (revised)"))
        self.assertEqual(untouched.stat().st_mtime_ns, before)

    def test_an_edited_version_appends_a_state_and_leaves_the_first_alone(self):
        facts.append_edition(REGISTER, "august2026", self.versions)
        counts = facts.append_edition(REGISTER, "september2026", self.edited(title="Maternity study (revised)"))
        self.assertEqual(counts["new_states"], 1)
        record = facts.read_agreement(REGISTER, FIRST)["versions"][1]
        self.assertEqual([s["title"] for s in record["states"]], ["Maternity study", "Maternity study (revised)"])
        self.assertEqual(facts.edition_index(REGISTER, "august2026")["DARS-NIC-1-AAAAA-v2"], 0)
        self.assertEqual(facts.edition_index(REGISTER, "september2026")["DARS-NIC-1-AAAAA-v2"], 1)

    def test_an_older_edition_still_reads_as_it_was_published(self):
        facts.append_edition(REGISTER, "august2026", self.versions)
        facts.append_edition(REGISTER, "september2026", self.edited(title="Maternity study (revised)"))
        was = facts.read_edition(REGISTER, "august2026")[FIRST][1]["title"]
        now = facts.read_edition(REGISTER, "september2026")[FIRST][1]["title"]
        self.assertEqual((was, now), ("Maternity study", "Maternity study (revised)"))

    def test_a_version_that_reverts_reuses_the_state_it_returns_to(self):
        facts.append_edition(REGISTER, "july2026", self.versions)
        facts.append_edition(REGISTER, "august2026", self.edited(title="Briefly different"))
        counts = facts.append_edition(REGISTER, "september2026", self.versions)
        self.assertEqual(counts["new_states"], 0)
        self.assertEqual(len(facts.read_agreement(REGISTER, FIRST)["versions"][1]["states"]), 2)
        self.assertEqual(facts.edition_index(REGISTER, "september2026")["DARS-NIC-1-AAAAA-v2"], 0)

    # Nothing is deleted

    def test_an_agreement_that_leaves_the_register_keeps_its_history(self):
        facts.append_edition(REGISTER, "august2026", self.versions)
        facts.append_edition(REGISTER, "september2026", {FIRST: self.versions[FIRST]})
        self.assertIsNotNone(facts.read_agreement(REGISTER, SECOND))
        self.assertIn(SECOND, facts.read_edition(REGISTER, "august2026"))
        self.assertNotIn(SECOND, facts.read_edition(REGISTER, "september2026"))

    # Storage is not sensitive to row order

    def test_reordering_a_versions_datasets_is_not_a_new_state(self):
        facts.append_edition(REGISTER, "august2026", self.versions)
        shuffled = copy.deepcopy(self.versions)
        shuffled[SECOND][0]["datasets"].reverse()
        self.assertEqual(facts.append_edition(REGISTER, "september2026", shuffled)["new_states"], 0)

    def test_a_changed_dataset_attribute_is_a_new_state(self):
        facts.append_edition(REGISTER, "august2026", self.versions)
        changed = copy.deepcopy(self.versions)
        changed[SECOND][0]["datasets"][0]["sensitivity"] = "Non-Sensitive"
        self.assertEqual(facts.append_edition(REGISTER, "september2026", changed)["new_states"], 1)

    # Editions

    def test_editions_are_listed_oldest_first_however_they_were_added(self):
        for edition in ("september2026", "july2021", "august2026"):
            facts.append_edition(REGISTER, edition, self.versions)
        self.assertEqual(facts.stored_editions(REGISTER), ["july2021", "august2026", "september2026"])
        self.assertEqual(facts.latest_edition(REGISTER), "september2026")

    def test_an_edition_that_is_not_stored_explains_what_to_do(self):
        facts.append_edition(REGISTER, "september2026", self.versions)
        with self.assertRaises(SystemExit) as caught:
            facts.read_edition(REGISTER, "june2026")
        self.assertIn("june2026", str(caught.exception))
        self.assertIn("pipeline.ingest", str(caught.exception))

    def test_two_agreements_with_one_file_name_are_refused(self):
        clash = dict(self.versions)
        clash["DARS/NIC/1/AAAAA"] = self.versions[FIRST]
        with self.assertRaises(SystemExit) as caught:
            facts.append_edition(REGISTER, "september2026", clash)
        self.assertIn("collides", str(caught.exception))

    def test_an_index_pointing_past_the_states_is_refused(self):
        facts.append_edition(REGISTER, "september2026", self.versions)
        path = facts.edition_path(REGISTER, "september2026")
        broken = json.loads(path.read_text())
        broken["versions"]["DARS-NIC-1-AAAAA-v1"] = 7
        path.write_text(json.dumps(broken))
        with self.assertRaises(SystemExit) as caught:
            facts.read_edition(REGISTER, "september2026")
        self.assertIn("re-ingest", str(caught.exception))

    # The point of it all

    def test_an_edition_read_back_assembles_into_the_same_site_data(self):
        """A stored edition and its workbook are interchangeable inputs."""
        facts.append_edition(REGISTER, "september2026", self.versions)
        rebuilt = editions.rehydrate(facts.read_edition(REGISTER, "september2026"))
        again = extract(workbook_bytes())
        self.assertEqual(rebuilt["agreements"], again["agreements"])
        self.assertEqual(rebuilt["organisations"], again["organisations"])
        self.assertEqual(rebuilt["datasets"], again["datasets"])


if __name__ == "__main__":
    unittest.main()
