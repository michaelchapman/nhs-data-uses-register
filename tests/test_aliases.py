import json
import tempfile
import unittest
from pathlib import Path

from pipeline import aliases, orgcheck

FIRST = "COVID-19 Second Generation Surveillance System"
SECOND = "COVID-19 Second Generation Surveillance System (SGSS)"
THIRD = "COVID-19 SGSS First Positives (Second Generation Surveillance System)"

# SGSS as the alias file used to hold it: two renames, the second group's
# variant the first group's canonical.
CHAINED = [
    {"canonical": SECOND, "variants": [FIRST, SECOND]},
    {"canonical": THIRD, "variants": [THIRD, SECOND]},
]


class MapOf(unittest.TestCase):
    def test_a_name_renamed_twice_resolves_to_the_end_of_the_chain(self):
        mapping = aliases.map_of(CHAINED)
        for name in (FIRST, SECOND, THIRD):
            self.assertEqual(aliases.resolve(name, mapping), THIRD)

    def test_the_order_of_the_groups_does_not_matter(self):
        mapping = aliases.map_of(list(reversed(CHAINED)))
        self.assertEqual(aliases.resolve(FIRST, mapping), THIRD)

    def test_a_loop_is_refused(self):
        groups = [{"canonical": "A", "variants": ["B"]}, {"canonical": "B", "variants": ["A"]}]
        with self.assertRaisesRegex(ValueError, "alias loop"):
            aliases.map_of(groups)

    def test_a_spelling_differing_from_the_canonical_only_in_case_is_not_asked_about_again(self):
        mapping = aliases.map_of([{"canonical": "Results (Pillar 2)", "variants": ["Results (pillar 2)"]}])
        self.assertTrue(orgcheck.already_resolved(["Results (pillar 2)", "Results (Pillar 2)"], mapping))
        self.assertFalse(orgcheck.already_resolved(["Results (Pillar 2)", "Results (Pillar 3)"], mapping))

    def test_an_unaliased_name_is_unchanged(self):
        self.assertEqual(aliases.resolve("Other Data Set", aliases.map_of(CHAINED)), "Other Data Set")


class AddAlias(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "dataset-aliases.json"

    def groups(self):
        return json.loads(self.path.read_text())["aliases"]

    def test_a_rename_of_a_merged_name_joins_its_group(self):
        aliases.add_alias(SECOND, [FIRST, SECOND], "first rename", path=self.path)
        # The second rename is found as SECOND -> THIRD, and merged onto SECOND.
        aliases.add_alias(SECOND, [SECOND, THIRD], "second rename", path=self.path)
        [group] = self.groups()
        self.assertEqual(group["canonical"], SECOND)
        self.assertEqual({*group["variants"]}, {FIRST, SECOND, THIRD})

    def test_a_canonical_that_is_already_a_variant_joins_that_group(self):
        aliases.add_alias(THIRD, [SECOND, THIRD], path=self.path)
        aliases.add_alias(SECOND, [FIRST], path=self.path)
        [group] = self.groups()
        self.assertEqual(group["canonical"], THIRD)
        self.assertIn(FIRST, group["variants"])

    def test_a_group_named_as_a_variant_is_folded_in_with_its_reason(self):
        aliases.add_alias(SECOND, [FIRST, SECOND], "January", path=self.path)
        aliases.add_alias(THIRD, [THIRD], "April", path=self.path)
        aliases.add_alias(THIRD, [SECOND], path=self.path)
        [group] = self.groups()
        self.assertEqual(group["canonical"], THIRD)
        self.assertEqual({*group["variants"]}, {FIRST, SECOND, THIRD})
        self.assertEqual(group["reason"], "April; January")


if __name__ == "__main__":
    unittest.main()
