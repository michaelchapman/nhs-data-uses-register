import tempfile
import unittest
from pathlib import Path

from pipeline import build, linkcheck, onward
from pipeline.extract import extract

from .fixtures import FIRST_EDITION, dataset_aliases, site_meta, workbook_bytes


def holder(registers, agreements=("DARS-NIC-1-AAAAA",), organisation="university-of-example", **extra):
    return {
        "holder": "Example Cohort", "organisation": organisation, "agreements": list(agreements),
        "registers": registers, **extra,
    }


SUB_LICENSEES = {
    "kind": "sub-licensees", "title": "Who we pass data to", "url": "https://example.test/sub",
    "format": "PDF", "checked": "2026-09-30", "note": "Every organisation sublicensed.",
}
APPROVED = {
    "kind": "approved uses", "title": "Approved projects", "url": "https://example.test/projects",
    "format": "web page", "checked": "2026-09-30", "opened": False,
}


def agreement(reference, sublicensing="Yes", organisation_type="Academic"):
    return {
        "base_reference": reference, "sublicensing": sublicensing, "organisation_type": organisation_type,
        "organisation": "Somewhere", "title": "A study",
    }


class Checks(unittest.TestCase):
    def test_a_sound_file_has_no_problems(self):
        config = {"holders": [holder([SUB_LICENSEES])]}
        self.assertEqual(onward.problems(config, [agreement("DARS-NIC-1-AAAAA")], {"university-of-example"}), [])

    def test_reports_what_the_edition_does_not_bear_out(self):
        config = {"holders": [
            holder([{**APPROVED, "kind": "anything"}], agreements=("DARS-NIC-1-AAAAA", "DARS-NIC-9-ZZZZZ"),
                   organisation="nowhere"),
            holder([], agreements=("dars-nic-1-aaaaa", "DARS-NIC-3-CCCCC")),
        ]}
        agreements = [agreement("DARS-NIC-1-AAAAA"), agreement("DARS-NIC-3-CCCCC", sublicensing="No")]
        found = onward.problems(config, agreements, {"university-of-example"})
        self.assertEqual(found, [
            "Example Cohort: unknown kind 'anything'",
            "Example Cohort: no organisation page nowhere",
            "Example Cohort: DARS-NIC-9-ZZZZZ is not in this edition",
            "Example Cohort: dars-nic-1-aaaaa is named more than once",
            "Example Cohort: DARS-NIC-3-CCCCC no longer permits sublicensing",
        ])

    def test_a_sublicensing_agreement_with_no_entry_is_listed_unless_an_icb_holds_it(self):
        agreements = [
            agreement("DARS-NIC-4-DDDDD"),
            agreement("DARS-NIC-5-EEEEE", organisation_type="ICB - Integrated Care Board"),
            agreement("DARS-NIC-6-FFFFF", organisation_type="Sub ICB Location"),
            agreement("DARS-NIC-7-GGGGG", sublicensing="No"),
        ]
        found = onward.problems({"holders": []}, agreements, set())
        self.assertEqual(found, ["no entry: DARS-NIC-4-DDDDD (Somewhere, A study)"])

    def test_counts_holders_by_the_records_they_keep(self):
        config = {"holders": [
            holder([SUB_LICENSEES, APPROVED], agreements=("A", "B")),
            holder([APPROVED], agreements=("C",)),
            holder([], agreements=("D",)),
        ]}
        self.assertEqual(onward.counts(config), {
            "holders": 3, "agreements": 4, "sub_licensees": 1, "approved_uses": 2, "none": 1,
        })


class Site(unittest.TestCase):
    def build(self, out, config):
        with dataset_aliases():
            data = extract(workbook_bytes())
            example = next(a for a in data["agreements"] if a["slug"] == "dars-nic-1-aaaaa")
            example["sublicensing"] = example["latest"]["sublicensing"] = "Yes"
            empty = {"source_url": "", "retrieved": "", "projects": []}
            build.build(data, site_meta(), FIRST_EDITION, out, opensafely_store=empty, onward_config=config)

    def test_registers_show_on_the_agreement_and_the_holder(self):
        config = {"checked": "2026-09-30", "holders": [holder([SUB_LICENSEES, APPROVED])]}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.build(out, config)
            page = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
            organisation = (out / "organisations" / "university-of-example" / "index.html").read_text()
            other = (out / "agreements" / "dars-nic-2-bbbbb" / "index.html").read_text()
            about = (out / "about" / "index.html").read_text()
            broken, _ = linkcheck.check(out)
        self.assertIn('id="onward"', page)
        self.assertIn("Organisations the data is passed on to:", page)
        self.assertIn('<a href="https://example.test/sub">Who we pass data to</a>', page)
        self.assertIn("Every organisation sublicensed.", page)
        self.assertIn("found by search, and not opened by this site", page)
        self.assertIn("30 September 2026", page)
        self.assertNotIn('id="onward"', other)
        self.assertIn('id="onward"', organisation)
        self.assertIn('<a href="/agreements/dars-nic-1-aaaaa/">DARS-NIC-1-AAAAA</a>', organisation)
        self.assertIn('id="onward"', about)
        self.assertEqual(dict(broken), {})

    def test_a_holder_with_no_register_says_so(self):
        config = {"checked": "2026-09-30", "holders": [holder([], note="Access is decided by a committee.")]}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.build(out, config)
            page = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
        self.assertIn("No record of what happens to the data next was found when this site checked", page)
        self.assertIn("Access is decided by a committee.", page)


if __name__ == "__main__":
    unittest.main()
