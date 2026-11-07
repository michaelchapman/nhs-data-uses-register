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
            holder([SUB_LICENSEES], agreements=("E",), commissioning=True),
            holder([], agreements=("F", "G"), commissioning=True),
        ]}
        self.assertEqual(onward.counts(config), {
            "holders": 3, "agreements": 4, "sub_licensees": 1, "approved_uses": 2, "publications": 0, "none": 1,
            "icbs": 2, "icb_agreements": 3, "icbs_found": 1, "icbs_none": 1,
        })


class Site(unittest.TestCase):
    def build(self, out, config):
        with dataset_aliases():
            data = extract(workbook_bytes())
            example = next(a for a in data["agreements"] if a["slug"] == "dars-nic-1-aaaaa")
            example["sublicensing"] = example["latest"]["sublicensing"] = "Yes"
            build.build(data, site_meta(), FIRST_EDITION, out, onward_config=config)

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
        self.assertIn("not opened by this site because the holder's site refuses automated checks", page)
        self.assertIn("Projects and papers under this agreement", page)
        self.assertIn("Not every project or paper on them used NHS England data.", page)
        self.assertIn("30 September 2026", page)
        self.assertNotIn('id="onward"', other)
        self.assertIn('id="onward"', organisation)
        self.assertIn('<a href="/agreements/dars-nic-1-aaaaa/">DARS-NIC-1-AAAAA</a>', organisation)
        self.assertIn('id="onward"', about)
        self.assertEqual(dict(broken), {})

    def test_a_list_of_nhs_england_data_only_needs_no_caveat(self):
        only = {**SUB_LICENSEES, "nhs_england_only": True}
        papers = {"kind": "publications", "title": "Our papers", "url": "https://example.test/papers",
                  "format": "web page", "checked": "2026-11-07"}
        self.assertFalse(onward.caveat(holder([only])))
        self.assertTrue(onward.caveat(holder([only, papers])))
        config = {"checked": "2026-11-07", "holders": [holder([only, papers])]}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.build(out, config)
            page = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
        self.assertIn("Papers the holder lists:", page)
        self.assertIn("NHS England data only", page)
        self.assertIn('Lists not marked "NHS England data only" cover', page)
        self.assertIn('href="#onward"', page)

    def test_a_holder_with_no_register_says_so(self):
        config = {"checked": "2026-09-30", "holders": [holder([], note="Access is decided by a committee.")]}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.build(out, config)
            page = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
        self.assertIn("This site couldn't find a public list of projects or papers under this agreement when it checked", page)
        self.assertIn("Access is decided by a committee.", page)

    def test_an_icb_speaks_of_organisations_not_projects_and_papers(self):
        found = {**SUB_LICENSEES, "nhs_england_only": True}
        for registers in ([found], []):
            config = {"checked": "2026-11-07", "holders": [holder(registers, commissioning=True)]}
            with tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                self.build(out, config)
                page = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
                organisation = (out / "organisations" / "university-of-example" / "index.html").read_text()
                about = (out / "about" / "index.html").read_text()
                broken, _ = linkcheck.check(out)
            self.assertIn('<h2 id="onward">Organisations the data is passed on to</h2>', page)
            self.assertIn("for commissioning", page)
            self.assertNotIn("Projects and papers", page)
            self.assertNotIn("Not every project or paper", page)
            self.assertIn("Organisations its data is passed on to", organisation)
            self.assertIn('id="onward-icbs"', about)
            self.assertEqual(dict(broken), {})
            if registers:
                self.assertIn('<a href="https://example.test/sub">Who we pass data to</a>', page)
            else:
                self.assertIn("This site couldn't find a published list of the organisations Example Cohort passes this data to", page)


if __name__ == "__main__":
    unittest.main()
