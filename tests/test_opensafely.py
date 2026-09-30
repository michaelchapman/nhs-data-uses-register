import tempfile
import unittest
from pathlib import Path

from pipeline import build, linkcheck, opensafely
from pipeline.extract import extract

from .fixtures import FIRST_EDITION, dataset_aliases, site_meta, workbook_bytes

# Two cards as opensafely.org writes them: a recent project, split over lines
# with a space before its colon and a start date, and an early COVID-19 one.
LISTING = """
<ul class="m-0 grid">
  <li
    class="flex max-w-prose flex-col items-start"
  >
    <h3 class="m-0 p-0">
      <a class="link" href="https://www.opensafely.org/project/pos-2026-3015/">
        POS-2026-3015 : OptiFIT: Optimising faecal immunochemical testing
      </a>
    </h3>
    <p class="m-0 p-0 leading-snug">
                    Research                project run by
      University of Nottingham.
    </p>
    <div class="mt-auto flex"><time datetime="2026-09-30T01:00:00+01:00">September 2026</time></div>
  </li>
  <li class="flex max-w-prose flex-col items-start">
    <h3><a class="link" href="https://www.opensafely.org/project/11/"> Project #11: Assessing the impact of COVID-19 on antidepressant prescribing </a></h3>
    <p class="m-0 p-0 leading-snug"> Service evaluation project run by NHS England and NHS Improvement. </p>
    <div class="mt-auto flex"> <span></span> <span
      class="inline-flex rounded bg-blue-100" > COVID-19 </span> </div>
  </li>
</ul>
<a href="https://www.opensafely.org/projects/page/2/">2</a>
"""

PROJECT = """
<ul>
  <li>
    <strong>
      Study lead:
    </strong>
    <a href="mailto:someone@example.test">Someone</a>
  </li>
  <li><strong>Organisation:</strong> The London School of Hygiene and Tropical Medicine</li>
  <li>
    <strong>Project type:</strong>
    Research
  </li>
  <li>
    <strong>Start date:</strong>
    17 September 2026
  </li>
  <li>
    <a href="https://jobs.opensafely.org/integrate/">View project progress, open code and outputs</a>
  </li>
</ul>
"""

# An early project's page: no start date, and its outputs link sits inside the
# empty type field.
OLD_PROJECT = """
<ul>
  <li><strong>Organisation:</strong> NHS England and NHS Improvement</li>
  <li>
    <strong>Project type:</strong>
    <a href="https://jobs.opensafely.org/antidepressants/">View project progress, open code and outputs</a>
  </li>
</ul>
"""


def project(number, organisation, listed=True):
    return {
        "number": number, "title": f"Title {number}", "type": "Research", "organisation": organisation,
        "covid": False, "page_url": f"https://www.opensafely.org/project/{number}/", "start_date": "",
        "jobs_url": "", "listed": listed,
    }


class Parsing(unittest.TestCase):
    def test_reads_the_cards(self):
        cards = opensafely.parse_listing(LISTING)
        self.assertEqual([c["number"] for c in cards], ["POS-2026-3015", "Project #11"])
        self.assertEqual(cards[0]["title"], "OptiFIT: Optimising faecal immunochemical testing")
        self.assertEqual(cards[0]["type"], "Research")
        self.assertEqual(cards[0]["organisation"], "University of Nottingham")
        self.assertFalse(cards[0]["covid"])
        self.assertTrue(cards[1]["covid"])
        self.assertEqual(cards[1]["organisation"], "NHS England and NHS Improvement")
        self.assertEqual(opensafely.next_pages(LISTING), ["https://www.opensafely.org/projects/page/2/"])

    def test_a_card_it_cannot_read_stops_the_ingest(self):
        broken = LISTING.replace("project run by", "run by")
        with self.assertRaises(ValueError):
            opensafely.parse_listing(broken)

    def test_reads_a_project_page_and_leaves_out_the_study_lead(self):
        page = opensafely.parse_project(PROJECT)
        self.assertEqual(page, {
            "organisation": "The London School of Hygiene and Tropical Medicine",
            "type": "Research",
            "start_date": "2026-09-17",
            "jobs_url": "https://jobs.opensafely.org/integrate/",
        })

    def test_an_early_page_has_no_type_or_start_date(self):
        page = opensafely.parse_project(OLD_PROJECT)
        self.assertEqual(page["type"], "")
        self.assertEqual(page["start_date"], "")
        self.assertEqual(page["jobs_url"], "https://jobs.opensafely.org/antidepressants/")

    def test_numbers_sort_old_scheme_first(self):
        numbers = ["POS-2026-3001", "Project #210", "Project #11", "POS-2025-3002"]
        self.assertEqual(
            sorted(numbers, key=opensafely.sort_key),
            ["Project #11", "Project #210", "POS-2025-3002", "POS-2026-3001"],
        )


class Store(unittest.TestCase):
    def test_a_project_the_list_drops_is_kept_and_marked(self):
        held = [project("Project #1", "A"), project("Project #2", "B")]
        merged = opensafely.merge(held, [{**project("Project #2", "B2")}])
        self.assertEqual([(p["number"], p["listed"]) for p in merged], [("Project #1", False), ("Project #2", True)])
        self.assertEqual(merged[1]["organisation"], "B2")

    def test_organisations_are_placed_by_the_map_then_by_name(self):
        projects = [
            project("Project #1", "University of Oxford and LSHTM"),
            project("Project #2", "University of Example"),
            project("Project #3", "NHSX"),
            project("Project #4", "Somewhere Else"),
        ]
        config = {
            "pages": {"University of Oxford and LSHTM": ["university-of-oxford", "lshtm", "no-such-page"]},
            "none": {"NHSX": "No agreement in the register."},
        }
        slugs = {"university-of-oxford", "lshtm", "university-of-example"}
        pages = opensafely.organisation_pages(projects, lambda n: n.lower().replace(" ", "-"), slugs, config)
        self.assertEqual(pages, {
            "University of Oxford and LSHTM": ["university-of-oxford", "lshtm"],
            "University of Example": ["university-of-example"],
        })
        self.assertEqual(opensafely.unmatched(projects, pages, config), ["Somewhere Else"])
        self.assertEqual(opensafely.unknown_pages(config, slugs), ["no-such-page"])
        by_org = opensafely.by_organisation(projects, pages)
        self.assertEqual([p["number"] for p in by_org["university-of-oxford"]], ["Project #1"])


class Site(unittest.TestCase):
    def build(self, out, store):
        with dataset_aliases():
            build.build(extract(workbook_bytes()), site_meta(), FIRST_EDITION, out, opensafely_store=store)

    def test_projects_have_a_page_and_appear_on_their_organisation(self):
        store = {
            "source_url": opensafely.LISTING,
            "retrieved": "2026-09-30",
            "projects": [project("Project #7", "University of Example"), project("Project #8", "Nobody", listed=False)],
        }
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.build(out, store)
            listing = (out / "opensafely" / "index.html").read_text()
            organisation = (out / "organisations" / "university-of-example" / "index.html").read_text()
            broken, _ = linkcheck.check(out)
        self.assertIn("Title Project #7", listing)
        self.assertIn("no longer listed", listing)
        self.assertIn("retrieved 30 September 2026", listing)
        self.assertIn('id="opensafely"', organisation)
        self.assertIn("Title Project #7", organisation)
        self.assertNotIn("Title Project #8", organisation)
        self.assertEqual(dict(broken), {})

    def test_an_empty_store_still_builds_the_page(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            self.build(out, {"source_url": opensafely.LISTING, "retrieved": "", "projects": []})
            listing = (out / "opensafely" / "index.html").read_text()
        self.assertIn("No OpenSAFELY projects have been added", listing)


if __name__ == "__main__":
    unittest.main()
