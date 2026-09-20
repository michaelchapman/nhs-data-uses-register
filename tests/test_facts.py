import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import editions, facts
from pipeline.extract import extract, summarise_releases

from .fixtures import NEW_NAME, dataset_aliases, workbook_bytes

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
        self.assertNotIn("releases", record["states"][0])
        self.assertNotIn("files_released", record["states"][0])
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

    def test_datasets_are_presented_alphabetically_ignoring_case(self):
        mixed = copy.deepcopy(self.versions)
        first = mixed[SECOND][0]["datasets"][0]
        mixed[SECOND][0]["datasets"] = [
            {**first, "name": name} for name in ("Medicines dispensed", "MRIS report", "adult survey")
        ]
        facts.append_edition(REGISTER, "september2026", mixed)
        names = [d["name"] for d in facts.read_edition(REGISTER, "september2026")[SECOND][0]["datasets"]]
        self.assertEqual(names, ["adult survey", "Medicines dispensed", "MRIS report"])

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

    # File releases, which move every month by design

    def released(self, base=FIRST, index=-1, month="2026-09", files=1, first=900):
        """A copy of the register with more files released under one version."""
        changed = copy.deepcopy(self.versions)
        version = changed[base][index]
        template = version["released_files"][0]
        for offset in range(files):
            version["released_files"].append(
                {**template, "file": f"FILE{first + offset:07d}", "month": month}
            )
        version["releases"] = summarise_releases(version["released_files"], version["datasets"])
        version["files_released"] = sum(r["files"] for r in version["releases"])
        return changed

    def test_a_month_of_new_releases_is_not_a_new_state(self):
        facts.append_edition(REGISTER, "august2026", self.versions)
        counts = facts.append_edition(REGISTER, "september2026", self.released())
        self.assertEqual(counts["new_states"], 0)
        self.assertEqual(counts["new_released_files"], 1)
        self.assertEqual(counts["files_written"], 0)

    def test_an_edition_reports_the_releases_it_had_and_not_later_ones(self):
        facts.append_edition(REGISTER, "august2026", self.versions)
        facts.append_edition(REGISTER, "september2026", self.released(month="2026-09", files=4))
        was = facts.read_edition(REGISTER, "august2026")[FIRST][1]
        now = facts.read_edition(REGISTER, "september2026")[FIRST][1]
        self.assertEqual(was["files_released"], 2)
        self.assertEqual(now["files_released"], 6)
        self.assertNotIn("2026-09", was["releases"][0]["months"])
        self.assertEqual(now["releases"][0]["months"]["2026-09"], 4)
        self.assertEqual(now["releases"][0]["last_month"], "2026-09")

    def stored_file(self, base, file_reference):
        """One stored release row, as [file, month, opt-outs, first edition]."""
        return next(
            row
            for group in facts.read_releases(REGISTER, base)["releases"]
            for row in group["files"]
            if row[facts.FILE] == file_reference
        )

    def test_a_file_is_stored_once_and_keeps_the_edition_that_first_reported_it(self):
        facts.append_edition(REGISTER, "august2026", self.released(month="2026-08"))
        counts = facts.append_edition(REGISTER, "september2026", self.released(month="2026-08"))
        self.assertEqual(counts["new_released_files"], 0)
        self.assertEqual(counts["release_files_written"], 0)
        self.assertEqual(self.stored_file(FIRST, "FILE0000900")[facts.FIRST_EDITION], "august2026")

    def test_a_file_described_differently_later_keeps_both_descriptions(self):
        facts.append_edition(REGISTER, "august2026", self.released(month="2026-08"))
        counts = facts.append_edition(REGISTER, "september2026", self.released(month="2026-07"))
        self.assertEqual(counts["redescribed_files"], 1)
        self.assertEqual(counts["new_released_files"], 0)
        # Each edition reads back the month it reported, not the first one seen.
        def month_in(edition):
            files = facts.read_edition(REGISTER, edition)[FIRST][1]["released_files"]
            return next(f["month"] for f in files if f["file"] == "FILE0000900")
        self.assertEqual((month_in("august2026"), month_in("september2026")), ("2026-08", "2026-07"))

    def test_a_file_the_register_stops_reporting_is_dropped_from_then_on(self):
        facts.append_edition(REGISTER, "august2026", self.released(month="2026-08"))
        counts = facts.append_edition(REGISTER, "september2026", self.versions)
        self.assertEqual(counts["withdrawn_files"], 1)

        def files_in(edition):
            return {f["file"] for f in facts.read_edition(REGISTER, edition)[FIRST][1]["released_files"]}
        self.assertIn("FILE0000900", files_in("august2026"))
        self.assertNotIn("FILE0000900", files_in("september2026"))

    def test_a_withdrawn_file_that_comes_back_is_reported_again(self):
        facts.append_edition(REGISTER, "july2026", self.released(month="2026-07"))
        facts.append_edition(REGISTER, "august2026", self.versions)
        facts.append_edition(REGISTER, "september2026", self.released(month="2026-07"))

        def files_in(edition):
            return {f["file"] for f in facts.read_edition(REGISTER, edition)[FIRST][1]["released_files"]}
        self.assertEqual(
            ["FILE0000900" in files_in(e) for e in ("july2026", "august2026", "september2026")],
            [True, False, True],
        )

    def test_a_relabelled_dataset_follows_the_edition_that_reported_it(self):
        facts.append_edition(REGISTER, "august2026", self.versions)
        renamed = copy.deepcopy(self.versions)
        for released in renamed[FIRST][-1]["released_files"]:
            released["dataset"] = "Renamed Data Set"
        renamed[FIRST][-1]["releases"] = summarise_releases(
            renamed[FIRST][-1]["released_files"], renamed[FIRST][-1]["datasets"]
        )
        facts.append_edition(REGISTER, "september2026", renamed)
        def datasets_in(edition):
            files = facts.read_edition(REGISTER, edition)[FIRST][1]["released_files"]
            return {f["dataset"] for f in files}
        self.assertEqual(datasets_in("september2026"), {"Renamed Data Set"})
        self.assertNotIn("Renamed Data Set", datasets_in("august2026"))

    def test_recording_the_same_releases_again_writes_nothing(self):
        facts.append_edition(REGISTER, "september2026", self.versions)
        counts = facts.append_edition(REGISTER, "september2026", copy.deepcopy(self.versions))
        self.assertEqual(counts["new_released_files"], 0)
        self.assertEqual(counts["release_files_written"], 0)

    def test_an_agreement_with_no_releases_has_none_stored(self):
        bare = copy.deepcopy(self.versions)
        for version in bare[SECOND]:
            version["releases"], version["released_files"] = [], []
            version["files_released"] = 0
        facts.append_edition(REGISTER, "september2026", bare)
        self.assertFalse((facts.releases_dir(REGISTER) / "dars-nic-2-bbbbb.json").exists())
        read = facts.read_edition(REGISTER, "september2026")[SECOND][0]
        self.assertEqual((read["releases"], read["files_released"]), ([], 0))

    def test_files_disagreeing_about_opt_outs_are_reported_as_mixed(self):
        facts.append_edition(REGISTER, "september2026", self.versions)
        release = facts.read_edition(REGISTER, "september2026")[SECOND][0]["releases"][0]
        self.assertEqual(release["files"], 2)
        self.assertEqual(release["opt_outs_applied"], "Mixed")

    def test_a_file_whose_attributes_differ_from_its_dataset_is_flagged(self):
        facts.append_edition(REGISTER, "september2026", self.versions)
        releases = facts.read_edition(REGISTER, "september2026")[SECOND][0]["releases"]
        flagged = {r["dataset"]: r["attributes_differ"] for r in releases}
        self.assertTrue(flagged[NEW_NAME])
        # Only the file that disagreed is stored with attributes of its own.
        kept = [g["attributes"] for g in facts.read_releases(REGISTER, SECOND)["releases"] if "attributes" in g]
        self.assertEqual(len(kept), 1)
        self.assertEqual(next(iter(kept[0].values()))["sensitivity"], "Non-Sensitive")

    def test_every_release_records_the_channel_it_came_through(self):
        facts.append_edition(REGISTER, "september2026", self.versions)
        channels = {r["channel"] for r in facts.read_releases(REGISTER, FIRST)["releases"]}
        self.assertEqual(channels, {"file"})
        release = facts.read_edition(REGISTER, "september2026")[FIRST][0]["releases"][0]
        self.assertEqual(release["channel"], "file")

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
