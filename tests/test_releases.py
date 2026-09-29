import copy
import tempfile
import unittest
from pathlib import Path

from pipeline import aliases, build, releases
from pipeline.extract import extract

from .fixtures import FIRST_EDITION, NEW_NAME, dataset_aliases, site_meta, workbook_bytes

FIRST = "DARS-NIC-1-AAAAA"
SECOND = "DARS-NIC-2-BBBBB"


class Releases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with dataset_aliases():
            cls.data = extract(workbook_bytes())
            cls.alias_map = aliases.load_map(aliases.DATASET_ALIASES_PATH)
        cls.agreements = {a["base_reference"]: a for a in cls.data["agreements"]}

    def test_the_months_add_up_to_the_pages(self):
        releases.check(self.data["agreements"], self.data["datasets"], self.alias_map)

    def test_a_disagreement_stops_the_build(self):
        agreements = copy.deepcopy(self.data["agreements"])
        agreements[0]["files_released"] += 1
        with self.assertRaisesRegex(SystemExit, "disagree"):
            releases.check(agreements, self.data["datasets"], self.alias_map)

    def test_a_dataset_renamed_between_versions_is_one_strip(self):
        # Three files under the old name in 2020, two under the new in 2022.
        timeline = releases.agreement_timeline(self.agreements[FIRST], self.alias_map, "2026-09-01")
        [strip] = timeline["strips"]
        self.assertEqual(strip["dataset"], NEW_NAME)
        self.assertEqual((strip["files"], strip["months"]), (5, 5))
        self.assertEqual([m["month"] for m in strip["marks"]], ["2020-01", "2020-02", "2020-03", "2022-01", "2022-02"])
        self.assertEqual(dict(strip["by_year"]), {"2020": 3, "2022": 2})

    def test_the_axis_stops_at_the_last_month_the_edition_reports(self):
        # The second version's term runs to 2030.
        timeline = releases.agreement_timeline(self.agreements[FIRST], self.alias_map, "2026-09-01")
        self.assertEqual((timeline["start"], timeline["end"]), ("2020-01", "2026-08"))
        self.assertTrue(timeline["runs_on"])
        self.assertEqual([t["version"] for t in timeline["terms"]], ["1", "2"])

    def test_years_are_labelled_at_januaries_only(self):
        timeline = releases.agreement_timeline(self.agreements[FIRST], self.alias_map, "2026-09-01")
        labelled = [y["year"] for y in timeline["years"] if y["label"]]
        self.assertEqual(labelled, ["2020", "2021", "2022", "2023", "2024", "2025", "2026"])

    def test_an_agreement_with_no_files_has_no_timeline(self):
        quiet = copy.deepcopy(self.agreements[SECOND])
        for version in quiet["versions"]:
            version["releases"] = []
        self.assertIsNone(releases.agreement_timeline(quiet, self.alias_map, "2026-09-01"))

    def test_monthly_counts_files_and_the_agreements_receiving_them(self):
        by_month = releases.monthly(self.data["agreements"], self.alias_map)
        self.assertEqual(by_month["2022-06"], {"files": 2, "agreements": 1})
        self.assertEqual(sum(r["files"] for r in by_month.values()), 7)

    def test_monthly_for_one_dataset(self):
        slug = next(d["slug"] for d in self.data["datasets"] if d["name"] == NEW_NAME)
        by_month = releases.monthly(self.data["agreements"], self.alias_map, slug)
        self.assertEqual(sum(r["files"] for r in by_month.values()), 7)
        self.assertEqual(releases.monthly(self.data["agreements"], self.alias_map, "other-data-set"), {})


class Chart(unittest.TestCase):
    def test_the_axis_top_is_a_clean_number_in_three_or_four_steps(self):
        self.assertEqual(releases._nice_top(745), (800, 200))
        self.assertEqual(releases._nice_top(2805), (3000, 1000))
        self.assertEqual(releases._nice_top(3), (3, 1))
        self.assertEqual(releases._nice_top(0), (1, 1))

    def test_only_months_with_a_value_get_a_column(self):
        chart = releases.chart({"2019-03": {"files": 4, "agreements": 1}}, "files", "2019-12", start="2019-01")
        [column] = chart["columns"]
        self.assertEqual((column["month"], column["value"], column["height"]), ("2019-03", 4, 100))
        self.assertAlmostEqual(column["left"], 2 / 12 * 100)
        self.assertEqual(chart["peak"], {"month": "2019-03", "value": 4})
        self.assertEqual(chart["latest"], {"month": "2019-12", "value": 0})

    def test_months_before_the_chart_starts_are_left_out(self):
        chart = releases.chart({"2019-06": {"files": 9, "agreements": 1}}, "files", "2020-12")
        self.assertEqual(chart["columns"], [])
        self.assertEqual(releases.CHART_START, "2020-01")

    def test_an_edition_ending_before_the_chart_starts_draws_nothing(self):
        chart = releases.chart({"2019-06": {"files": 9, "agreements": 1}}, "files", "2019-12")
        self.assertEqual((chart["columns"], chart["peak"]), ([], None))

    def test_an_edition_reports_up_to_the_month_before_it(self):
        self.assertEqual(releases.last_month("2026-09-01"), "2026-08")
        self.assertEqual(releases.last_month("2026-01-01"), "2025-12")


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        with dataset_aliases():
            build.build(extract(workbook_bytes()), site_meta(), FIRST_EDITION, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def read(self, path):
        return (self.out / path / "index.html").read_text()

    def test_the_releases_page_charts_both_measures_and_says_what_they_count(self):
        page = self.read("releases")
        self.assertIn("Agreements receiving files each month", page)
        self.assertIn("Files released each month", page)
        self.assertIn("files released externally by DARS", page)
        self.assertIn('title="June 2022: 2 files"', page)

    def test_an_agreement_page_has_its_timeline_and_table(self):
        page = self.read("agreements/dars-nic-1-aaaaa")
        self.assertIn("Months with files released, by dataset", page)
        self.assertIn('title="January 2020: 1 file"', page)
        self.assertIn("Files by dataset and year, as a table", page)

    def test_a_dataset_page_charts_its_files(self):
        page = self.read("datasets/msds-maternity-services-data-set-v1-5")
        self.assertIn("Files of this dataset released each month", page)

    def test_the_home_page_and_about_link_to_it(self):
        self.assertIn('href="/releases/"', self.read(""))
        self.assertIn('href="/releases/"', self.read("about"))

    def test_it_is_in_the_main_menu_and_marked_there_as_the_current_page(self):
        def menu(page):
            return page[page.index('<nav aria-label="Main">'):page.index("</nav>")]
        self.assertIn('href="/releases/">Files released</a>', menu(self.read("datasets")))
        self.assertIn('href="/releases/" aria-current="page">Files released</a>', menu(self.read("releases")))


if __name__ == "__main__":
    unittest.main()
