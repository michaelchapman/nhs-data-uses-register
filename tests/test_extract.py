import unittest

from pipeline import editions
from pipeline.extract import clean_line, extract, slugify, split_list, tidy_version

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


class Whitespace(unittest.TestCase):
    def test_clean_line_collapses_spaces_and_line_breaks(self):
        self.assertEqual(clean_line("BCP COUNCIL  [BOURNEMOUTH,\n CHRISTCHURCH]"), "BCP COUNCIL [BOURNEMOUTH, CHRISTCHURCH]")
        self.assertEqual(clean_line(None), "")
        self.assertEqual(clean_line("  a\u00a0b\t"), "a b")

    def test_a_known_name_matches_however_its_spaces_fall(self):
        known = ("BCP COUNCIL [BOURNEMOUTH, CHRISTCHURCH AND POOLE]",)
        self.assertEqual(
            split_list("BCP COUNCIL  [BOURNEMOUTH, CHRISTCHURCH AND POOLE]; NHS X", known),
            ["BCP COUNCIL [BOURNEMOUTH, CHRISTCHURCH AND POOLE]", "NHS X"],
        )

    def test_a_newline_still_separates_controllers(self):
        self.assertEqual(split_list("A  B\nC"), ["A B", "C"])

    def version(self, **overrides):
        base = {
            "reference": "X-v1", "version": "1", "title": "A  title\nsplit", "organisation": "ORG  ONE",
            "organisation_type": "Academic ", "controller_basis": "Sole", "controllers": ["ORG  ONE", " "],
            "datasets": [{"name": "Data  Set", "type_of_data": "", "sensitivity": "", "frequency": "",
                          "legal_basis": "Other-a\nb", "confidentiality": ""}],
            "releases": [{"dataset": "Data  Set", "files": 1}],
            "objective": "Line one.\n\nLine  two.",
        }
        return {**base, **overrides}

    def test_tidy_version_cleans_names_but_leaves_prose_paragraphs(self):
        tidied = tidy_version(self.version())
        self.assertEqual(tidied["title"], "A title split")
        self.assertEqual(tidied["organisation"], "ORG ONE")
        self.assertEqual(tidied["controllers"], ["ORG ONE"])
        self.assertEqual(tidied["datasets"][0]["name"], "Data Set")
        self.assertEqual(tidied["datasets"][0]["legal_basis"], "Other-a b")
        self.assertEqual(tidied["releases"][0]["dataset"], "Data Set")
        self.assertEqual(tidied["objective"], "Line one.\n\nLine  two.")

    def test_tidy_version_is_idempotent(self):
        once = tidy_version(self.version())
        self.assertEqual(tidy_version(dict(once)), once)

    def test_a_stored_extract_is_tidied_when_read(self):
        stored = {"X": [{**self.version(), "start_date": "2020-01-01", "end_date": "2021-01-01",
                         "sublicensing": "No", "commercial": "No", "files_released": 0}]}
        with dataset_aliases():
            data = editions.rehydrate(stored)
        agreement = data["agreements"][0]
        self.assertEqual(agreement["organisation"], "ORG ONE")
        self.assertEqual(agreement["title"], "A title split")
        self.assertEqual(agreement["dataset_names"], ["Data Set"])


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
        # 3 files under the old name, 2 + 2 under the new one.
        dataset = next(d for d in self.data["datasets"] if d["name"] == NEW_NAME)
        self.assertEqual(dataset["files_released"], 7)

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
