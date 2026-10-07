import json
import tempfile
import unittest
from pathlib import Path

from pipeline import build, search
from pipeline.extract import extract

from .fixtures import FIRST_EDITION, dataset_aliases, site_meta, workbook_bytes


def agreement(objective="", title="A study", organisation="University of Example", earlier=None):
    latest = {"objective": objective}
    return {
        "title": title,
        "base_reference": "DARS-NIC-1-AAAAA",
        "organisation": organisation,
        "dataset_names": ["Hospital Episode Statistics Admitted Patient Care"],
        "latest": latest,
        "versions": [earlier or latest, latest],
    }


def found(agreements, word):
    """The numbers of the agreements indexed under exactly `word`."""
    postings = search.build_index(agreements).get(word[0], {}).get(word)
    return search.decode(postings) if postings else []


class Words(unittest.TestCase):
    def test_splits_on_anything_but_letters_and_digits(self):
        self.assertEqual(search.words("COVID-19 (A&E) data."), {"covid", "19", "a", "e", "data"})

    def test_drops_apostrophes_so_kings_matches_king_s(self):
        self.assertEqual(search.words("King’s College, the patient's GP"), {"kings", "college", "the", "patients", "gp"})


class Encoding(unittest.TestCase):
    def test_sparse_and_dense_postings_round_trip(self):
        # [10] is one gap of 11, "b" in hexadecimal: it must not read as a bitset.
        for numbers in ([0], [10], [10, 11], [2, 3, 13], list(range(0, 100, 3)), [0, 99]):
            with self.subTest(numbers=numbers):
                self.assertEqual(search.decode(search.encode(numbers, 100)), numbers)

    def test_a_word_in_many_agreements_is_a_bitset(self):
        self.assertTrue(search.encode(list(range(50)), 100).startswith("x"))
        self.assertEqual(search.encode([2, 3, 13], 100), "3,1,a")


class Index(unittest.TestCase):
    def test_indexes_the_purpose_text_as_well_as_the_title_and_names(self):
        agreements = [agreement("Research into dementia care."), agreement("Cancer survival.")]
        self.assertEqual(found(agreements, "dementia"), [0])
        self.assertEqual(found(agreements, "cancer"), [1])
        self.assertEqual(found(agreements, "example"), [0, 1])  # organisation
        self.assertEqual(found(agreements, "episode"), [0, 1])  # dataset
        self.assertEqual(found(agreements, "nic"), [0, 1])  # reference

    def test_only_the_latest_version_is_searched(self):
        # The page shows the latest version; a match only in older text couldn't be seen.
        agreements = [agreement("Current aims.", earlier={"objective": "Marketing."})]
        self.assertEqual(found(agreements, "marketing"), [])
        self.assertEqual(found(agreements, "current"), [0])

    def test_an_acronym_matches_its_plural_both_ways(self):
        agreements = [agreement("Data about GPs."), agreement("Data from each GP practice.")]
        self.assertEqual(found(agreements, "gp"), [0, 1])
        self.assertEqual(found(agreements, "gps"), [0, 1])

    def test_ordinary_words_do_not_match_a_plural(self):
        # "ha" is not "has", and "doe" is not "does".
        agreements = [agreement("It has data and does analysis for GPs.")]
        self.assertEqual(found(agreements, "ha"), [])
        self.assertEqual(found(agreements, "doe"), [])

    def test_the_plural_is_judged_by_each_agreements_own_capitals(self):
        # MRIS, a service, is not the plural of MRI.
        agreements = [agreement("Uses MRIS data."), agreement("Two MRIs each.")]
        self.assertEqual(found(agreements, "mri"), [1])
        self.assertEqual(found(agreements, "mris"), [0, 1])


class BuiltIndex(unittest.TestCase):
    def test_the_build_writes_the_index_under_the_edition_and_numbers_the_rows(self):
        with tempfile.TemporaryDirectory() as directory, dataset_aliases():
            out = Path(directory)
            data = extract(workbook_bytes())
            meta = site_meta()
            build.build(data, meta, FIRST_EDITION, out)
            index = out / "search" / meta["edition"]
            files = sorted(p.name for p in index.iterdir())
            page = (out / "agreements" / "index.html").read_text()
            shard = json.loads((index / "o.json").read_text())

        self.assertIn("o.json", files)
        self.assertEqual(shard["agreements"], len(data["agreements"]))
        self.assertIn("objective", shard["words"])  # the fixture's purpose text
        self.assertIn(f'data-search-index="/search/{meta["edition"]}/"', page)
        for number, a in enumerate(data["agreements"]):
            self.assertRegex(page, rf'<tr data-i="{number}"[^>]*>\s*<th scope="row"><a href="/agreements/{a["slug"]}/"')

    def test_organisation_and_dataset_tables_search_the_same_index(self):
        with tempfile.TemporaryDirectory() as directory, dataset_aliases():
            out = Path(directory)
            data = extract(workbook_bytes())
            meta = site_meta()
            build.build(data, meta, FIRST_EDITION, out)
            numbers = {a["slug"]: n for n, a in enumerate(data["agreements"])}
            dataset = (out / "datasets" / "msds-maternity-services-data-set-v1-5" / "index.html").read_text()
            agreement = (out / "agreements" / "dars-nic-1-aaaaa" / "index.html").read_text()

        self.assertIn(f'data-search-index="/search/{meta["edition"]}/"', dataset)
        for slug in ("dars-nic-1-aaaaa", "dars-nic-2-bbbbb"):
            self.assertRegex(dataset, rf'<tr data-i="{numbers[slug]}" [^>]*>\s*<th scope="row"><a href="/agreements/{slug}/"')
        # The agreement page highlights a search it was opened from.
        self.assertIn('<script src="/assets/highlight.js" defer></script>', agreement)
        self.assertIn("data-search-note hidden", agreement)
        self.assertEqual(agreement.count('<details class="fold" data-highlight'), 5)



class Names(unittest.TestCase):
    def test_lists_names_busiest_first_with_the_spellings_merged_onto_each_page(self):
        organisations = [
            {"name": "SMALL TRUST", "slug": "small-trust", "agreement_count": 1, "known_as": {"SMALL TRUST"}},
            {"name": "Cambridge University Hospitals NHS Foundation Trust", "slug": "cuh", "agreement_count": 9,
             "known_as": {"ADDENBROOKE'S HOSPITAL", "Cambridge University Hospitals NHS Foundation Trust"}},
            {"name": "Gone Ltd", "slug": "gone-ltd", "agreement_count": 2, "known_as": set(),
             "archived": {"last_edition": "january2023"}},
            {"name": "Controller Ltd", "slug": "controller-ltd", "agreement_count": 0, "known_as": set(),
             "controller_agreements": [{}]},
        ]
        datasets = [{"name": "MSDS v1.5", "slug": "msds-v1-5", "agreement_count": 3}]
        groups = [{"canonical": "MSDS v1.5", "variants": ["Maternity Services Data Set v1.5"]}]
        names = search.names(organisations, datasets, groups)
        self.assertEqual(names["organisations"], [
            ["Cambridge University Hospitals NHS Foundation Trust", "cuh", 9, ["Addenbrooke's Hospital"], 0, ""],
            ["Small Trust", "small-trust", 1, [], 0, ""],
            # Still in the register, but only as a data controller.
            ["Controller Ltd", "controller-ltd", 0, [], 1, ""],
            # No longer in the register: none of its agreements is counted.
            ["Gone Ltd", "gone-ltd", 0, [], 0, "January 2023"],
        ])
        self.assertEqual(names["datasets"], [["MSDS v1.5", "msds-v1-5", 3, ["Maternity Services Data Set v1.5"], 0, ""]])

    def test_the_build_writes_names_beside_the_word_index(self):
        with dataset_aliases(), tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build.build(extract(workbook_bytes()), site_meta(), FIRST_EDITION, out)
            names = json.loads((out / "search" / "september2026" / "names.json").read_text())
            listing = (out / "agreements" / "index.html").read_text()
        self.assertIn("University of Example", [row[0] for row in names["organisations"]])
        self.assertIn('data-names="/search/september2026/names.json"', listing)
