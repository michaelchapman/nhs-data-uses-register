"""The agreements search, in a browser, against a built site.

    pip install -r requirements-browser.txt && playwright install chromium
    python -m pipeline.run
    python -m unittest discover -s tests/browser

Kept out of the ordinary test run (this folder is not a package, so
`python -m unittest` doesn't find it): it needs a browser and a full build.
CI runs it after the build. It reads which agreements to search for from the
built list, so it holds whatever the edition is. Set `SITE_DIR` to test a site
built elsewhere, and `CHROMIUM` to use a browser other than Playwright's own.
"""

from __future__ import annotations

import functools
import http.server
import os
import re
import threading
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - the ordinary environment has no browser
    sync_playwright = None

SITE = Path(os.environ.get("SITE_DIR", Path(__file__).resolve().parents[2] / "_site"))


def _rows(page: str, table: str | None = None) -> list[tuple[str, str]]:
    """(reference, attributes) for each row of the agreements list, or of the table with id `table`."""
    if table:
        start = page.index(f'id="{table}"')
        page = page[start: page.index("</table>", start)]
    return [(m.group(2), m.group(1)) for m in re.finditer(
        r'<tr([^>]*)>\s*<th scope="row"><a href="/agreements/[^"]+/">.*?</a>\s*<span class="ref">([^<]+)</span>', page, re.S)]


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
@unittest.skipUnless((SITE / "agreements" / "index.html").exists(), f"no built site at {SITE}")
class Search(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(_Quiet, directory=str(SITE))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
        listing = (SITE / "agreements" / "index.html").read_text(encoding="utf-8")
        listed = [(ref, attrs) for ref, attrs in _rows(listing) if "data-i=" in attrs]
        cls.in_term = next(ref for ref, attrs in listed if 'data-active="yes"' in attrs)
        cls.expired = next(ref for ref, attrs in listed if 'data-active="no"' in attrs)
        earlier = re.search(r'id="earlier-table".*?<th scope="row"><a href="[^"]+">([^<]+)</a>', listing, re.S)
        cls.earlier_only = earlier.group(1) if earlier else None

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()

    def search(self, query: str, field: bool = True, url: str = "/agreements/"):
        """Open the agreements list and type `query` into its box, or open it with `url` as given."""
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.goto(self.base + url)
        if field:
            page.fill("[data-filter-text]", query)
        page.wait_for_function("!document.querySelector('[data-filter-count]').textContent.includes('Searching')")
        page.wait_for_timeout(300)
        return page

    def status(self, page) -> str:
        return page.locator("[data-filter-count]").inner_text().strip()

    def visible(self, page, reference: str) -> bool:
        return page.locator("tr", has_text=reference).filter(visible=True).count() > 0

    def test_a_reference_in_term_is_found(self):
        page = self.search(self.in_term)
        self.assertTrue(self.visible(page, self.in_term))
        self.assertRegex(self.status(page), r"^Showing 1 of ")

    def test_an_expired_reference_says_a_filter_hides_it(self):
        # "In term" starts ticked, so the match is hidden: the count must say
        # so, and offer to show it, not suggest shorter search words.
        page = self.search(self.expired)
        self.assertFalse(self.visible(page, self.expired))
        self.assertRegex(self.status(page), r"match(es)? (the search|outside these filters)")
        self.assertNotIn("shorter search words", self.status(page))
        page.locator("[data-filter-count] button").click()
        page.wait_for_timeout(200)
        self.assertTrue(self.visible(page, self.expired))

    def test_the_site_search_finds_an_expired_reference(self):
        page = self.search("", field=False, url=f"/agreements/?q={self.expired}&active=all")
        self.assertTrue(self.visible(page, self.expired))

    def test_an_earlier_only_reference_is_counted_below(self):
        if not self.earlier_only:
            self.skipTest("no agreements only in the earlier registers")
        page = self.search(self.earlier_only)
        self.assertTrue(self.visible(page, self.earlier_only))
        self.assertIn("1 listed below does", self.status(page))

    def test_a_purpose_word_finds_agreements(self):
        page = self.search("cancer")
        self.assertRegex(self.status(page), r"^Showing [\d,]+ of ")
        self.assertGreater(page.locator("#agreements-table tbody tr").filter(visible=True).count(), 0)

    def test_nonsense_finds_nothing_and_says_so(self):
        page = self.search("zzqxjv")
        self.assertIn("No agreements match", self.status(page))


if __name__ == "__main__":
    unittest.main()
