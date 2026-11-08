import unittest
import xml.dom.minidom

from pipeline import feeds

from .fixtures import site_meta

META = {**site_meta(), "edition": "november2026"}
HISTORY = [
    {"edition": "october2026", "previous_edition": "september2026", "added": [], "removed": [],
     "amended": [{"reference": "DARS-NIC-1-AAAAA-v2", "base": "DARS-NIC-1-AAAAA", "org": "UNIVERSITY OF LEEDS",
                  "title": "Maternity study", "fields": ["End date"]}]},
    {"edition": "november2026", "previous_edition": "october2026", "amended": [], "removed": [],
     "added": [{"reference": "DARS-NIC-2-BBBBB-v0.1", "base": "DARS-NIC-2-BBBBB", "org": "BANGOR UNIVERSITY",
                "title": "COPE study", "kind": "new"}]},
]
AGREEMENTS = {
    "DARS-NIC-1-AAAAA": {"slug": "dars-nic-1-aaaaa", "organisation_slug": "university-of-leeds",
                         "controller_slugs": ["leeds-trust"], "dataset_slugs": ["hes"]},
    "DARS-NIC-2-BBBBB": {"slug": "dars-nic-2-bbbbb", "organisation_slug": "bangor-university",
                         "controller_slugs": ["bangor-university"], "dataset_slugs": ["hes", "msds"]},
}


class Feeds(unittest.TestCase):
    def test_the_register_feed_has_an_entry_per_edition_newest_first(self):
        feed = feeds.site_feed(META, HISTORY)
        xml.dom.minidom.parseString(feed)
        self.assertLess(feed.index("November 2026 edition: 1 added"), feed.index("October 2026 edition: 0 added, 1 amended"))
        # The newest edition is the changes page itself; older ones have their own.
        self.assertIn('href="https://example.test/changes/"/>', feed)
        self.assertIn('href="https://example.test/changes/october2026/"/>', feed)
        # Dated by edition, not by build, so a rebuild writes the same feed.
        self.assertIn("<updated>2026-11-01T00:00:00Z</updated>", feed)
        self.assertEqual(feed, feeds.site_feed(META, list(reversed(HISTORY))))

    def test_a_change_reaches_its_applicant_controllers_and_datasets(self):
        pages = feeds.page_entries(HISTORY, AGREEMENTS, META)
        self.assertEqual(set(pages["organisations"]), {"university-of-leeds", "leeds-trust", "bangor-university"})
        self.assertEqual(len(pages["organisations"]["bangor-university"]), 1)
        self.assertEqual([e["title"] for e in pages["datasets"]["hes"]],
                         ["Added: COPE study (Bangor University)", "Amended (end date): Maternity study (University of Leeds)"])

    def test_an_organisation_feed_is_valid_atom(self):
        pages = feeds.page_entries(HISTORY, AGREEMENTS, META)
        feed = feeds.page_feed(META, "organisations", "university-of-leeds", "University of Leeds & Partners",
                               pages["organisations"]["university-of-leeds"])
        document = xml.dom.minidom.parseString(feed)
        self.assertEqual(document.documentElement.getAttribute("xmlns"), "http://www.w3.org/2005/Atom")
        self.assertIn("University of Leeds &amp; Partners", feed)
        self.assertIn('href="https://example.test/agreements/dars-nic-1-aaaaa/"', feed)

    def test_a_change_to_an_unknown_agreement_is_left_out(self):
        pages = feeds.page_entries(HISTORY, {}, META)
        self.assertEqual(pages, {"organisations": {}, "datasets": {}})


if __name__ == "__main__":
    unittest.main()
