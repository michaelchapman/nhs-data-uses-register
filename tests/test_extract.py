import unittest

from pipeline import facts
from pipeline.extract import extract
from pipeline.model import build_agreement
from pipeline.records import clean_line, known_organisation_names, resplit_list, split_list, tidy_version
from pipeline.references import slugify

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

    def test_a_controller_only_name_with_a_comma_stays_whole(self):
        # Never an applicant, so only the built-in list vouches for it.
        known = known_organisation_names(["UNIVERSITY OF YORK"])
        self.assertEqual(
            split_list("UNIVERSITY OF YORK, THE MINISTRY OF HOUSING, COMMUNITIES AND LOCAL GOVERNMENT", known),
            ["UNIVERSITY OF YORK", "THE MINISTRY OF HOUSING, COMMUNITIES AND LOCAL GOVERNMENT"],
        )

    def test_resplitting_rejoins_a_known_name_stored_in_halves(self):
        known = known_organisation_names([])
        self.assertEqual(
            resplit_list(["UNIVERSITY OF YORK", "THE MINISTRY OF HOUSING", "COMMUNITIES AND LOCAL GOVERNMENT"], known),
            ["UNIVERSITY OF YORK", "THE MINISTRY OF HOUSING, COMMUNITIES AND LOCAL GOVERNMENT"],
        )
        # Two organisations that are not one known name stay apart.
        self.assertEqual(resplit_list(["A", "B"], known), ["A", "B"])


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
            data = facts.rehydrate(stored)
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

    def test_a_renamed_dataset_lists_its_other_spellings(self):
        dataset = next(d for d in self.data["datasets"] if d["name"] == NEW_NAME)
        self.assertEqual(dataset["known_as"], [OLD_NAME])


class DatasetTitle(unittest.TestCase):
    """The alias file keys a page on the name the register dropped."""

    @classmethod
    def setUpClass(cls):
        with dataset_aliases(canonical=OLD_NAME):
            cls.data = extract(workbook_bytes())
        cls.dataset = next(d for d in cls.data["datasets"] if d["canonical"] == OLD_NAME)

    def test_the_page_is_titled_as_the_register_writes_it_now(self):
        # Both agreements' latest versions say NEW_NAME.
        self.assertEqual(self.dataset["name"], NEW_NAME)
        self.assertEqual(self.dataset["known_as"], [OLD_NAME])

    def test_the_page_keeps_the_address_of_the_canonical_name(self):
        self.assertEqual(self.dataset["slug"], slugify(OLD_NAME))
        self.assertEqual(self.dataset["files_released"], 7)


def _version(version, start, end):
    return {
        "reference": f"DARS-NIC-9-ZZZZZ-v{version}", "version": version, "title": "A study",
        "organisation": "UNIVERSITY OF EXAMPLE", "organisation_type": "Academic",
        "commercial": "No", "sublicensing": "No", "controller_basis": "Sole Data Controller",
        "controllers": ["UNIVERSITY OF EXAMPLE"], "start_date": start, "end_date": end,
        "datasets": [], "releases": [], "files_released": 0,
    }


class AgreementTerm(unittest.TestCase):
    def agreement(self, *versions):
        return build_agreement("DARS-NIC-9-ZZZZZ", list(versions), {}, {})

    def test_a_first_version_numbered_below_one_is_the_first(self):
        agreement = self.agreement(_version("0.4", "2025-01-27", "2030-01-26"))
        self.assertTrue(agreement["first_start_known"])

    def test_an_earliest_version_above_one_has_versions_before_it(self):
        agreement = self.agreement(_version("5.2", "2024-01-01", "2027-01-01"))
        self.assertFalse(agreement["first_start_known"])

    def test_the_latest_version_decides_when_the_term_ends(self):
        # DARS-NIC-147978-LZDFC: a v0.0 record runs to 2027, but v7.7, the
        # version that superseded it, ended in December 2022.
        agreement = self.agreement(
            _version("0.0", "2012-02-22", "2027-12-31"),
            _version("7.7", "2021-12-06", "2022-12-05"),
        )
        self.assertEqual(agreement["coverage_end"], "2022-12-05")

    def test_a_latest_version_with_no_end_date_falls_back_to_the_others(self):
        agreement = self.agreement(
            _version("1", "2020-01-01", "2023-01-01"),
            _version("2", "2023-01-01", ""),
        )
        self.assertEqual(agreement["coverage_end"], "2023-01-01")


if __name__ == "__main__":
    unittest.main()


class NotAReference(unittest.TestCase):
    def test_a_note_in_the_reference_column_is_not_an_agreement(self):
        # The March 2022 workbook carried "No filters applied" there.
        import io

        import openpyxl

        from pipeline.extract import extract

        from .fixtures import dataset_aliases, workbook_bytes

        book = openpyxl.load_workbook(io.BytesIO(workbook_bytes()))
        book["Agreements"].append(["No filters applied"])
        buffer = io.BytesIO()
        book.save(buffer)
        with dataset_aliases():
            bases = [a["base_reference"] for a in extract(buffer.getvalue())["agreements"]]
        self.assertEqual(sorted(bases), ["DARS-NIC-1-AAAAA", "DARS-NIC-2-BBBBB"])
