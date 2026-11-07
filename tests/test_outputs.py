import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import build, outputs
from pipeline.extract import extract

from .fixtures import FIRST_EDITION, dataset_aliases, site_meta, workbook_bytes

REFERENCE = "DARS-NIC-1-AAAAA"


def row(**extra) -> dict:
    return {
        "agreement": f"{REFERENCE}-v2",
        "doi": "10.1136/bmj-2024-000001",
        "title": "Maternity outcomes in England",
        "year": 2024,
        "basis": "found",
        "register_cited": False,
        **extra,
    }


def write(rows: list[dict], path: Path) -> None:
    path.write_text(json.dumps({
        "register_edition": "november2026", "source_commit": "c65350e", "exported": "2026-11-07", "outputs": rows,
    }))


def build_site(rows: list[dict] | None, out: Path) -> None:
    """The site, built with `rows` as data/outputs.json, or with no file if None."""
    with dataset_aliases(), tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "outputs.json"
        if rows is not None:
            write(rows, path)
        with mock.patch.object(outputs, "PATH", path):
            build.build(extract(workbook_bytes()), site_meta(), FIRST_EDITION, out)


def build_with(rows: list[dict] | None, out: Path) -> tuple[str, str]:
    """The first agreement's page and the About page, built with `rows` as data/outputs.json."""
    build_site(rows, out)
    page = (out / "agreements" / REFERENCE.lower() / "index.html").read_text()
    return page, (out / "about" / "index.html").read_text()


class Page(unittest.TestCase):
    def test_found_papers_are_listed_and_flagged_as_not_the_register(self):
        with tempfile.TemporaryDirectory() as directory:
            page, about = build_with([row()], Path(directory))
        self.assertIn('<h2 id="papers">Papers linked to this agreement</h2>', page)
        self.assertIn("Not part of the register.", page)
        self.assertIn("Papers found to have used this agreement's data", page)
        self.assertIn('<a href="https://doi.org/10.1136/bmj-2024-000001">Maternity outcomes in England</a>', page)
        self.assertIn("November 2026 edition", page)
        self.assertIn("/commit/c65350e", page)
        self.assertIn('href="#papers"', page)
        self.assertNotIn("benefit of", page.lower())
        # The fixture's register reports no benefits, so the page says the
        # papers come from the review.
        self.assertIn("These papers were found by the review, not cited by the register.", page)
        self.assertLess(page.index('id="purpose"'), page.index('id="papers"'))
        self.assertLess(page.index('id="papers"'), page.index('id="datasets"'))
        self.assertIn('id="papers"', about)
        self.assertIn("1 of the 2 agreement pages", about)

    def test_register_cited_papers_say_what_the_review_found(self):
        rows = [row(doi=f"10.1000/{basis}", title=f"Paper {basis}", basis=basis) for basis in outputs.RESULTS]
        with tempfile.TemporaryDirectory() as directory:
            page, about = build_with(rows, Path(directory))
        self.assertIn("Cited in the register, not confirmed by the review", page)
        text = page.replace("&#39;", "'")
        self.assertEqual(text.count("Not checked: full text not openly available"), 1)
        for word in ("another study", "names no NHS England data", "rejected"):
            self.assertNotIn(word, text[text.index('id="papers"'):text.index('id="datasets"')])
        self.assertNotIn("Papers found to have used", page)
        self.assertIn("4 more papers", about)

    def test_no_file_means_no_section(self):
        with tempfile.TemporaryDirectory() as directory:
            page, about = build_with(None, Path(directory))
        self.assertNotIn('id="papers"', page)
        self.assertNotIn('id="papers"', about)

    def test_titles_are_escaped(self):
        with tempfile.TemporaryDirectory() as directory:
            page, _ = build_with([row(title="<script>x</script> in A&E")], Path(directory))
        self.assertIn("&lt;script&gt;x&lt;/script&gt; in A&amp;E", page)


class PapersPage(unittest.TestCase):
    def test_each_paper_is_listed_once_with_its_agreements(self):
        rows = [
            row(),
            row(agreement=f"{REFERENCE}-v1"),
            row(doi="10.1000/other", title="A paper the register cites", basis="unreadable", year=2020),
            # Found under no agreement with a page: left out.
            row(agreement="DARS-NIC-99999-ZZZZZ", doi="10.1000/orphan", title="Orphan paper"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            build_site(rows, Path(directory))
            page = (Path(directory) / "papers" / "index.html").read_text()
            home = (Path(directory) / "index.html").read_text()
            sitemap = (Path(directory) / "sitemap.xml").read_text()
        self.assertIn("<h1>Published papers</h1>", page)
        self.assertEqual(page.count("https://doi.org/10.1136/bmj-2024-000001"), 1)
        self.assertIn("Not part of the register.", page)
        self.assertEqual(page.count('data-reason="found"'), 1)
        self.assertEqual(page.count('data-reason="cited"'), 1)
        self.assertIn('id="papers-table"', page)
        self.assertIn("filter.js", page)
        self.assertIn(f"/agreements/{REFERENCE.lower()}/", page)
        self.assertNotIn("Orphan paper", page)
        self.assertIn("2 published papers", page)
        self.assertIn('/papers/">Papers</a>', home)
        self.assertIn("/papers/</loc>", sitemap)

    def test_organisation_pages_link_to_their_papers(self):
        with tempfile.TemporaryDirectory() as directory:
            build_site([row()], Path(directory))
            page = (Path(directory) / "papers" / "index.html").read_text()
            organisation = (Path(directory) / "organisations" / "university-of-example" / "index.html").read_text()
        self.assertIn('/papers/?org=university-of-example">1</a>', organisation)
        self.assertIn('<option value="university-of-example">University of Example (1)</option>', page)

    def test_long_lists_on_an_agreement_page_fold_after_five(self):
        rows = [row(doi=f"10.1000/p{n}", title=f"Paper {n}", year=2010 + n) for n in range(8)]
        with tempfile.TemporaryDirectory() as directory:
            page, _ = build_with(rows, Path(directory))
        self.assertIn("Show 3 more", page)
        # Newest first, so the oldest three are the folded ones.
        self.assertLess(page.index("Paper 3<"), page.index("Show 3 more"))
        self.assertGreater(page.index("Paper 2<"), page.index("Show 3 more"))

    def test_figures_for_quoting_and_counting(self):
        rows = [
            row(),
            row(doi="10.1000/cited", title="A paper the register cites", basis="unreadable", year=2020),
            row(doi="10.1000/undated", title="No year", year=None),
            row(doi="10.1000/recent", title="This year", year=2026),
        ]
        with tempfile.TemporaryDirectory() as directory:
            build_site(rows, Path(directory))
            page = (Path(directory) / "papers" / "index.html").read_text()
            table = (Path(directory) / "papers" / "papers.csv").read_text()
            downloads = (Path(directory) / "downloads" / "index.html").read_text()
            datasets = list((Path(directory) / "datasets").glob("*/index.html"))
            dataset_pages = [d.read_text() for d in datasets]
        self.assertIn("Papers by year of publication", page)
        self.assertIn("2026 is a part year", page)
        self.assertIn("1 with no known year", page)
        self.assertIn('<th scope="row">2024</th><td class="num">1</td><td class="num">0</td>', page)
        self.assertIn("Agreements with a linked paper</dt><dd>1 of 2", page)
        self.assertIn('id="by-sector"', page)
        self.assertIn('data-key="sector"', page)
        self.assertIn('data-key="dataset"', page)
        # A control with id "dataset" would shadow the form's own `dataset` in filter.js.
        self.assertNotIn('id="dataset"', page)
        lines = table.splitlines()
        self.assertEqual(lines[0].split(",")[:3], ["title", "year", "doi"])
        self.assertEqual(len(lines), 5)
        self.assertIn("found to have used the data", table)
        self.assertIn("cited in the register, not confirmed", table)
        self.assertIn("/papers/papers.csv", page)
        self.assertIn("/papers/papers.csv", downloads)
        self.assertTrue(any("/papers/?dataset=" in d for d in dataset_pages))

    def test_lag_counts_from_the_earliest_known_start(self):
        def link(start, known=True):
            return {"agreement": {"first_start": start, "first_start_known": known}}
        papers = [{"year": 2020 + n % 5, "agreements": [link("2019-04-01"), link("2015-01-01", known=False)]}
                  for n in range(25)]
        # Published before its agreement started: left out.
        papers.append({"year": 2010, "agreements": [link("2019-04-01")]})
        lag = outputs.lag(papers)
        self.assertEqual(lag["papers"], 25)
        self.assertEqual(lag["median"], 3)
        self.assertIsNone(outputs.lag(papers[:5]))

    def test_no_file_means_no_page_and_no_menu_item(self):
        with tempfile.TemporaryDirectory() as directory:
            build_site(None, Path(directory))
            self.assertFalse((Path(directory) / "papers").exists())
            home = (Path(directory) / "index.html").read_text()
        self.assertNotIn("/papers/", home)

    def test_found_wins_when_a_paper_has_both_reasons(self):
        loaded = {"by_agreement": {
            "A": [{**row(), "id": "x", "url": "u", "basis": "found", "result": "", "register_cited": False}],
            "B": [{**row(), "id": "x", "url": "u", "basis": "unreadable", "result": "r", "register_cited": True}],
        }}
        agreements = [{"base_reference": "A", "organisation_slug": "a"}, {"base_reference": "B", "organisation_slug": "b"}]
        [paper] = outputs.papers(loaded, agreements)
        self.assertEqual(paper["basis"], "found")
        self.assertTrue(paper["register_cited"])
        self.assertEqual([link["basis"] for link in paper["agreements"]], ["found", "unreadable"])


class Load(unittest.TestCase):
    def load(self, rows: list[dict]) -> dict | None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outputs.json"
            write(rows, path)
            return outputs.load(path)

    def test_an_undecided_basis_stops_the_build(self):
        for basis in ("probable", "rejected", "protocol", None):
            with self.subTest(basis=basis), self.assertRaises(outputs.OutputsError):
                self.load([row(basis=basis)])

    def test_a_bad_doi_stops_the_build(self):
        with self.assertRaises(outputs.OutputsError):
            self.load([row(doi="not a doi")])

    def test_doi_urls_are_normalised_and_versions_grouped(self):
        loaded = self.load([row(doi="https://doi.org/10.1000/abc"), row(agreement=f"{REFERENCE}-v1", doi="10.1000/ABC")])
        self.assertEqual([r["url"] for r in loaded["by_agreement"][REFERENCE]], ["https://doi.org/10.1000/abc"])

    def test_only_known_fields_are_kept(self):
        loaded = self.load([row(quote="A long passage from the paper.")])
        self.assertNotIn("quote", loaded["by_agreement"][REFERENCE][0])

    def test_a_paper_with_no_doi_links_by_pmcid(self):
        loaded = self.load([row(doi="", pmcid="PMC123", title="")])
        paper = loaded["by_agreement"][REFERENCE][0]
        self.assertEqual(paper["url"], "https://europepmc.org/article/PMC/PMC123")
        self.assertEqual(paper["title"], "PMC123")
        self.assertTrue(paper["untitled"])

    def test_a_paper_with_neither_identifier_stops_the_build(self):
        with self.assertRaises(outputs.OutputsError):
            self.load([row(doi="", pmcid="")])

    def test_missing_file_is_none(self):
        self.assertIsNone(outputs.load(Path("/nonexistent/outputs.json")))


if __name__ == "__main__":
    unittest.main()
