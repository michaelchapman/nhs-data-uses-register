import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import build, relations
from pipeline.extract import extract

from .fixtures import FIRST_EDITION, dataset_aliases, site_meta, workbook_bytes

CONFIG = {
    "groups": [{"name": "Acme", "members": ["acme-uk", "acme-inc", "acme-labs"], "reason": "One group."}],
    "hosted": [{"body": "unit", "host": "trust", "reason": "Hosted."}],
    "joint": [{"body": "school", "parents": ["hull", "york"], "reason": "Joint."}],
    "merged": [{"from": "old", "into": "new", "year": "2024", "reason": "Merged."}],
}


def text(line):
    return "".join(value if kind == "text" else f"[{value}]" for kind, value in line)


class Lines(unittest.TestCase):
    def setUp(self):
        self.lines = {slug: [text(line) for line in lines] for slug, lines in relations.lines(CONFIG).items()}

    def test_a_group_member_names_the_others(self):
        self.assertEqual(self.lines["acme-uk"], ["In the Acme group of companies, with [acme-inc] and [acme-labs]."])

    def test_hosting_is_said_from_both_sides(self):
        self.assertEqual(self.lines["unit"], ["Hosted by [trust]."])
        self.assertEqual(self.lines["trust"], ["Hosts [unit]."])

    def test_a_joint_body_and_each_parent(self):
        self.assertEqual(self.lines["school"], ["Run jointly by [hull] and [york]."])
        self.assertEqual(self.lines["hull"], ["Runs [school] jointly with [york]."])

    def test_a_merger_is_said_from_both_sides(self):
        self.assertEqual(self.lines["old"], ["Merged into [new] in 2024."])
        self.assertEqual(self.lines["new"], ["Formed in part from [old], which merged into it in 2024."])

    def test_unknown_lists_slugs_with_no_page(self):
        pages = {"acme-uk", "acme-inc", "acme-labs", "unit", "trust", "school", "hull", "york", "new"}
        self.assertEqual(relations.unknown(CONFIG, pages), ["old"])


class OnThePage(unittest.TestCase):
    def test_an_organisation_page_links_its_related_organisations(self):
        config = {"hosted": [{"body": "other-trust", "host": "university-of-example", "reason": "Test."}]}
        with tempfile.TemporaryDirectory() as directory, dataset_aliases():
            path = Path(directory) / "relations.json"
            path.write_text(json.dumps(config))
            out = Path(directory) / "site"
            with mock.patch.object(relations, "PATH", path):
                build.build(extract(workbook_bytes()), site_meta(), FIRST_EDITION, out)
            host = (out / "organisations" / "university-of-example" / "index.html").read_text()
            body = (out / "organisations" / "other-trust" / "index.html").read_text()
            unrelated = (out / "organisations" / "nhs-bristol-north-somerset-and-south-gloucestershire-icb-15c" / "index.html").read_text()
        self.assertIn('<li>Hosts <a href="/organisations/other-trust/">Other Trust</a>.</li>', host)
        self.assertIn('<li>Hosted by <a href="/organisations/university-of-example/">University of Example</a>.</li>', body)
        self.assertNotIn("Related organisations", unrelated)
