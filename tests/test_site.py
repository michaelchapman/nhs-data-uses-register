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

    def test_pages_name_their_own_address_and_section(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out, "/repo")
            index = (out / "agreements" / "index.html").read_text()
            agreement = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
            not_found = (out / "404.html").read_text()
        self.assertIn('<link rel="canonical" href="https://example.test/repo/agreements/">', index)
        self.assertIn('<link rel="canonical" href="https://example.test/repo/agreements/dars-nic-1-aaaaa/">', agreement)
        self.assertIn('<meta property="og:title"', agreement)
        self.assertIn('href="/repo/agreements/" aria-current="page"', index)
        self.assertIn('href="/repo/agreements/" aria-current="true"', agreement)
        self.assertNotIn('rel="canonical"', not_found)
        self.assertNotIn("aria-current", not_found)

    def test_released_datasets_link_to_their_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out)
            page = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
        releases = page[page.index('id="releases"'):page.index('id="history"')]
        self.assertIn('href="/datasets/', releases)
        self.assertIn('<nav aria-label="On this page"', page)

    def test_agreements_list_opens_newest_first(self):
        with dataset_aliases(), tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            data = extract(workbook_bytes())
            # The register's order is by organisation name, which puts Ambulance
            # study (NHS Bristol...) first; a later start puts Maternity study first.
            for agreement in data["agreements"]:
                if agreement["title"] == "Maternity study":
                    agreement["latest_start"] = "2025-01-01"
            build.build(data, site_meta(), FIRST_EDITION, out)
            page = (out / "agreements" / "index.html").read_text()
        table = page[page.index('id="agreements-table"'):]
        self.assertLess(table.index("Maternity study"), table.index("Ambulance study"))

    def test_pages_offer_a_citation_of_the_register_read_here(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out, "/repo")
            agreement = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
            organisation = (out / "organisations" / "university-of-example" / "index.html").read_text()
            dataset = (out / "datasets" / "msds-maternity-services-data-set-v1-5" / "index.html").read_text()
        self.assertIn(
            "NHS England (2026) <cite>Data Uses Register</cite>, September 2026 edition, agreement "
            "DARS-NIC-1-AAAAA, “Maternity study”. Read via Test site (unofficial), "
            "https://example.test/repo/agreements/dars-nic-1-aaaaa/ (accessed <span data-cite-date>[date]</span>).",
            agreement,
        )
        self.assertIn("September 2026 edition, agreements naming University of Example. Read via", organisation)
        self.assertIn("September 2026 edition, agreements naming MSDS (Maternity Services Data Set) v1.5. Read via", dataset)
        for page in (agreement, organisation, dataset):
            self.assertIn('<script src="/repo/assets/cite.js" defer></script>', page)

    def test_every_page_but_the_agreements_list_searches_all_agreements(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out, "/repo")
            home = (out / "index.html").read_text()
            agreement = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
            listing = (out / "agreements" / "index.html").read_text()
        for page in (home, agreement):
            header = page[page.index('<header class="site-header">'):page.index("</header>")]
            self.assertIn('<form class="site-search" action="/repo/agreements/" method="get"', header)
            self.assertIn('<input type="hidden" name="active" value="all">', header)
        self.assertIn('<form class="home-search" action="/repo/agreements/"', home)
        self.assertNotIn('class="site-search"', listing)

    def test_an_organisation_named_only_as_a_controller_says_so(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out)
            page = (out / "organisations" / "other-trust" / "index.html").read_text()
        self.assertIn("Named in the register only as a data controller", page)
        self.assertIn("<h2>Named as a data controller</h2>", page)
        # No empty table of its own agreements, and an end date from those naming it.
        self.assertNotIn('id="organisation-agreements"', page)
        self.assertNotIn("Organisation type not stated", page)
        self.assertRegex(page, r"<dt>Latest end date</dt><dd>\d+ \w+ \d{4}</dd>")


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
        # On by default, but ticked by the script: with JavaScript off every row
        # shows, so the markup must not claim the filter is applied.
        self.assertRegex(page, r'<input type="checkbox" data-filter-flag data-key="active" value="yes" data-default="on">')
        self.assertNotRegex(page, r'data-key="active"[^>]*checked')

    def test_status_is_shown_on_every_page_that_lists_or_describes_an_agreement(self):
        # As of June 2030, DARS-NIC-1 (to January 2030) has ended and DARS-NIC-2 has not.
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            meta = {**site_meta(), "as_of": "2030-06-01"}
            build.build(self.data, meta, FIRST_EDITION, out)

            def read(*parts):
                return (out.joinpath(*parts) / "index.html").read_text()

            listing = read("agreements")
            self.assertEqual(listing.count('<span class="tag tag-in-term">In term</span>'), 1)
            self.assertEqual(listing.count('<span class="tag tag-expired">Expired</span>'), 1)
            self.assertIn("1 are in term in September 2026", listing)

            expired = read("agreements", "dars-nic-1-aaaaa")
            self.assertIn('<span class="tag tag-expired">Expired</span>', expired)
            self.assertIn("<dt>Latest version</dt>", expired)
            self.assertNotIn("Current version", expired)
            current = read("agreements", "dars-nic-2-bbbbb")
            self.assertIn('<span class="tag tag-in-term">In term</span>', current)
            self.assertIn("<dt>Current version</dt>", current)

            self.assertRegex(read("organisations", "university-of-example"),
                             r"<dt>In term in September 2026</dt><dd>0</dd>")
            dataset = read("datasets", "msds-maternity-services-data-set-v1-5")
            self.assertRegex(dataset, r"<dt>In term in September 2026</dt><dd>1</dd>")
            self.assertEqual(dataset.count("tag-expired"), 1)
            self.assertIn("data sharing agreements in term, of 2 listed", read())


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

    def test_lists_the_organisations_naming_it_with_agreement_counts(self):
        self.assertIn("Organisations whose agreements name it (2)", self.page)
        self.assertRegex(self.page, r'organisations/university-of-example/">University of Example</a> \(1\)')
        self.assertIn("With an agreement in term in September 2026 (2)", self.page)
        self.assertNotIn("With expired agreements only", self.page)

    def test_agreements_can_be_filtered_and_show_this_datasets_files(self):
        self.assertIn('data-key="active"', self.page)
        self.assertIn('data-active="yes"', self.page)
        self.assertIn('<th scope="col" class="num">Files</th>', self.page)
        table = self.page[self.page.index('id="dataset-agreements"'):]
        self.assertIn('<td class="num">5</td>', table)


class ChangesPages(unittest.TestCase):
    def test_the_current_edition_has_one_changes_page_not_two(self):
        history = [
            {**FIRST_EDITION, "edition": "august2026"},
            {**FIRST_EDITION, "edition": "september2026"},
        ]
        meta = {**site_meta(), "editions": [
            {"edition": "july2026", "retrieved": "2026-07-20", "counts": {"agreement_versions": 1}},
            {"edition": "august2026", "retrieved": "2026-08-20", "counts": {"agreement_versions": 2},
             "source_file": "datausesregister_august2026.xlsx", "source_url": "https://example.test/august.xlsx"},
            {"edition": "september2026", "retrieved": "2026-09-20", "counts": {"agreement_versions": 3}},
        ]}
        with dataset_aliases(), tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build.build(extract(workbook_bytes()), meta, FIRST_EDITION, out, changes_history=history)
            self.assertTrue((out / "changes" / "august2026" / "index.html").exists())
            self.assertFalse((out / "changes" / "september2026").exists())
            latest = (out / "changes" / "index.html").read_text()
            older = (out / "changes" / "august2026" / "index.html").read_text()
            sitemap = (out / "sitemap.xml").read_text()
            broken, _ = linkcheck.check(out)
        self.assertEqual(dict(broken), {})
        # Both pages mark September as current, whichever edition they describe.
        for page in (latest, older):
            self.assertRegex(page, r'<a href="/changes/">September 2026</a> <span class="tag tag-new">Current</span>')
        self.assertIn('<a href="/changes/august2026/">August 2026</a>', older)
        # Each page links to the editions either side; July, the first held, has no page.
        self.assertIn('Previous: <a href="/changes/august2026/">August 2026</a>', latest)
        self.assertNotIn("Next:", latest)
        self.assertIn('Next: <a href="/changes/">September 2026</a>', older)
        self.assertNotIn("Previous:", older)
        # Each page's footer cites the workbook it describes.
        self.assertIn('retrieved 20 August 2026 from <a href="https://example.test/august.xlsx">datausesregister_august2026.xlsx</a>', older)
        self.assertNotIn("source.xlsx", older)
        self.assertIn("source.xlsx", latest)
        # The older edition's page is in the sitemap; the current one is /changes/.
        self.assertIn("<loc>https://example.test/changes/august2026/</loc>", sitemap)
        self.assertNotIn("/changes/september2026/", sitemap)

    def test_changes_link_their_organisations_and_can_be_searched(self):
        changes = {**FIRST_EDITION, "comparable": True, "reason": "", "previous_edition": "august2026",
                   "skipped": [], "added": [{"base": "DARS-NIC-1-AAAAA", "reference": "DARS-NIC-1-AAAAA-v1",
                                             "title": "Maternity study", "org": "UNIVERSITY OF EXAMPLE",
                                             "kind": "new"}]}
        with dataset_aliases(), tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build.build(extract(workbook_bytes()), site_meta(), changes, out)
            page = (out / "changes" / "index.html").read_text()
        self.assertIn('<a href="/organisations/university-of-example/">University of Example</a>', page)
        self.assertIn('data-target="added-table amended-table removed-table"', page)
        self.assertIn("Showing all 1 changes.", page)


class Downloads(unittest.TestCase):
    def test_the_page_points_to_the_register_and_the_archive_and_is_not_in_the_menu(self):
        with dataset_aliases(), tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build.build(extract(workbook_bytes()), site_meta(), FIRST_EDITION, out)
            page = (out / "downloads" / "index.html").read_text()
            home = (out / "index.html").read_text()
            files = sorted(path.name for path in (out / "downloads").iterdir())
        self.assertEqual(files, ["index.html"])  # no data files
        self.assertIn("<h1>Get the data</h1>", page)
        self.assertIn('href="https://example.test/source.xlsx"', page)
        self.assertIn('href="https://example.test/repo/tree/main/data/facts"', page)
        nav = home[home.index('<nav aria-label="Main">'):home.index("</nav>")]
        self.assertNotIn("/downloads/", nav)
        self.assertIn('href="/downloads/">Get the data</a>', home)


class Robots(unittest.TestCase):
    def test_the_sitemap_is_named_under_the_base_path(self):
        with dataset_aliases(), tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build.build(extract(workbook_bytes()), site_meta("/repo"), FIRST_EDITION, out)
            robots = (out / "robots.txt").read_text()
        self.assertIn("Sitemap: https://example.test/repo/sitemap.xml\n", robots)


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
        self.assertIn("<h1>University of Example</h1>", page)
        self.assertIn("The register writes this name in capitals: UNIVERSITY OF EXAMPLE.", page)
        self.assertIn(">University of Example</a>", listing)
        self.assertIn(">Other Trust</a>", agreement)  # a joint controller, listed on the agreement
        # What is stored and searched stays as the register wrote it.
        self.assertIn('data-search="', listing)

    def test_a_name_already_in_mixed_case_gets_no_note(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out)
            slug = "nhs-bristol-north-somerset-and-south-gloucestershire-icb-15c"
            page = (out / "organisations" / slug / "index.html").read_text()
        self.assertNotIn("writes this name in capitals", page)


class ReleaseWording(unittest.TestCase):
    """What a file release does and does not show, per docs/plan.md, "Release views"."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        with dataset_aliases():
            data = extract(workbook_bytes())
            by_slug = {a["slug"]: a for a in data["agreements"]}
            # One agreement whose files all went out under an earlier version,
            # and one with none at all that permits sublicensing.
            earlier = by_slug["dars-nic-1-aaaaa"]
            earlier["latest"]["releases"] = []
            earlier["latest"]["files_released"] = 0
            earlier["files_released"] = sum(v["files_released"] for v in earlier["versions"])
            none = by_slug["dars-nic-2-bbbbb"]
            none["latest"]["releases"] = []
            none["latest"]["files_released"] = 0
            none["latest"]["sublicensing"] = "Yes"
            none["files_released"] = 0
            build.build(data, site_meta(), FIRST_EDITION, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def page(self, path):
        return (self.out / path / "index.html").read_text()

    def test_no_files_is_not_said_to_mean_no_data_shared(self):
        page = self.page("agreements/dars-nic-2-bbbbb")
        self.assertIn("No files recorded as released under this agreement.", page)
        self.assertIn("/about/#file-releases", page)

    def test_files_released_under_earlier_versions_are_pointed_to(self):
        page = self.page("agreements/dars-nic-1-aaaaa")
        self.assertIn("No files recorded as released under the current version. 3 were released", page)

    def test_sublicensing_says_onward_sharing_is_not_recorded(self):
        self.assertIn("permits sublicensing", self.page("agreements/dars-nic-2-bbbbb"))
        self.assertNotIn("permits sublicensing", self.page("agreements/dars-nic-1-aaaaa"))

    def test_about_page_does_not_treat_files_as_everything_that_moved(self):
        page = self.page("about")
        self.assertNotIn("better sense of what actually moved", page)
        self.assertIn('id="file-releases"', page)
        self.assertIn("File releases are recorded from January 2020.", page)


class MergerEdition(unittest.TestCase):
    """February 2023's departures are labelled, per docs/plan.md, "Release views"."""

    def changes_page(self, edition: str) -> str:
        removed = [{"base": "DARS-NIC-9-ZZZZZ", "reference": "DARS-NIC-9-ZZZZZ-v1",
                    "title": "Internal flow", "org": "NHS DIGITAL"}]
        changes = {**FIRST_EDITION, "comparable": True, "reason": "", "skipped": [],
                   "previous_edition": "january2023", "removed": removed}
        meta = {**site_meta(), "edition": edition}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with dataset_aliases():
                build.build(extract(workbook_bytes()), meta, changes, out)
            return (out / "changes" / "index.html").read_text()

    def test_february_2023_says_departures_moved_register(self):
        self.assertIn("moved to another register rather than ended", self.changes_page("february2023"))

    def test_other_editions_say_nothing_about_the_merger(self):
        self.assertNotIn("merged into NHS England", self.changes_page("march2023"))


class ReleaseScope(unittest.TestCase):
    def test_every_page_counting_files_says_what_they_cover(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(out)
            for path in ("agreements", "organisations", "datasets", "agreements/dars-nic-1-aaaaa",
                         "organisations/university-of-example",
                         "datasets/msds-maternity-services-data-set-v1-5"):
                with self.subTest(path=path):
                    page = (out / path / "index.html").read_text()
                    self.assertIn("files released externally by DARS", page)
                    self.assertIn("/about/#file-releases", page)


class NhsLineage(unittest.TestCase):
    """One page per ICB, codes kept out of names: docs/organisation-names.md."""

    @classmethod
    def setUpClass(cls):
        from .fixtures import _record, _role, lineage_files

        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        codes = [
            {"name": "NHS Bristol, North Somerset and South Gloucestershire ICB - 15C", "code": "15C", "evidence": "test"},
            {"name": "NHS BRISTOL, NORTH SOMERSET AND SOUTH GLOUCESTERSHIRE CCG", "code": "15C", "as": "CCG",
             "evidence": "test"},
        ]
        world = {
            "15C": _record("NHS BRISTOL, NORTH SOMERSET AND SOUTH GLOUCESTERSHIRE ICB - 15C",
                           [_role("RO98", "2020-04-01", primary=True), _role("RO319", "2022-07-01")], icb="QUY"),
            "QUY": _record("NHS BRISTOL, NORTH SOMERSET AND SOUTH GLOUCESTERSHIRE INTEGRATED CARE BOARD",
                           [_role("RO261", "2017-04-01", primary=True)]),
        }
        with dataset_aliases():
            lineage_files(codes, world)
            build.build(extract(workbook_bytes()), site_meta(), FIRST_EDITION, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_the_icb_has_one_page_listing_its_sub_icb_locations(self):
        slug = "nhs-bristol-north-somerset-and-south-gloucestershire-integrated-care-board"
        page = (self.out / "organisations" / slug / "index.html").read_text()
        self.assertIn("<h1>NHS Bristol, North Somerset and South Gloucestershire Integrated Care Board</h1>", page)
        self.assertIn(">15C</span>, formerly NHS Bristol, North Somerset and South Gloucestershire CCG", page)
        self.assertIn("Open Government Licence v3.0", page)
        # The sub-ICB location has no page of its own: its old address forwards to the ICB's.
        old = (self.out / "organisations" / "nhs-bristol-north-somerset-and-south-gloucestershire-icb-15c" / "index.html").read_text()
        self.assertIn(f'<meta http-equiv="refresh" content="0; url=/organisations/{slug}/">', old)
        self.assertIn('<meta name="robots" content="noindex">', old)
        self.assertNotIn("<table", old)

    def test_the_agreement_names_its_applicant_without_the_code(self):
        page = (self.out / "agreements" / "dars-nic-2-bbbbb" / "index.html").read_text()
        self.assertIn("NHS Bristol, North Somerset and South Gloucestershire ICB</a>", page)
        self.assertNotIn("ICB - 15C", page)

    def test_the_about_page_credits_ods(self):
        page = (self.out / "about" / "index.html").read_text()
        self.assertIn("NHS Organisation Data Service", page)


class Exclusions(unittest.TestCase):
    def test_an_excluded_agreement_has_no_page_and_is_not_counted(self):
        from .fixtures import exclude

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with dataset_aliases():
                exclude("DARS-NIC-2-BBBBB")
                build.build(extract(workbook_bytes()), site_meta(), FIRST_EDITION, out)
            self.assertFalse((out / "agreements" / "dars-nic-2-bbbbb").exists())
            self.assertNotIn("DARS-NIC-2-BBBBB", (out / "agreements" / "index.html").read_text())
            self.assertIn('<span class="stat-number">1</span><span class="stat-label">data sharing agreements',
                          (out / "index.html").read_text())


class ArchivedAgreements(unittest.TestCase):
    """Agreements no longer in the register keep their pages, outside every count."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        with dataset_aliases():
            data = extract(workbook_bytes())
            left = next(a for a in data["agreements"] if a["base_reference"] == "DARS-NIC-2-BBBBB")
            # The register as it would be without it: organisations and
            # datasets are derived from the agreements still listed.
            from pipeline.extract import assemble
            data = assemble({a["base_reference"]: a["versions"] for a in data["agreements"] if a is not left})
            left["archived"] = {"last_edition": "january2023", "next_edition": "february2023"}
            data["archived"] = [left]
            kept = data["agreements"][0]
            later = {**kept["latest"], "reference": "DARS-NIC-1-AAAAA-v3", "version": "3",
                     "last_edition": "january2023"}
            kept["dropped_versions"] = kept["later_dropped"] = [later]
            removed = [{"base": "DARS-NIC-2-BBBBB", "reference": "DARS-NIC-2-BBBBB-v1",
                        "title": "Ambulance study", "org": left["organisation"]}]
            changes = {**FIRST_EDITION, "comparable": True, "reason": "", "skipped": [],
                       "previous_edition": "august2026", "removed": removed}
            build.build(data, site_meta(), changes, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def read(self, path):
        return (self.out / path / "index.html").read_text()

    def test_the_page_says_it_is_no_longer_listed_and_why_it_most_likely_left(self):
        page = self.read("agreements/dars-nic-2-bbbbb")
        self.assertIn("No longer in the register.", page)
        self.assertIn("last published in the January 2023 edition", page)
        self.assertIn("most likely moved rather than ended", page)
        self.assertIn("Latest version", page)

    def test_it_is_listed_apart_and_not_counted(self):
        listing = self.read("agreements")
        self.assertIn("No longer in the register (1)", listing)
        self.assertIn('<span class="stat-number">1</span><span class="stat-label">data sharing agreements',
                      self.read(""))
        # Listed apart, below the table, not in it.
        table = listing[listing.index('id="agreements-table"'):listing.index("</table>")]
        self.assertNotIn("DARS-NIC-2-BBBBB", table)

    def test_the_changes_page_links_to_it(self):
        self.assertIn('href="/agreements/dars-nic-2-bbbbb/"', self.read("changes"))

    def test_its_citation_names_the_last_edition_that_listed_it(self):
        page = self.read("agreements/dars-nic-2-bbbbb")
        self.assertIn("NHS England (2023) <cite>Data Uses Register</cite>, January 2023 edition, "
                      "agreement DARS-NIC-2-BBBBB, “Ambulance study”.", page)

    def test_an_organisation_named_only_by_it_keeps_a_page_outside_the_counts(self):
        slug = "nhs-bristol-north-somerset-and-south-gloucestershire-icb-15c"
        self.assertIn("No longer in the register.", self.read(f"organisations/{slug}"))
        self.assertIn("No longer in the register (1)", self.read("organisations"))
        # University of Example, and Other Trust as a joint controller: not the archived one.
        self.assertIn('<span class="stat-number">2</span><span class="stat-label">organisations', self.read(""))

    def test_a_dataset_named_only_by_it_keeps_a_page_and_a_shared_one_lists_it_apart(self):
        self.assertIn("No longer in the register.", self.read("datasets/other-data-set"))
        self.assertIn("No longer in the register (1)", self.read("datasets"))
        shared = self.read("datasets/msds-maternity-services-data-set-v1-5")
        self.assertNotIn('<p class="notice"><strong>No longer in the register.', shared)
        self.assertIn('href="/agreements/dars-nic-2-bbbbb/"', shared)

    def test_a_later_version_that_left_is_noted_beside_the_current_one(self):
        page = self.read("agreements/dars-nic-1-aaaaa")
        self.assertIn("A later version has left the register.", page)
        self.assertIn("v3</a>", page)

    def test_links_stay_whole(self):
        broken, _ = linkcheck.check(self.out)
        self.assertFalse(broken)


class ChangeDetails(unittest.TestCase):
    def test_the_changes_page_shows_what_changed_and_register_wide_edits_once(self):
        amended = [{"base": "DARS-NIC-1-AAAAA", "reference": "DARS-NIC-1-AAAAA-v2", "title": "Maternity study",
                    "org": "UNIVERSITY OF EXAMPLE", "fields": ["End date"],
                    "details": [{"label": "End date", "kind": "value", "before": "2030-01-01", "after": "2031-06-01"}]}]
        wide = [{"edits": [{"field": "Datasets: legal basis", "removed": "s261(1) and", "added": ""}],
                 "agreements": 639, "versions": [{**amended[0], "reference": "DARS-NIC-1-AAAAA-v1"}]}]
        changes = {**FIRST_EDITION, "comparable": True, "reason": "", "skipped": [],
                   "previous_edition": "august2026", "amended": amended, "wide_edits": wide}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with dataset_aliases():
                build.build(extract(workbook_bytes()), site_meta(), changes, out)
            page = (out / "changes" / "index.html").read_text()
        self.assertIn("<del>1 January 2030</del> → <ins>1 June 2031</ins>", page)
        self.assertIn('id="register-wide"', page)
        self.assertIn("Datasets: legal basis: “<del>s261(1) and</del>” taken out", page)
        self.assertIn("across 639 agreements", page)
        self.assertIn('<span class="stat-number">1</span><span class="stat-label">register-wide edit</span>', page)
