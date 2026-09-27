import unittest

from pipeline.orgcheck import weighted_similarity


class WeightedSimilarity(unittest.TestCase):
    def test_names_differing_only_in_a_dropped_word_are_flagged(self):
        # "The" and legal-form words are left out of the comparison, so these
        # two have the same words. They are the likeliest duplicates of all.
        candidates = weighted_similarity(["THE UNIVERSITY OF YORK", "UNIVERSITY OF YORK", "UNIVERSITY OF KENT"])
        self.assertEqual(
            [c.names for c in candidates], [["THE UNIVERSITY OF YORK", "UNIVERSITY OF YORK"]]
        )
        self.assertEqual(candidates[0].label, "similarity 1.00")


if __name__ == "__main__":
    unittest.main()
