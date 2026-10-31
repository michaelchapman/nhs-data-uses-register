import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import build, overviews, summarise
from pipeline.extract import extract

from .fixtures import FIRST_EDITION, dataset_aliases, site_meta, workbook_bytes

REFERENCE = "DARS-NIC-1-AAAAA"


def build_with(entries: dict, out: Path) -> str:
    """The first agreement's page, built with `entries` as data/summaries.json."""
    with dataset_aliases(), tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "summaries.json"
        data = extract(workbook_bytes())
        agreement = next(a for a in data["agreements"] if a["base_reference"].upper() == REFERENCE)
        for entry in entries.values():
            entry.setdefault("hash", overviews.text_hash(agreement["latest"]))
        overviews.write(entries, path)
        with mock.patch.object(overviews, "PATH", path):
            build.build(data, site_meta(), FIRST_EDITION, out)
    return (out / "agreements" / REFERENCE.lower() / "index.html").read_text()


def entry(**extra) -> dict:
    return {"summary": "Leeds studies maternity care.", "model": "claude-haiku-5-5", "written": "2026-10-31", **extra}


class Overview(unittest.TestCase):
    def test_the_about_page_names_the_model(self):
        with tempfile.TemporaryDirectory() as directory:
            build_with({REFERENCE: entry(model="claude-sonnet-5-5")}, Path(directory))
            about = (Path(directory) / "about" / "index.html").read_text()
        self.assertIn('id="ai-overviews"', about)
        self.assertIn("Claude Sonnet 5.5 from Anthropic", about)

    def test_a_current_overview_is_shown_and_flagged_as_ai_generated(self):
        with tempfile.TemporaryDirectory() as directory:
            page = build_with({REFERENCE: entry()}, Path(directory))
        self.assertIn('<h2 id="overview">Overview</h2>', page)
        self.assertIn("AI-generated summary, not part of the register.", page)
        # The model is named on the About page, not on every agreement page.
        self.assertNotIn("Claude Haiku 5.5", page)
        self.assertIn("/about/#ai-overviews", page)
        self.assertIn("Leeds studies maternity care.", page)
        # It comes before the register's own text, and stays out of the
        # page's description, which search engines show without the flag.
        self.assertLess(page.index('id="overview"'), page.index('id="purpose"'))
        head = page[: page.index("</head>")]
        self.assertNotIn("Leeds studies", head)

    def test_an_overview_of_older_text_is_not_shown(self):
        with tempfile.TemporaryDirectory() as directory:
            page = build_with({REFERENCE: entry(hash="0" * 16)}, Path(directory))
        self.assertNotIn('id="overview"', page)

    def test_a_flagged_overview_is_held_back(self):
        with tempfile.TemporaryDirectory() as directory:
            page = build_with({REFERENCE: entry(flags=["long: 120 words"])}, Path(directory))
        self.assertNotIn('id="overview"', page)

    def test_no_overviews_file_means_no_overview(self):
        with tempfile.TemporaryDirectory() as directory:
            page = build_with({}, Path(directory))
        self.assertNotIn('id="overview"', page)

    def test_the_hash_follows_the_purpose_text_only(self):
        version = {"objective": "A", "activities": "B", "title": "T"}
        self.assertEqual(overviews.text_hash(version), overviews.text_hash({**version, "title": "Other"}))
        self.assertNotEqual(overviews.text_hash(version), overviews.text_hash({**version, "objective": "A2"}))


class Checks(unittest.TestCase):
    SOURCE = "Organisation: University of Leeds\nThe study uses Hospital Episode Statistics (HES)."

    def test_a_plain_overview_passes(self):
        self.assertEqual(summarise.check("University of Leeds uses HES data to study hospital stays.", self.SOURCE), [])

    def test_a_claim_about_releases_is_flagged(self):
        flags = summarise.check("University of Leeds has not yet been released any data.", self.SOURCE)
        self.assertIn("says whether data was released", flags)

    def test_a_name_the_text_never_uses_is_flagged(self):
        flags = summarise.check("University of Leeds uses HES data from Scotland.", self.SOURCE)
        self.assertIn("names not in the text: Scotland", flags)

    def test_a_long_overview_is_flagged(self):
        flags = summarise.check("University of Leeds " + "studies care " * 50, self.SOURCE)
        self.assertTrue(any(f.startswith("long:") for f in flags))

    def test_the_request_carries_the_purpose_text_but_not_the_activities(self):
        agreement = {
            "base_reference": REFERENCE, "title": "T", "organisation": "O",
            "latest": {"objective": "Obj", "activities": "Act", "expected_output": "Out",
                       "expected_benefits": "Ben", "yielded_benefits": "", "datasets": [{"name": "HES"}]},
        }
        text = summarise.agreement_text(agreement)
        for part in ("Obj", "Out", "Ben", "Datasets: HES", "## Benefits reported so far\n\nNot stated"):
            self.assertIn(part, text)
        self.assertNotIn("Act", text)
        params = summarise.request_params(agreement, "claude-haiku-5-5")
        self.assertEqual(params["model"], "claude-haiku-5-5")
        self.assertEqual(params["system"], summarise.INSTRUCTIONS)
