import unittest

from pipeline import sources


class EditionDate(unittest.TestCase):
    def test_is_the_first_of_the_editions_month(self):
        self.assertEqual(sources.edition_date("july2026"), "2026-07-01")
        self.assertEqual(sources.edition_date("december2021"), "2021-12-01")

    def test_unreadable_edition_gives_nothing(self):
        self.assertEqual(sources.edition_date("nonsense"), "")


if __name__ == "__main__":
    unittest.main()
