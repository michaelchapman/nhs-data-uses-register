import tempfile
import unittest
from pathlib import Path

from pipeline import build, linkcheck
from pipeline.extract import extract

from .fixtures import FIRST_EDITION, OLD_NAME, dataset_aliases, site_meta, workbook_bytes


def build_site(out: Path, base_path: str = "") -> None:
    with dataset_aliases():
        data = extract(workbook_bytes())
        build.build(data, site_meta(base_path), FIRST_EDITION, out)


class BuiltSite(unittest.TestCase):
    def test_no_broken_internal_links(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out)
            broken, pages = linkcheck.check(out)
        self.assertGreater(pages, 5)
        self.assertEqual(dict(broken), {})

    def test_no_broken_links_under_a_base_path(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out, "/repo")
            broken, _ = linkcheck.check(out, "/repo")
        self.assertEqual(dict(broken), {})

    def test_renamed_dataset_links_to_the_canonical_page(self):
        # The agreement lists the old spelling; its link must still resolve.
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out)
            page = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
        self.assertIn(OLD_NAME, page)
        self.assertNotIn("/datasets/maternity-services-data-set-v1-5/", page)


class LinkCheck(unittest.TestCase):
    def write(self, out: Path, name: str, html: str) -> None:
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_text(html)

    def test_reports_missing_page_and_missing_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.write(out, "index.html", '<a href="/gone/">x</a><a href="/other/#nope">y</a><a href="/other/#here">z</a>')
            self.write(out, "other/index.html", '<h2 id="here">h</h2>')
            broken, _ = linkcheck.check(out)
        self.assertEqual(set(broken), {"/gone/", "/other/#nope"})

    def test_link_outside_the_base_path_is_broken(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.write(out, "index.html", '<a href="/repo/a/">ok</a><a href="/a/">bad</a>')
            self.write(out, "a/index.html", "")
            broken, _ = linkcheck.check(out, "/repo")
        self.assertEqual(set(broken), {"/a/"})

    def test_external_links_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.write(out, "index.html", '<a href="https://example.com/x">x</a><a href="mailto:a@b.c">m</a>')
            broken, _ = linkcheck.check(out)
        self.assertEqual(dict(broken), {})


if __name__ == "__main__":
    unittest.main()


class PrepareOutput(unittest.TestCase):
    def test_an_empty_or_missing_directory_is_fine(self):
        with tempfile.TemporaryDirectory() as directory:
            build.prepare_output(Path(directory) / "new")
            build.prepare_output(Path(directory) / "new")  # now a previous build

    def test_a_previous_build_is_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out)
            (out / "stale.html").write_text("old")
            build.prepare_output(out)
            self.assertEqual([p.name for p in out.iterdir()], [build.BUILD_MARKER])

    def test_a_build_made_before_the_marker_existed_is_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / ".nojekyll").write_text("")
            (out / "meta.json").write_text("{}")
            build.prepare_output(out)

    def test_a_directory_with_other_files_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "thesis.docx").write_text("precious")
            with self.assertRaises(SystemExit):
                build.prepare_output(out)
            self.assertTrue((out / "thesis.docx").exists())

    def test_the_repository_is_refused(self):
        with self.assertRaises(SystemExit):
            build.prepare_output(build.ROOT)
        with self.assertRaises(SystemExit):
            build.prepare_output(build.ROOT / "pipeline")  # not a build either


class InTerm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with dataset_aliases():
            cls.data = extract(workbook_bytes())

    def test_active_agreements_depend_on_the_edition_date_not_the_build_date(self):
        # Both fixture agreements run to 2030 or later.
        self.assertEqual(build.compute_stats(self.data, "2026-09-01")["active_agreements"], 2)
        self.assertEqual(build.compute_stats(self.data, "2030-06-01")["active_agreements"], 1)
        self.assertEqual(build.compute_stats(self.data, "2035-01-01")["active_agreements"], 0)

    def test_the_agreements_table_flags_terms_as_of_the_edition(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            meta = {**site_meta(), "as_of": "2030-06-01"}
            build.build(self.data, meta, FIRST_EDITION, out)
            page = (out / "agreements" / "index.html").read_text()
        self.assertEqual(page.count('data-active="yes"'), 1)
        self.assertEqual(page.count('data-active="no"'), 1)
        self.assertIn("In term in September 2026", page)


class DatasetPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        build_site(cls.out)
        cls.page = (cls.out / "datasets" / "msds-maternity-services-data-set-v1-5" / "index.html").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_shows_what_the_register_records_about_the_dataset(self):
        self.assertIn("How the register describes it", self.page)
        for value in ("Identifiable", "Sensitive", "One-off", "Consent"):
            self.assertIn(f"<li>{value}</li>", self.page)

    def test_lists_the_receiving_organisations_with_agreement_counts(self):
        self.assertIn("Organisations receiving it (2)", self.page)
        self.assertRegex(self.page, r'organisations/university-of-example/">University of Example</a> \(1\)')


class ChangesPages(unittest.TestCase):
    def test_the_current_edition_has_one_changes_page_not_two(self):
        history = [
            {**FIRST_EDITION, "edition": "august2026"},
            {**FIRST_EDITION, "edition": "september2026"},
        ]
        meta = {**site_meta(), "editions": [
            {"edition": "july2026", "retrieved": "2026-07-20", "counts": {"agreement_versions": 1}},
            {"edition": "august2026", "retrieved": "2026-08-20", "counts": {"agreement_versions": 2}},
            {"edition": "september2026", "retrieved": "2026-09-20", "counts": {"agreement_versions": 3}},
        ]}
        with dataset_aliases(), tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build.build(extract(workbook_bytes()), meta, FIRST_EDITION, out, changes_history=history)
            self.assertTrue((out / "changes" / "august2026" / "index.html").exists())
            self.assertFalse((out / "changes" / "september2026").exists())
            latest = (out / "changes" / "index.html").read_text()
            older = (out / "changes" / "august2026" / "index.html").read_text()
            broken, _ = linkcheck.check(out)
        self.assertEqual(dict(broken), {})
        # Both pages mark September as current, whichever edition they describe.
        for page in (latest, older):
            self.assertRegex(page, r'<a href="/changes/">September 2026</a> <span class="tag tag-new">Current</span>')
        self.assertIn('<a href="/changes/august2026/">August 2026</a>', older)


class Csvs(unittest.TestCase):
    def test_agreement_urls_are_absolute(self):
        import csv
        with dataset_aliases(), tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build.build(extract(workbook_bytes()), site_meta("/repo"), FIRST_EDITION, out)
            with (out / "downloads" / "agreements.csv").open(newline="", encoding="utf-8") as handle:
                urls = [row["url"] for row in csv.DictReader(handle)]
        self.assertTrue(urls)
        self.assertTrue(all(u.startswith("https://example.test/repo/agreements/") for u in urls), urls)


class EditionGap(unittest.TestCase):
    def build(self, out: Path, changes: dict, missing: list[str]) -> None:
        meta = {**site_meta(), "missing_editions": missing}
        with dataset_aliases():
            build.build(extract(workbook_bytes()), meta, changes, out)

    def test_a_comparison_across_a_gap_is_labelled_as_spanning_two_months(self):
        changes = {**FIRST_EDITION, "comparable": True, "reason": "", "previous_edition": "december2024",
                   "skipped": ["january2025"]}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.build(out, changes, ["january2025"])
            page = (out / "changes" / "index.html").read_text()
        self.assertIn("This covers 2 months, not one.", page)
        self.assertIn("January 2025 is not held here", page)
        self.assertIn("Not held: January 2025.", page)

    def test_a_month_on_month_comparison_says_nothing_about_gaps(self):
        changes = {**FIRST_EDITION, "comparable": True, "reason": "", "previous_edition": "august2026",
                   "skipped": []}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.build(out, changes, [])
            page = (out / "changes" / "index.html").read_text()
        self.assertNotIn("not one", page)
        self.assertNotIn("Not held", page)


class OrganisationNames(unittest.TestCase):
    def test_a_name_the_register_wrote_in_capitals_is_shown_in_ordinary_case(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out)
            page = (out / "organisations" / "university-of-example" / "index.html").read_text()
            listing = (out / "organisations" / "index.html").read_text()
            agreement = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
            csv_text = (out / "downloads" / "agreements.csv").read_text()
        self.assertIn("<h1>University of Example</h1>", page)
        self.assertIn("The register writes this name in capitals: UNIVERSITY OF EXAMPLE.", page)
        self.assertIn(">University of Example</a>", listing)
        self.assertIn(">Other Trust</a>", agreement)  # a joint controller, listed on the agreement
        # What is stored, searched and exported stays as the register wrote it.
        self.assertIn("UNIVERSITY OF EXAMPLE", csv_text)
        self.assertIn('data-search="', listing)

    def test_a_name_already_in_mixed_case_gets_no_note(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out)
            slug = "nhs-bristol-north-somerset-and-south-gloucestershire-icb-15c"
            page = (out / "organisations" / slug / "index.html").read_text()
        self.assertNotIn("writes this name in capitals", page)
