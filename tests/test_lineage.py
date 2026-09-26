import copy
import io
import json
import unittest
from unittest import mock

from pipeline import compare, lineage, ods, odscheck
from pipeline.names import display_name, strip_code

from .fixtures import ODS_CODES, ODS_WORLD


def world(codes=ODS_CODES, organisations=ODS_WORLD):
    return lineage.Lineage(list(codes), copy.deepcopy(organisations), {})


class Relations(unittest.TestCase):
    def setUp(self):
        self.lineage = world()

    def test_a_ccg_is_succeeded_by_its_icb_on_the_day_it_took_over(self):
        self.assertEqual(self.lineage.relation("NHS KENT AND MEDWAY CCG", "NHS KENT AND MEDWAY ICB - 91Q"),
                         (lineage.SUCCEEDED, "2022-07-01"))
        self.assertEqual(self.lineage.relation("NHS KENT AND MEDWAY CCG", "NHS KENT AND MEDWAY INTEGRATED CARE BOARD"),
                         (lineage.SUCCEEDED, "2022-07-01"))

    def test_a_sub_icb_location_and_its_icb_are_one_organisation(self):
        self.assertEqual(
            self.lineage.relation("NHS KENT AND MEDWAY ICB - 91Q", "NHS KENT AND MEDWAY INTEGRATED CARE BOARD"),
            (lineage.SAME, ""),
        )

    def test_ccgs_that_merged_before_2022_are_followed_through_to_the_icb(self):
        self.assertEqual(self.lineage.relation("NHS NORTH KIRKLEES CCG", "NHS KIRKLEES CCG"),
                         (lineage.SUCCEEDED, "2021-04-01"))
        self.assertEqual(self.lineage.relation("NHS NORTH KIRKLEES CCG", "NHS WEST YORKSHIRE ICB - X2C4Y"),
                         (lineage.SUCCEEDED, "2022-07-01"))

    def test_a_succession_recorded_only_on_the_later_record_still_counts(self):
        self.assertEqual(
            self.lineage.relation("NORTHERN DEVON HEALTHCARE NHS TRUST",
                                  "ROYAL DEVON UNIVERSITY HEALTHCARE NHS FOUNDATION TRUST"),
            (lineage.SUCCEEDED, "2022-04-01"),
        )

    def test_nothing_runs_backwards_or_between_strangers(self):
        self.assertIsNone(self.lineage.relation("NHS KENT AND MEDWAY ICB - 91Q", "NHS KENT AND MEDWAY CCG"))
        self.assertIsNone(self.lineage.relation("NHS KENT AND MEDWAY CCG", "NHS WEST YORKSHIRE ICB - X2C4Y"))
        self.assertIsNone(self.lineage.relation("NHS KENT AND MEDWAY CCG", "UNIVERSITY OF EXAMPLE"))

    def test_an_alias_spelling_finds_the_code_of_its_canonical_name(self):
        aliased = lineage.Lineage(list(ODS_CODES), copy.deepcopy(ODS_WORLD),
                                  {"royal devon and exeter nhs foundation trust":
                                   "ROYAL DEVON UNIVERSITY HEALTHCARE NHS FOUNDATION TRUST"})
        self.assertEqual(aliased.node("ROYAL DEVON AND EXETER NHS FOUNDATION TRUST"), "org:RH8")


class Pages(unittest.TestCase):
    def setUp(self):
        self.lineage = world()

    def test_every_name_for_an_icb_goes_to_one_page_named_as_ods_names_it(self):
        for name in ("NHS KENT AND MEDWAY ICB - 91Q", "NHS KENT AND MEDWAY INTEGRATED CARE BOARD"):
            self.assertEqual(self.lineage.page(name), "org:QKS")
        self.assertEqual(self.lineage.page_name("org:QKS"), "NHS KENT AND MEDWAY INTEGRATED CARE BOARD")

    def test_a_ccg_keeps_a_page_of_its_own_under_the_registers_name(self):
        self.assertEqual(self.lineage.page("NHS KENT AND MEDWAY CCG"), "ccg:91Q")
        self.assertEqual(self.lineage.page_name("ccg:91Q"), "NHS KENT AND MEDWAY CCG")

    def test_an_icb_lists_its_sub_icb_locations_with_the_ccg_each_continued(self):
        self.assertEqual(self.lineage.sub_icb_locations("org:QKS"),
                         [{"code": "91Q", "former": ["NHS KENT AND MEDWAY CCG"]}])

    def test_a_council_in_the_icbs_area_is_not_one_of_its_sub_icb_locations(self):
        codes = ODS_CODES + [{"name": "KENT COUNTY COUNCIL", "code": "886", "evidence": "test"}]
        organisations = {**ODS_WORLD, "886": {**ODS_WORLD["QKS"], "name": "KENT COUNTY COUNCIL", "icb": "QKS",
                                              "roles": [{"id": "RO141", "primary": True, "start": "", "end": ""}]}}
        self.assertEqual([r["code"] for r in world(codes, organisations).sub_icb_locations("org:QKS")], ["91Q"])
        self.assertEqual(world(codes, organisations).page("KENT COUNTY COUNCIL"), "org:886")

    def test_predecessors_and_successors_are_the_register_named_ones(self):
        self.assertEqual([p["name"] for p in self.lineage.predecessors("org:QWO")], ["NHS KIRKLEES CCG"])
        self.assertEqual(self.lineage.successors_of("ccg:91Q"),
                         [{"identity": "org:QKS", "name": "NHS KENT AND MEDWAY INTEGRATED CARE BOARD",
                           "date": "2022-07-01"}])

    def test_an_empty_lineage_knows_nothing(self):
        empty = lineage.Lineage([], {}, {})
        self.assertIsNone(empty.page("NHS KENT AND MEDWAY CCG"))
        self.assertIsNone(empty.relation("NHS KENT AND MEDWAY CCG", "NHS KENT AND MEDWAY ICB - 91Q"))


class Comparing(unittest.TestCase):
    def version(self, organisation="UNIVERSITY OF EXAMPLE", controllers=(), organisation_type="Academic"):
        return {"organisation": organisation, "organisation_type": organisation_type,
                "controllers": list(controllers), "datasets": []}

    def compare(self, before, after):
        return compare.compare_versions(before, after, {}, {}, world())

    def test_a_ccg_replaced_by_its_icb_is_a_succession_not_a_change(self):
        difference = self.compare(self.version(controllers=["NHS KENT AND MEDWAY CCG"]),
                                  self.version(controllers=["NHS KENT AND MEDWAY ICB - 91Q"]))
        self.assertEqual(difference["lists"], [])
        self.assertEqual(difference["succeeded"], [{"label": "Data controllers", "before": "NHS KENT AND MEDWAY CCG",
                                                    "after": "NHS KENT AND MEDWAY ICB - 91Q", "date": "2022-07-01"}])

    def test_several_ccgs_pair_with_their_own_sub_icb_locations(self):
        codes = ODS_CODES + [
            {"name": "NHS MEDWAY CCG", "code": "09W", "as": "CCG", "evidence": "test"},
            {"name": "NHS KENT AND MEDWAY ICB - 09W", "code": "09W", "evidence": "test"},
        ]
        organisations = {**ODS_WORLD, "09W": {**ODS_WORLD["91Q"], "name": "NHS KENT AND MEDWAY ICB - 09W"}}
        difference = compare.compare_versions(
            self.version(controllers=["NHS KENT AND MEDWAY CCG", "NHS MEDWAY CCG"]),
            self.version(controllers=["NHS KENT AND MEDWAY ICB - 91Q", "NHS KENT AND MEDWAY ICB - 09W"]),
            {}, {}, world(codes, organisations),
        )
        self.assertEqual(sorted((s["before"], s["after"]) for s in difference["succeeded"]), [
            ("NHS KENT AND MEDWAY CCG", "NHS KENT AND MEDWAY ICB - 91Q"),
            ("NHS MEDWAY CCG", "NHS KENT AND MEDWAY ICB - 09W"),
        ])

    def test_a_controller_with_no_predecessor_on_the_list_is_still_a_change(self):
        difference = self.compare(self.version(controllers=["NHS KENT AND MEDWAY CCG"]),
                                  self.version(controllers=["NHS KENT AND MEDWAY ICB - 91Q",
                                                            "NHS WEST YORKSHIRE ICB - X2C4Y"]))
        self.assertEqual(difference["lists"], [{"label": "Data controllers",
                                                "added": ["NHS WEST YORKSHIRE ICB - X2C4Y"], "removed": []}])

    def test_the_applicants_type_changes_with_it_and_is_not_a_second_change(self):
        difference = self.compare(
            self.version("NHS KENT AND MEDWAY CCG", organisation_type="CCG"),
            self.version("NHS KENT AND MEDWAY ICB - 91Q", organisation_type="ICB"),
        )
        self.assertEqual(difference["scalars"], [])
        self.assertEqual([s["label"] for s in difference["succeeded"]], ["Applicant organisation", "Organisation type"])

    def test_an_icb_named_by_a_sub_icb_location_then_by_itself_is_a_rename(self):
        difference = self.compare(self.version(controllers=["NHS KENT AND MEDWAY ICB - 91Q"]),
                                  self.version(controllers=["NHS KENT AND MEDWAY INTEGRATED CARE BOARD"]))
        self.assertEqual([r["label"] for r in difference["renamed"]], ["Data controllers"])
        self.assertEqual(difference["lists"], [])


class Names(unittest.TestCase):
    def test_codes_are_dropped_from_displayed_names(self):
        self.assertEqual(strip_code("NHS KENT AND MEDWAY ICB - 91Q"), "NHS KENT AND MEDWAY ICB")
        self.assertEqual(display_name("NHS ENGLAND - X26"), "NHS England")
        self.assertEqual(display_name("NHS Bristol, North Somerset and South Gloucestershire ICB - 15C"),
                         "NHS Bristol, North Somerset and South Gloucestershire ICB")

    def test_a_dash_before_words_is_not_a_code(self):
        self.assertEqual(strip_code("SAVING FACES - THE FACIAL SURGERY RESEARCH FOUNDATION"),
                         "SAVING FACES - THE FACIAL SURGERY RESEARCH FOUNDATION")


# Recorded from the ORD API, trimmed to the fields `ods.trim` reads.
ORD_91Q = {"Organisation": {
    "Name": "NHS KENT AND MEDWAY ICB - 91Q", "Status": "Active",
    "Date": [{"Type": "Operational", "Start": "2019-10-23"}, {"Type": "Legal", "Start": "2020-04-01"}],
    "Roles": {"Role": [
        {"id": "RO98", "primaryRole": True, "Date": [{"Type": "Legal", "Start": "2020-04-01"}], "Status": "Active"},
        {"id": "RO319", "Date": [{"Type": "Operational", "Start": "2022-07-01"}], "Status": "Active"},
    ]},
    "Rels": {"Rel": [{"id": "RE5", "Status": "Active", "Target": {"OrgId": {"extension": "QKS"},
                                                                   "PrimaryRoleId": {"id": "RO261"}}}]},
    "Succs": {"Succ": [{"Type": "Predecessor", "Date": [{"Type": "Legal", "Start": "2020-04-01"}],
                        "Target": {"OrgId": {"extension": "10E"}, "PrimaryRoleId": {"id": "RO98"}}}]},
}}


class OdsRecords(unittest.TestCase):
    def test_a_record_is_trimmed_to_what_the_site_uses(self):
        record = ods.trim(ORD_91Q)
        self.assertEqual(record["name"], "NHS KENT AND MEDWAY ICB - 91Q")
        self.assertEqual(record["start"], "2020-04-01")  # legal, not operational
        self.assertEqual(record["icb"], "QKS")
        self.assertEqual([r["id"] for r in record["roles"]], ["RO98", "RO319"])
        self.assertEqual(record["predecessors"], [{"type": "predecessor", "code": "10E", "date": "2020-04-01"}])

    def test_gathering_follows_links_and_fetches_each_code_once(self):
        asked = []

        def fetch(code):
            asked.append(code)
            return copy.deepcopy(ODS_WORLD.get(code))

        held = ods.gather(["03J"], fetcher=fetch)
        self.assertEqual(set(held), {"03J", "X2C4Y", "QWO"})
        self.assertEqual(sorted(asked), sorted(set(asked)))

    def test_a_search_keeps_only_organisations_with_exactly_the_name(self):
        reply = {"Organisations": [
            {"OrgId": "211", "Name": "KIRKLEES COUNCIL", "Status": "Active", "OrgRecordClass": "RC1", "PrimaryRoleId": "RO141"},
            {"OrgId": "211AA", "Name": "KIRKLEES COUNCIL HQ", "Status": "Active", "OrgRecordClass": "RC2", "PrimaryRoleId": "RO"},
        ]}
        with mock.patch.object(ods, "_get", return_value=reply):
            self.assertEqual([o["code"] for o in ods.search("Kirklees  Council")], ["211"])


class Proposing(unittest.TestCase):
    def propose(self, names, swaps=(), kept=(), searches=None):
        searches = searches or {}
        return odscheck.propose(
            names, dict(swaps), list(kept),
            fetch=lambda code: copy.deepcopy(ODS_WORLD.get(code)),
            search=lambda name: searches.get(name, []),
            report=lambda *_: None,
        )

    def test_a_code_in_the_name_is_used_when_ods_knows_it(self):
        entries, _ = self.propose(["NHS KENT AND MEDWAY ICB - 91Q", "NHS NOWHERE ICB - ZZ9"])
        self.assertEqual([(e["name"], e["code"]) for e in entries], [("NHS KENT AND MEDWAY ICB - 91Q", "91Q")])

    def test_an_exact_current_name_is_a_match_and_an_old_ccg_is_marked(self):
        entries, _ = self.propose(["NHS NORTH KIRKLEES CCG"], searches={
            "NHS NORTH KIRKLEES CCG": [{"code": "03J", "name": "NHS NORTH KIRKLEES CCG", "status": "Inactive", "role": "RO98"}],
        })
        self.assertEqual(entries[0]["code"], "03J")
        self.assertEqual(entries[0]["as"], "CCG")

    def test_a_ccg_name_on_a_record_that_is_not_a_ccg_is_not_a_match(self):
        # ODS has prescribing records named after old CCGs.
        entries, _ = self.propose(
            ["NHS KENT AND MEDWAY CCG", "NHS KENT AND MEDWAY ICB - 91Q"],
            swaps={("NHS KENT AND MEDWAY CCG", "NHS KENT AND MEDWAY ICB - 91Q"): 3},
            searches={"NHS KENT AND MEDWAY CCG": [
                {"code": "Y04158", "name": "NHS KENT AND MEDWAY CCG", "status": "Active", "role": "RO177"}]},
        )
        ccg = next(e for e in entries if e["name"] == "NHS KENT AND MEDWAY CCG")
        self.assertEqual((ccg["code"], ccg["as"]), ("91Q", "CCG"))

    def test_a_ccg_gets_the_code_of_the_name_that_replaced_it(self):
        entries, _ = self.propose(
            ["NHS KENT AND MEDWAY CCG", "NHS KENT AND MEDWAY ICB - 91Q"],
            swaps={("NHS KENT AND MEDWAY CCG", "NHS KENT AND MEDWAY ICB - 91Q"): 20},
        )
        ccg = next(e for e in entries if e["name"] == "NHS KENT AND MEDWAY CCG")
        self.assertEqual((ccg["code"], ccg["as"]), ("91Q", "CCG"))
        self.assertIn("20 versions", ccg["evidence"])

    def test_a_reviewed_entry_is_kept_and_unmatched_nhs_names_are_listed(self):
        kept = [{"name": "NHS DIGITAL", "code": "X26", "evidence": "reviewed: test"}]
        entries, for_review = self.propose(["NHS DIGITAL", "NHS SOMEWHERE TRUST", "UNIVERSITY OF EXAMPLE"], kept=kept)
        self.assertEqual([e["name"] for e in entries], ["NHS DIGITAL"])
        self.assertEqual(for_review, ["NHS SOMEWHERE TRUST"])
