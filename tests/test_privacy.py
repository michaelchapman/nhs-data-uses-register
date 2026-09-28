import tempfile
import unittest
from pathlib import Path

from pipeline import build, privacy
from pipeline.extract import extract, summarise_releases

from .fixtures import FIRST_EDITION, dataset_aliases, site_meta, workbook_bytes

S251 = "Section 251 NHS Act 2006"
NONE = "Does not include the flow of confidential data"
S251_AND_NONE = (
    "Mixture of confidential data flow(s) with support under section 251 NHS Act 2006 "
    "and non-confidential data flow(s)"
)


def datasets(*values):
    return [{"name": f"Dataset {i}", "confidentiality": value} for i, value in enumerate(values)]


def version(reference, *answers):
    """A version whose files were released with these opt-out answers."""
    released = [
        {"file": f"F{i}", "dataset": "HES", "month": "2022-01", "opt_outs_applied": answer}
        for i, answer in enumerate(answers)
    ]
    return {"reference": reference, "releases": summarise_releases(released, [])}


class Confidentiality(unittest.TestCase):
    def test_every_register_value_names_a_listed_basis(self):
        listed = {key for key, _ in privacy.CONFIDENTIALITY_OPTIONS}
        for value, bases in privacy.CONFIDENTIALITY.items():
            with self.subTest(value=value):
                self.assertTrue(bases)
                self.assertLessEqual(set(bases), listed)

    def test_each_basis_any_dataset_names_is_listed(self):
        self.assertEqual(
            privacy.confidentiality(datasets(S251, "Consent (Reasonable Expectation)", NONE)),
            ["consent", "s251"],
        )

    def test_a_mixture_names_each_of_its_bases(self):
        self.assertEqual(privacy.confidentiality(datasets(S251_AND_NONE)), ["s251"])

    def test_no_confidential_data_means_none_on_any_dataset(self):
        self.assertEqual(privacy.confidentiality(datasets(NONE, NONE)), ["none"])

    def test_a_blank_value_is_not_recorded_and_is_not_read_as_none(self):
        self.assertEqual(privacy.confidentiality(datasets(NONE, "")), ["not-recorded"])
        self.assertEqual(privacy.confidentiality(datasets(S251, "")), ["s251", "not-recorded"])

    def test_no_datasets_is_not_recorded(self):
        self.assertEqual(privacy.confidentiality([]), ["not-recorded"])

    def test_an_unknown_value_stops_the_build(self):
        with self.assertRaises(SystemExit) as raised:
            privacy.confidentiality(datasets("Yes"))
        self.assertIn('"Yes"', str(raised.exception))


class OptOuts(unittest.TestCase):
    def test_every_file_applied(self):
        self.assertEqual(privacy.opt_outs([version("v1", "Yes", "Yes")]),
                         {"state": "all", "applied": 2, "files": 2})

    def test_no_file_applied(self):
        self.assertEqual(privacy.opt_outs([version("v1", "No")]),
                         {"state": "none", "applied": 0, "files": 1})

    def test_some_files_applied_within_one_dataset(self):
        self.assertEqual(privacy.opt_outs([version("v1", "Yes", "No", "No")]),
                         {"state": "some", "applied": 1, "files": 3})

    def test_every_version_counts_not_only_the_latest(self):
        # The latest version on its own would be "none".
        self.assertEqual(privacy.opt_outs([version("v1", "Yes"), version("v2", "No")]),
                         {"state": "some", "applied": 1, "files": 2})
        self.assertEqual(privacy.opt_outs([version("v1", "Yes"), version("v2")])["state"], "all")

    def test_no_files_recorded(self):
        self.assertEqual(privacy.opt_outs([version("v1"), {"reference": "v2"}]),
                         {"state": "no-files", "applied": 0, "files": 0})

    def test_an_unknown_answer_stops_the_build(self):
        for answer in ("", "Partly"):
            with self.subTest(answer=answer), self.assertRaises(SystemExit):
                privacy.opt_outs([version("v1", "Yes", answer)])


class Counts(unittest.TestCase):
    def test_counts_follow_the_option_order_and_leave_out_empty_options(self):
        agreements = [
            {"confidentiality": ["consent", "s251"], "opt_outs": {"state": "some"}},
            {"confidentiality": ["s251"], "opt_outs": {"state": "no-files"}},
        ]
        self.assertEqual(privacy.counts(agreements), {
            "confidentiality": [("s251", "Section 251 support", 2), ("consent", "Consent", 1)],
            "opt_outs": [("some", "Applied to some files released", 1), ("no-files", "No files recorded", 1)],
        })


class BuiltSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory, dataset_aliases():
            out = Path(directory)
            build.build(extract(workbook_bytes()), site_meta(), FIRST_EDITION, out)
            cls.agreements = (out / "agreements" / "index.html").read_text()
            cls.about = (out / "about" / "index.html").read_text()
            cls.first = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()
            cls.second = (out / "agreements" / "dars-nic-2-bbbbb" / "index.html").read_text()

    def test_the_agreements_list_filters_on_both(self):
        self.assertIn('data-filter-tokens data-key="confidentiality"', self.agreements)
        self.assertIn('data-key="optouts"', self.agreements)
        self.assertIn('<option value="s251">Section 251 support (2)</option>', self.agreements)
        # Files under v1 as well as v2 count: the first agreement is "all", the
        # second has one file of each answer.
        self.assertIn('<option value="all">Applied to every file released (1)</option>', self.agreements)
        self.assertIn('<option value="some">Applied to some files released (1)</option>', self.agreements)
        self.assertEqual(self.agreements.count('data-confidentiality="s251" data-optouts="'), 2)

    def test_agreement_pages_say_how_many_files_had_opt_outs_applied(self):
        self.assertIn("applied to all 5 files released under this agreement, across every version", self.first)
        self.assertIn("applied to 1 of the 2 files released under this agreement", self.second)

    def test_the_filters_link_to_sections_that_exist(self):
        for anchor in ("confidential-data", "opt-outs"):
            with self.subTest(anchor=anchor):
                self.assertIn(f"/about/#{anchor}", self.agreements)
                self.assertIn(f'id="{anchor}"', self.about)
