import unittest

from pipeline import datasetcheck

OLD = "Continuing Healthcare Dataset"
NEW = "Continuing Healthcare Dataset_UDAL"


def edition(name, other="Other Data Set"):
    return {"DARS-NIC-1-AAAAA-v1": {name, other}, "DARS-NIC-2-BBBBB-v1": {name}}


class Gather(unittest.TestCase):
    def test_a_name_replaced_on_every_agreement_is_a_rename_with_evidence(self):
        [candidate] = datasetcheck.gather({"june2026": edition(OLD), "july2026": edition(NEW)})
        self.assertEqual(candidate.names, [OLD, NEW])
        self.assertIn("July 2026", candidate.evidence)

    def test_the_name_replaced_is_the_canonical_so_its_page_keeps_its_address(self):
        [candidate] = datasetcheck.gather({"june2026": edition(OLD), "july2026": edition(NEW)})
        self.assertEqual(candidate.canonical, OLD)

    def test_editions_are_compared_in_date_order_whatever_order_they_come_in(self):
        [candidate] = datasetcheck.gather({"july2026": edition(NEW), "june2026": edition(OLD)})
        self.assertEqual(candidate.names, [OLD, NEW])

    def test_a_partial_overlap_is_left_for_a_person(self):
        before = {"A-v1": {OLD}, "B-v1": {OLD}, "C-v1": {OLD}}
        after = {"A-v1": {NEW}, "B-v1": {NEW}, "C-v1": {"Something else"}}
        [candidate] = datasetcheck.gather({"june2026": before, "july2026": after})
        self.assertIsNone(candidate.evidence)

    def test_nothing_renamed_is_nothing_to_check(self):
        self.assertEqual(datasetcheck.gather({"june2026": edition(OLD), "july2026": edition(OLD)}), [])


if __name__ == "__main__":
    unittest.main()
