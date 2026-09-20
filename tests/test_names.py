import unittest

from pipeline import facts
from pipeline.names import display_name


class DisplayName(unittest.TestCase):
    def check(self, raw, shown):
        self.assertEqual(display_name(raw), shown)

    def test_ordinary_names(self):
        self.check("UNIVERSITY OF OXFORD", "University of Oxford")
        self.check("LONDON BOROUGH OF HAMMERSMITH & FULHAM", "London Borough of Hammersmith & Fulham")

    def test_acronyms_and_codes_stay_in_capitals(self):
        self.check("NHS BEDFORDSHIRE, LUTON AND MILTON KEYNES ICB - M1J4Y",
                   "NHS Bedfordshire, Luton and Milton Keynes ICB - M1J4Y")
        self.check("CARE QUALITY COMMISSION (CQC)", "Care Quality Commission (CQC)")
        self.check("3M UNITED KINGDOM PLC", "3M United Kingdom PLC")

    def test_apostrophes(self):
        self.check("ST GEORGE'S HOSPITAL MEDICAL SCHOOL", "St George's Hospital Medical School")
        self.check("ST GEORGE’S, UNIVERSITY OF LONDON", "St George’s, University of London")
        self.check("GUY'S AND ST THOMAS' NHS FOUNDATION TRUST", "Guy's and St Thomas' NHS Foundation Trust")
        self.check("O'BRIEN INSTITUTE", "O'Brien Institute")

    def test_hyphenated_places_keep_their_small_words(self):
        self.check("STOKE-ON-TRENT CITY COUNCIL", "Stoke-on-Trent City Council")
        self.check("KINGSTON UPON HULL CITY COUNCIL", "Kingston upon Hull City Council")

    def test_mc_prefix_and_company_forms(self):
        self.check("MCKINSEY & COMPANY, INC. UNITED KINGDOM", "McKinsey & Company, Inc. United Kingdom")
        self.check("SOMETHING GMBH", "Something GmbH")
        self.check("MEDICAGO R&D INCORPORATED", "Medicago R&D Incorporated")
        self.check("CRISTAL HEALTH LTD T/A AKRIVIA HEALTH", "Cristal Health Ltd T/A Akrivia Health")

    def test_a_phrase_after_a_dash_or_bracket_starts_with_a_capital(self):
        self.check("SAVING FACES - THE FACIAL SURGERY RESEARCH FOUNDATION",
                   "Saving Faces - The Facial Surgery Research Foundation")
        self.check("QUALITY BY RANDOMIZATION LIMITED (TRADING AS PROTAS)",
                   "Quality by Randomization Limited (Trading as Protas)")

    def test_brand_names_with_capitals_of_their_own(self):
        self.check("ASTRAZENECA UK LIMITED", "AstraZeneca UK Limited")
        self.check("GLAXOSMITHKLINE RESEARCH & DEVELOPMENT LIMITED", "GlaxoSmithKline Research & Development Limited")

    def test_a_name_someone_capitalised_is_left_alone(self):
        for name in ("NHS Bristol, North Somerset and South Gloucestershire ICB - 15C",
                     "University of Oxford", "McKinsey"):
            self.check(name, name)

    def test_empty_and_symbol_only_names_pass_through(self):
        self.check("", "")
        self.check("---", "---")


class OverTheRealRegister(unittest.TestCase):
    """A safety net rather than a specification: whatever the register holds."""

    @classmethod
    def setUpClass(cls):
        register = facts.latest_edition("data-uses-register")
        data = facts.read_extract("data-uses-register", register)
        cls.names = {o["name"] for o in data["organisations"]} | {
            a["organisation"] for a in data["agreements"]
        } | {c for a in data["agreements"] for c in a["controllers"]}

    def test_only_capitalisation_ever_changes(self):
        for name in self.names:
            self.assertEqual(display_name(name).lower(), name.lower(), name)

    def test_it_is_idempotent(self):
        for name in self.names:
            once = display_name(name)
            self.assertEqual(display_name(once), once, name)

    def test_no_shouting_survives_in_a_multi_word_name(self):
        # A multi-word name still wholly in capitals means a word slipped through.
        # Acronyms are fine: this only checks the name isn't entirely upper-case.
        for name in self.names:
            shown = display_name(name)
            if len(shown.split()) > 2 and any(c.isalpha() for c in shown):
                self.assertNotEqual(shown, shown.upper(), name)


if __name__ == "__main__":
    unittest.main()
