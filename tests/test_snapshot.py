import unittest

from pipeline import snapshot


def snap(edition: str, **versions: str) -> dict:
    """A minimal fingerprint: `{reference: digest}` under one agreement each."""
    return {
        "edition": edition,
        "fingerprint_version": snapshot.FINGERPRINT_VERSION,
        "versions": {
            reference: {"base": reference.rsplit("-v", 1)[0], "org": "ORG", "title": "T", "hashes": {"title": digest}}
            for reference, digest in versions.items()
        },
    }


class SkippedEditions(unittest.TestCase):
    def test_neighbouring_months_skip_nothing(self):
        self.assertEqual(snapshot.skipped_editions("december2024", "january2025"), [])

    def test_a_missing_month_is_named(self):
        self.assertEqual(snapshot.skipped_editions("december2024", "february2025"), ["january2025"])

    def test_several_months_across_a_year_end(self):
        self.assertEqual(
            snapshot.skipped_editions("october2024", "february2025"),
            ["november2024", "december2024", "january2025"],
        )

    def test_missing_editions_across_a_list(self):
        self.assertEqual(
            snapshot.missing_editions(["november2024", "december2024", "february2025", "april2025"]),
            ["january2025", "march2025"],
        )
        self.assertEqual(snapshot.missing_editions(["may2025"]), [])


class Diff(unittest.TestCase):
    def test_a_comparison_across_a_gap_says_what_it_skipped(self):
        changes = snapshot.diff(snap("february2025", **{"A-v1": "x"}), snap("december2024", **{"A-v1": "x"}))
        self.assertTrue(changes["comparable"])
        self.assertEqual(changes["skipped"], ["january2025"])

    def test_consecutive_editions_skip_nothing(self):
        changes = snapshot.diff(snap("february2025", **{"A-v1": "x"}), snap("january2025", **{"A-v1": "x"}))
        self.assertEqual(changes["skipped"], [])

    def test_first_edition_has_nothing_skipped(self):
        self.assertEqual(snapshot.diff(snap("july2021"), None)["skipped"], [])


class History(unittest.TestCase):
    def setUp(self):
        self.index = snapshot.history_index("unused", snapshots=[
            snap("november2024", **{"OLD-v1": "a"}),
            snap("december2024", **{"OLD-v1": "a"}),
            snap("february2025", **{"OLD-v1": "b", "NEW-v1": "n"}),
            snap("march2025", **{"OLD-v1": "b", "NEW-v1": "n"}),
        ])

    def test_an_edit_after_a_gap_notes_the_gap(self):
        (event,) = self.index["OLD"]["events"]
        self.assertEqual((event["edition"], event["skipped"]), ("february2025", ["january2025"]))

    def test_an_agreement_first_seen_after_a_gap_notes_the_gap(self):
        self.assertEqual(self.index["NEW"]["first_edition"], "february2025")
        self.assertEqual(self.index["NEW"]["first_skipped"], ["january2025"])

    def test_an_agreement_first_seen_after_no_gap_notes_nothing(self):
        index = snapshot.history_index("unused", snapshots=[snap("may2025"), snap("june2025", **{"A-v1": "x"})])
        self.assertEqual(index["A"]["first_skipped"], [])


if __name__ == "__main__":
    unittest.main()
