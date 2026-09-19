# Reviewing and merging organisation names

The register records an organisation's name as free text on every row it
appears on. The same real organisation sometimes gets recorded under more
than one spelling — a shortened ICB name, a trailing "Limited" dropped, a
comma moved — and each spelling gets its own organisation page unless someone
tells the site otherwise.

Two organisations with genuinely similar names are not the same thing (two
different NHS trusts, two different councils), so nothing is merged
automatically. A merge only happens because a person looked at a candidate
and added it to `data/organisation-aliases.json`.

## The workflow

1. **Find candidates.**

   ```bash
   .venv/bin/python -m pipeline.orgcheck
   ```

   Prints two groups:

   - **Same trailing reference code** (an ICB's "- M1J4Y", say) — near-certain.
     The reference code is the statutory identifier; two names ending in the
     same one are the same body under different amounts of its name.
   - **Weighted name similarity** — needs a person to look. This is
     deliberately noisy. It's ranked so that a word most organisations share
     (TRUST, COUNCIL, NHS, INTEGRATED CARE BOARD) counts for very little and a
     word only two names share (a place, a company) counts for a lot, but it
     still surfaces genuinely different organisations that happen to share
     a lot of boilerplate — two different metropolitan borough councils, two
     different ambulance trusts. Expect most of this group to be "no", not
     "yes".

2. **Decide, for each candidate.** Ask: is this the same legal entity
   recorded inconsistently, or two different organisations that happen to
   look similar? When in doubt, leave it — an unmerged near-duplicate is a
   cosmetic inconvenience; a wrong merge attributes one organisation's data
   sharing to another.

3. **Record a confirmed merge** in `data/organisation-aliases.json`:

   ```json
   {
     "aliases": [
       {
         "canonical": "NHS Bedfordshire, Luton and Milton Keynes ICB - M1J4Y",
         "variants": ["Luton and Milton Keynes ICB - M1J4Y"],
         "reason": "Same ICB reference code (M1J4Y) recorded under a shorter name on some agreement rows."
       }
     ]
   }
   ```

   `canonical` is what the organisation page shows. `variants` is every other
   spelling seen in the register that should land on that page — matching
   ignores case and extra whitespace, but not wording, so list each spelling
   that actually occurs (`orgcheck`'s output can be pasted straight in). A
   short `reason` is for the next person reading the file, yourself included
   in six months.

4. **Rebuild and check.**

   ```bash
   .venv/bin/python -m pipeline.run
   ```

   No re-ingest needed — aliases are applied fresh on every build, so editing
   this file and rebuilding is enough to see the result. Open the merged
   organisation's page: it lists every raw spelling it was recorded under
   under "Also recorded in the register as", linking back to this file, so
   the merge is always checkable against what the register actually says.
   Agreement pages are never affected — they always show the applicant name
   exactly as that row recorded it; only which organisation page it links to
   changes.

5. **Commit it,** with the reason in the commit message too if it's not
   obvious from the file.

## What this does and doesn't do

- It only affects the **organisation** field (the applicant, and the data
  controller cross-reference on organisation pages) — never agreement titles,
  dataset names, or any other free text from the register.
- It's forward and backward compatible with the committed edition store: an
  alias applies to every edition rebuilt after it's added, not just the one
  ingested at the time.
- It does not edit or correct the register itself, and doesn't claim to —
  this site is a mirror (see the About page's caveats). It only decides which
  of this site's own pages a name's agreements appear on.
