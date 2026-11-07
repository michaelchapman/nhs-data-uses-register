import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import openpyxl

from pipeline import build, earlier
from pipeline.extract import extract

from .fixtures import FIRST_EDITION, dataset_aliases, site_meta, workbook_bytes

RELEASE_HEADER = [
    "RowID", "Organisation Name", "Type of Data Provided", "Data provided to customer:\nIdentifiable, Anonymised",
    "Sensitive or Non-Sensitive", "Legal Basis for Provision of Data (Dissemination)", "Purpose", "Frequency",
    "NIC Number", "MR Number (where relevant)",
]
PURPOSE_HEADER = [
    "Reference Number", "Organisation", "Objective for Processing", "Processing Activities", "Expected Output",
    "Expected Measurable Benefits", "Yielded Benefits", "Organisation Type",
]


def register(releases: list[list], purposes: list[list] | None = None, release_sheet="DataReleases") -> bytes:
    """A release register in the 2019 to 2021 layout, or the 2015 one without `purposes`."""
    book = openpyxl.Workbook()
    book.active.title = "Title sheet"
    sheet = book.create_sheet(release_sheet)
    sheet.append(RELEASE_HEADER)
    for n, row in enumerate(releases, 1):
        sheet.append([f"R{n}", *row])
    if purposes is not None:
        sheet = book.create_sheet("PurposeStatements")
        sheet.append(PURPOSE_HEADER)
        for row in purposes:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def release(reference, dataset="Other Data Set", organisation="UNIVERSITY OF LEEDS", purpose=None):
    return [organisation, dataset, "Pseudonymised", "Sensitive", "s261", purpose, "One-Off", reference, None]


def purpose(reference, objective, benefits=""):
    return [reference, "UNIVERSITY OF LEEDS", objective, "Activities", "Output", "Expected", benefits, "Academic"]


class Store:
    """Workbooks written to a folder, listed in a files table, and ingested into a store."""

    def __init__(self, directory: Path, books: dict[str, tuple[str, str, bytes]], skip: tuple[str, ...] = ()):
        self.folder = directory / "raw"
        self.folder.mkdir()
        rows = []
        for name, (start, end, data) in books.items():
            (self.folder / name).write_bytes(data)
            row = {"file": name, "period_start": start, "period_end": end,
                   "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            if name in skip:
                row["skip"] = "no references"
            rows.append(row)
        self.files = directory / "earlier-registers.json"
        self.files.write_text(json.dumps({"files": rows}))
        self.path = directory / "store"

    def ingest(self):
        with mock.patch("builtins.print"):
            return earlier.ingest(self.folder, self.path, self.files)


class ReferenceTest(unittest.TestCase):
    def test_prefix_and_version(self):
        self.assertEqual(earlier.references("NIC-12345-ABCDE"), [("DARS-NIC-12345-ABCDE", "")])
        self.assertEqual(earlier.references("DARS-NIC-12345-abcde-v2.1"), [("DARS-NIC-12345-ABCDE", "2.1")])

    def test_two_in_one_cell(self):
        self.assertEqual(
            earlier.references("NIC-11111-AAAAA-v1; NIC-22222-BBBBB-v3"),
            [("DARS-NIC-11111-AAAAA", "1"), ("DARS-NIC-22222-BBBBB", "3")],
        )

    def test_no_reference(self):
        self.assertEqual(earlier.references("Choose and Book"), [])

    def test_period_labels(self):
        self.assertEqual(earlier.period_label("2017-03-01", "2017-05-31"), "March to May 2017")
        self.assertEqual(earlier.period_label("2019-04-01", "2019-04-30"), "April 2019")
        self.assertEqual(earlier.period_label("2016-12-01", "2017-02-28"), "December 2016 to February 2017")


class DatasetMatchTest(unittest.TestCase):
    SPELLINGS = {
        "Hospital Episode Statistics Admitted Patient Care (HES APC)": "hes-apc",
        "Acute-Local Provider Flows": "acute",
        "Diagnostic Imaging Data Set (DID)": "did",
        "Mental Health Minimum Data Set": "mhmds",
        "Mental Health Minimum Data Set (MHMDS)": "mhmds-2",
    }

    def match(self, name):
        found = earlier.match_datasets([name], self.SPELLINGS)
        return found[name]["slug"] if name in found else None

    def test_exact(self):
        self.assertEqual(self.match("Acute-Local Provider Flows"), "acute")

    def test_spelling(self):
        self.assertEqual(self.match("Diagnostic Imaging Dataset"), "did")
        self.assertEqual(self.match("Hospital Episode Statistics Admitted Patient Care"), "hes-apc")

    def test_rewrites(self):
        self.assertEqual(self.match("Standard Monthly Extract : HES Inpatient"), "hes-apc")
        self.assertEqual(self.match("Local Provider Data - Acute"), "acute")

    def test_several_flows_or_pages_link_nowhere(self):
        self.assertIsNone(self.match("Local Provider Data - Acute, Ambulance"))
        # Two pages share the spelling key, so neither is chosen.
        self.assertIsNone(self.match("Mental Health Minimum Dataset"))
        self.assertIsNone(self.match("ONS Births"))

    def test_alias_map(self):
        found = earlier.match_datasets(["Old HES"], {"Acute": "acute"}, {"old hes": "Acute"})
        self.assertEqual(found["Old HES"]["slug"], "acute")


class ReadWorkbookTest(unittest.TestCase):
    def test_monthly_layout(self):
        found = earlier.read_workbook(register(
            [release("DARS-NIC-12345-ABCDE-v2"), release("DARS-NIC-12345-ABCDE-v2"),
             release("DARS-NIC-12345-ABCDE-v2", dataset="HES Outpatients")],
            [purpose("DARS-NIC-12345-ABCDE-v2", "Study asthma", "A paper")],
        ))
        item = found[("DARS-NIC-12345-ABCDE", "2")]
        self.assertEqual(item["organisation"], "UNIVERSITY OF LEEDS")
        self.assertEqual(item["organisation_type"], "Academic")
        self.assertEqual(item["texts"]["objective"], "Study asthma")
        self.assertEqual(item["texts"]["yielded_benefits"], "A paper")
        self.assertEqual(sum(item["releases"].values()), 3)
        self.assertEqual(len(item["releases"]), 2)

    def test_purpose_column_before_2016(self):
        found = earlier.read_workbook(register(
            [release("NIC-12345-ABCDE", purpose="Study asthma")], release_sheet="DataReleases_Jul_Sep2015",
        ))
        self.assertEqual(found[("DARS-NIC-12345-ABCDE", "")]["texts"], {"objective": "Study asthma"})

    def test_no_release_sheet(self):
        book = openpyxl.Workbook()
        buffer = io.BytesIO()
        book.save(buffer)
        with self.assertRaises(earlier.EarlierError):
            earlier.read_workbook(buffer.getvalue())


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        text = "Study asthma"
        self.store = Store(Path(self.directory.name), {
            "old.xlsx": ("2014-01-01", "2014-03-31", register([release("Not a reference")])),
            "a.xlsx": ("2016-09-01", "2016-11-30", register(
                [release("NIC-12345-ABCDE-v1")], [purpose("NIC-12345-ABCDE-v1", text)])),
            "b.xlsx": ("2019-01-01", "2019-01-31", register(
                [release("DARS-NIC-12345-ABCDE-v1"), release("DARS-NIC-12345-ABCDE-v2")],
                [purpose("DARS-NIC-12345-ABCDE-v1", text), purpose("DARS-NIC-12345-ABCDE-v2", text, "A paper")])),
        }, skip=("old.xlsx",))
        self.summary = self.store.ingest()

    def record(self):
        return json.loads((self.store.path / "agreements" / "dars-nic-12345-abcde.json").read_text())

    def test_versions_and_periods(self):
        record = self.record()
        self.assertEqual([v["reference"] for v in record["versions"]],
                         ["DARS-NIC-12345-ABCDE-v1", "DARS-NIC-12345-ABCDE-v2"])
        self.assertEqual(record["versions"][0]["listed"], ["2016-09-01", "2019-01-01"])

    def test_text_kept_once(self):
        record = self.record()
        # One state for v1 across both files, and one copy of the shared objective.
        self.assertEqual(len(record["versions"][0]["states"]), 1)
        self.assertEqual(sorted(record["texts"].values()).count("Study asthma"), 1)

    def test_skipped_file_recorded(self):
        self.assertEqual([row["file"] for row in self.summary["skipped"]], ["old.xlsx"])
        self.assertEqual([row["file"] for row in self.summary["files"]], ["a.xlsx", "b.xlsx"])

    def test_changed_file_refused(self):
        (self.store.folder / "a.xlsx").write_bytes(b"not the same")
        with self.assertRaises(SystemExit):
            self.store.ingest()

    def test_view_leaves_out_held_versions(self):
        loaded = earlier.load(self.store.path)
        view = earlier.view(loaded["agreements"]["DARS-NIC-12345-ABCDE"], loaded["periods"],
                            {"DARS-NIC-12345-ABCDE-v2"})
        self.assertEqual(view["first_label"], "September to November 2016")
        self.assertEqual([v["reference"] for v in view["earlier_only"]], ["DARS-NIC-12345-ABCDE-v1"])
        self.assertEqual(view["earlier_only"][0]["texts"]["objective"], "Study asthma")

    def test_excluded(self):
        loaded = earlier.load(self.store.path, excluded=frozenset({"DARS-NIC-12345-ABCDE"}))
        self.assertEqual(loaded["agreements"], {})


class SiteTest(unittest.TestCase):
    """The earlier registers on a built site: a section on a known agreement, and pages of their own."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        with dataset_aliases():
            data = extract(workbook_bytes())
        known = data["agreements"][0]
        cls.known = known
        oldest = known["versions"][0]["reference"]
        cls.store = Store(root, {
            "a.xlsx": ("2017-03-01", "2017-05-31", register(
                [release(f"{known['base_reference']}-v0.1"), release(oldest),
                 release("NIC-99999-ZZZZZ-v1", organisation=known["organisation"].upper()),
                 release("NIC-88888-YYYYY-v1", organisation="GONE AWAY RESEARCH LTD")],
                [purpose(f"{known['base_reference']}-v0.1", "An earlier objective"),
                 purpose("NIC-99999-ZZZZZ-v1", "A finished study")])),
        })
        cls.store.ingest()
        cls.out = root / "site"
        with dataset_aliases(), mock.patch.object(earlier, "STORE", cls.store.path), mock.patch("builtins.print"):
            build.build(data, site_meta(), FIRST_EDITION, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def page(self, path):
        return (self.out / path / "index.html").read_text()

    def test_section_on_known_agreement(self):
        html = self.page(f"agreements/{self.known['slug']}")
        self.assertIn('id="earlier-registers"', html)
        self.assertIn(f"{self.known['base_reference']}-v0.1", html)
        self.assertIn("An earlier objective", html)
        self.assertIn("March to May 2017", html)

    def test_page_for_agreement_only_in_earlier_registers(self):
        html = self.page("agreements/dars-nic-99999-zzzzz")
        self.assertIn("Never in the Data Uses Register", html)
        self.assertIn("A finished study", html)
        self.assertIn("dars-nic-99999-zzzzz", self.page("agreements/earlier"))
        self.assertIn("/agreements/dars-nic-99999-zzzzz/", (self.out / "sitemap.xml").read_text())

    def test_dataset_page(self):
        datasets = {d["name"] for v in self.known["versions"] for d in v["datasets"]}
        self.assertIn("Other Data Set", datasets)
        html = self.page("datasets/other-data-set")
        self.assertIn('id="earlier-registers"', html)
        self.assertIn("dars-nic-99999-zzzzz", html)

    def test_organisation_page(self):
        html = self.page(f"organisations/{self.known['organisation_slug']}")
        self.assertIn("Only in the earlier registers (1)", html)
        self.assertIn("dars-nic-99999-zzzzz", html)

    def test_page_for_organisation_only_in_earlier_registers(self):
        html = self.page("organisations/gone-away-research-ltd")
        self.assertIn("Never in the Data Uses Register", html)
        self.assertIn("/agreements/dars-nic-88888-yyyyy/", html)
        self.assertIn('/datasets/other-data-set/', html)
        self.assertIn("/organisations/gone-away-research-ltd/", self.page("agreements/dars-nic-88888-yyyyy"))
        self.assertIn("/organisations/gone-away-research-ltd/", self.page("organisations"))
        self.assertIn("/organisations/gone-away-research-ltd/", (self.out / "sitemap.xml").read_text())

    def test_agreements_list_searchable(self):
        html = self.page("agreements")
        self.assertIn('id="earlier-table"', html)
        self.assertIn('data-search="DARS-NIC-99999-ZZZZZ', html)

    def test_about_page(self):
        self.assertIn('id="earlier-registers"', self.page("about"))


class NoStoreTest(unittest.TestCase):
    def test_site_without_store(self):
        with tempfile.TemporaryDirectory() as directory, dataset_aliases(), mock.patch("builtins.print"):
            out = Path(directory) / "site"
            build.build(extract(workbook_bytes()), site_meta(), FIRST_EDITION, out)
            self.assertFalse((out / "agreements" / "earlier").exists())
            self.assertNotIn('id="earlier-registers"', (out / "about" / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()


class SuccessorPageTest(unittest.TestCase):
    """An earlier-only agreement of a merged CCG is listed on its successor's page."""

    class Lineage:
        def node(self, name):
            return {"NHS OLD CCG": "ccg:01A"}.get(name)

        def successors(self, node):
            return {"ccg:01A": [("ccg:02B", "2018-04-01")], "ccg:02B": [("org:QWO", "2022-07-01")]}.get(node, [])

        def identity(self, node):
            return node

        def page_name(self, identity):
            return {"ccg:02B": "NHS Middle CCG", "org:QWO": "NHS New ICB"}[identity]

        def page(self, name):
            return None

    def test_first_successor_with_a_page(self):
        found = build.earlier_organisation_page("NHS OLD CCG", {"nhs-new-icb"}, {}, self.Lineage())
        self.assertEqual(found, ("nhs-new-icb", True))

    def test_own_page_first(self):
        found = build.earlier_organisation_page("NHS OLD CCG", {"nhs-old-ccg", "nhs-new-icb"}, {}, self.Lineage())
        self.assertEqual(found, ("nhs-old-ccg", False))

    def test_no_page(self):
        self.assertEqual(build.earlier_organisation_page("CTSU", {"nhs-new-icb"}, {}, self.Lineage()), ("", False))
