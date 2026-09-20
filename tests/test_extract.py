import unittest

from pipeline.extract import extract, slugify, split_list

from .fixtures import NEW_NAME, OLD_NAME, dataset_aliases, workbook_bytes


class SplitList(unittest.TestCase):
    def test_semicolons_newlines_and_commas_separate(self):
        self.assertEqual(split_list("A; B\nC, D"), ["A", "B", "C", "D"])

    def test_comma_before_a_corporate_suffix_stays(self):
        self.assertEqual(split_list("MCKINSEY & COMPANY, INC. UNITED KINGDOM"),
                         ["MCKINSEY & COMPANY, INC. UNITED KINGDOM"])

    def test_commas_inside_brackets_stay(self):
        self.assertEqual(split_list("BCP COUNCIL [BOURNEMOUTH, CHRISTCHURCH AND POOLE], NHS X"),
                         ["BCP COUNCIL [BOURNEMOUTH, CHRISTCHURCH AND POOLE]", "NHS X"])

    def test_known_comma_names_stay_whole(self):
        known = ("NHS Bristol, North Somerset and South Gloucestershire ICB - 15C",)
        self.assertEqual(
            split_list("NHS Bristol, North Somerset and South Gloucestershire ICB - 15C, UNIVERSITY OF YORK", known),
            ["NHS Bristol, North Somerset and South Gloucestershire ICB - 15C", "UNIVERSITY OF YORK"],
        )


class Slugify(unittest.TestCase):
    def test_curly_and_straight_apostrophes_agree(self):
        self.assertEqual(slugify("ST GEORGE’S"), slugify("ST GEORGE'S"))

    def test_empty_falls_back(self):
        self.assertEqual(slugify(""), "unknown")


class Extract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with dataset_aliases():
            cls.data = extract(workbook_bytes())

    def test_versions_group_under_one_agreement(self):
        agreements = {a["base_reference"]: a for a in self.data["agreements"]}
        self.assertEqual(len(agreements), 2)
        self.assertEqual([v["version"] for v in agreements["DARS-NIC-1-AAAAA"]["versions"]], ["1", "2"])

    def test_comma_bearing_applicant_is_one_organisation(self):
        names = {o["name"] for o in self.data["organisations"]}
        self.assertIn("NHS Bristol, North Somerset and South Gloucestershire ICB - 15C", names)

    def test_renamed_dataset_is_one_page(self):
        names = [d["name"] for d in self.data["datasets"]]
        self.assertEqual(names.count(NEW_NAME), 1)
        self.assertNotIn(OLD_NAME, names)

    def test_renamed_dataset_counts_files_released_under_either_name(self):
        # 3 files under the old name, 2 + 1 under the new one.
        dataset = next(d for d in self.data["datasets"] if d["name"] == NEW_NAME)
        self.assertEqual(dataset["files_released"], 6)

    def test_dataset_files_add_up_to_the_agreements(self):
        self.assertEqual(
            sum(a["files_released"] for a in self.data["agreements"]),
            sum(d["files_released"] for d in self.data["datasets"]),
        )

    def test_organisation_dataset_names_are_canonical(self):
        university = next(o for o in self.data["organisations"] if o["name"] == "UNIVERSITY OF EXAMPLE")
        self.assertEqual(university["dataset_names"], [NEW_NAME])


if __name__ == "__main__":
    unittest.main()
