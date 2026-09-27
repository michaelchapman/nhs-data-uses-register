import csv
import tempfile
import unittest
from pathlib import Path

from pipeline import build, sectors
from pipeline.extract import extract

from .fixtures import FIRST_EDITION, dataset_aliases, site_meta, workbook_bytes

CONFIG = {
    "sectors": [
        {"name": "NHS", "types": ["ICB - Integrated Care Board", "Sub ICB Location"]},
        {"name": "Universities", "types": ["Academic"]},
        {"name": "Companies", "types": ["Commercial"]},
    ],
    "corrections": [
        {"organisation": "evidera-ltd", "name": "EVIDERA LTD", "sector": "Companies", "reason": "A company."},
    ],
}


def organisation(slug, *types, type_=None):
    agreements = [{"organisation_type": t} for t in types]
    return {"slug": slug, "type": type_ if type_ is not None else (types[0] if types else ""), "agreements": agreements}


class Assign(unittest.TestCase):
    def test_a_type_maps_to_its_sector_and_the_agreements_follow(self):
        org = organisation("university-of-example", "Academic", "Academic")
        self.assertEqual(sectors.assign([org], CONFIG), [])
        self.assertEqual(org["sector"], "Universities")
        self.assertEqual([a["sector"] for a in org["agreements"]], ["Universities", "Universities"])
        self.assertNotIn("sector_reason", org)

    def test_a_correction_wins_over_the_type_and_says_why(self):
        org = organisation("evidera-ltd", "Research")
        self.assertEqual(sectors.assign([org], CONFIG), [])  # a corrected type is not unmapped
        self.assertEqual(org["sector"], "Companies")
        self.assertEqual(org["sector_reason"], "A company.")

    def test_an_organisation_under_two_types_takes_the_commoner(self):
        org = organisation("mixed", "Commercial", "Academic", "Academic")
        sectors.assign([org], CONFIG)
        self.assertEqual(org["sector"], "Universities")
        self.assertEqual({a["sector"] for a in org["agreements"]}, {"Universities"})

    def test_a_tie_goes_to_the_sector_listed_first(self):
        org = organisation("icb", "Academic", "ICB - Integrated Care Board")
        sectors.assign([org], CONFIG)
        self.assertEqual(org["sector"], "NHS")

    def test_a_new_type_is_other_and_is_reported(self):
        org = organisation("new", "Space Agency")
        warnings = sectors.assign([org], CONFIG)
        self.assertEqual(org["sector"], sectors.OTHER)
        self.assertEqual(len(warnings), 1)
        self.assertIn('"Space Agency"', warnings[0])

    def test_no_type_is_not_stated(self):
        org = organisation("controller-only", type_="")
        self.assertEqual(sectors.assign([org], CONFIG), [])
        self.assertEqual(org["sector"], sectors.NOT_STATED)

    def test_a_correction_for_no_organisation_is_reported(self):
        self.assertEqual(len(sectors.unused_corrections([organisation("other", "Academic")], CONFIG)), 1)
        self.assertEqual(sectors.unused_corrections([organisation("evidera-ltd", "Research")], CONFIG), [])


class SectorsFile(unittest.TestCase):
    def test_every_correction_names_a_listed_sector_and_gives_a_reason(self):
        config = sectors.load()
        listed = set(sectors.names(config))
        for correction in config["corrections"]:
            with self.subTest(organisation=correction["organisation"]):
                self.assertIn(correction["sector"], listed)
                self.assertTrue(correction["reason"].strip())

    def test_no_type_is_in_two_sectors(self):
        types = [t for sector in sectors.load()["sectors"] for t in sector["types"]]
        self.assertEqual(len(types), len(set(types)))


class BuiltSite(unittest.TestCase):
    def test_the_lists_filter_by_sector_and_the_csv_has_it(self):
        with tempfile.TemporaryDirectory() as directory, dataset_aliases():
            out = Path(directory)
            data = extract(workbook_bytes())
            build.build(data, site_meta(), FIRST_EDITION, out)
            agreements = (out / "agreements" / "index.html").read_text()
            organisations = (out / "organisations" / "index.html").read_text()
            organisation = (out / "organisations" / "university-of-example" / "index.html").read_text()
            with (out / "downloads" / "agreements.csv").open(encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))

        for page in (agreements, organisations):
            self.assertIn('<select id="sector" data-filter-select data-key="sector"', page)
        self.assertRegex(agreements, r'<tr data-i="\d+" data-sector="Universities"')
        # Both fixture agreements are filed as Academic, the ICB one included.
        self.assertIn('<option value="Universities">Universities (2)</option>', agreements)
        self.assertIn("<dt>Sector</dt><dd>Universities</dd>", organisation)
        self.assertNotIn("Sector set by hand", organisation)
        self.assertEqual(list(rows[0])[-1], "sector")
        self.assertEqual({r["sector"] for r in rows if r["organisation"] == "UNIVERSITY OF EXAMPLE"}, {"Universities"})
