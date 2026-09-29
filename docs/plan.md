# Plan: what is left to do

The single list of outstanding work. The earlier plans (the facts store, the
local edition archive, version diffs, release coverage and NHS organisation
changes) are finished or folded in here, and their reasoning is kept in the git
history. What still governs the site lives in three places: the
[README](../README.md), the monthly routine in
[manual-updates.md](manual-updates.md), and the name rules in
[organisation-names.md](organisation-names.md).

**What the site is for.** It takes the Data Uses Registers NHS England
publishes and reproducibly reformats them into pages that are easier to read,
search, link to and cite. It is a presentation of the register, not a new
dataset: there is no expectation that it publishes the reformatted data, so a
proposal to add a data download starts from that rule. See
[section 6](#6-considered-and-not-planned).

Last reviewed 2026-09-29. Each item has an issue. In rough order of value:

1. [Release views](#1-release-views) (#47)
2. [Dataset pages](#2-dataset-pages) (#56, #57)
3. [Amendments on the changes page](#3-amendments-on-the-changes-page) (#48)
4. [Checking workbooks before a re-parse](#4-checking-workbooks-before-a-re-parse) (#49)
5. [Waiting on people](#5-waiting-on-people) (#50, #51, #55)
6. [Considered and not planned](#6-considered-and-not-planned)

Ideas raised as issues and not yet scoped here: a glossary of the register's
terms (#27), and trends over time with a feed of what changed (#28).
[Built](#built) keeps the reasoning of finished work that still decides how
the site behaves.

## 1. Release views

Issue #47.

The facts store holds every file released, 104,451 rows from April 2016, one
per file with its month and opt-out flag. The site shows them only summarised
by dataset. All of the following are build-time work; nothing in the store
needs to change.

To build, in this order:

1. **A release check** at build time: files released per agreement, dataset
   and month, checked against the per-dataset totals the pages show. Nothing is
   published; the next two steps rest on it.
2. **A release timeline on each agreement page**: files per month, by dataset.
3. **A register-wide monthly chart** of files released.
4. **Last, a "no files recorded" line and filter** on the agreements list. It
   is the view most easily misread, so it waits for the wording below to be in
   place on the other three.

### What release data can and cannot say

These rules hold for every release view, and the pages that exist already
follow them.

**The claim not to make.** Of 1,950 agreements in the September 2026 edition,
983 have had files released, 651 expired with none recorded, 257 have run over
a year with none, and 59 are too recent to tell. "Half of these agreements
never resulted in any data being shared" is false. A release row records a
file released externally by DARS, which is one of several ways data reaches an
applicant. The DARS team confirmed that position in September 2026: the
release sheet does not cover system access, such as access granted in NHS
England's own Secure Data Environment and its predecessors.

**Out of scope, and so never implied:**

- access granted in NHS England's own systems;
- onward sharing by a recipient. 91 of 1,950 agreements permit sublicensing,
  and nothing downstream of them is recorded;
- NHS England's internal flows from 1 February 2023, which left this register
  at the NHS Digital merger (`sources.MERGER_EDITION`);
- releases published in NHS England's other registers (internal uses, National
  Back Office, NDRS, the ONS register for the Public Health Research Database,
  COVID-19 non-DARS), and the Data Sharing Framework Contracts above individual
  agreements.

**Wording:**

- "No files recorded as released under this agreement", never wording that
  says data was not shared.
- Every release view says it covers files released externally by DARS, and
  links to the About page's caveat (`_release-scope.html` does this).
- Release history runs from April 2016 and change history from July 2021. They
  are never described as one span.
- A sublicensing agreement's releases say onward sharing is permitted and not
  recorded here.
- The February 2023 departures are labelled wherever agreements leaving the
  register are counted.

The store keeps each release under a `channel`, today always `"file"`, so a
second kind of release from another source could sit beside these rather than
be merged into them.

### What the release data allows

Measured on 2026-09-29, from the store and the September 2026 edition.

- **Count an edition's files, not the store's rows.** The store holds 145,325
  rows for 104,872 distinct files, because a relabelled dataset's files are
  recorded again under the new name. Read through `read_edition`, September
  2026 reports 104,451. A register-wide count must come from one edition's view,
  as every page does now.
- **Recent months are complete.** 99% of files first appear in the edition
  published the month after they were released, so an edition's last month
  (August for the September edition) can be shown as final. A month is never
  counted before its first edition exists.
- **The years before 2019 are thin, and not because of departures.** September
  2026 lists 206 files released in 2016, 541 in 2017 and 980 in 2018, then
  7,684 in 2019; the July 2021 edition already had 206, 543 and 980. A chart
  starting in April 2016 would read as data sharing rising eightfold in 2019.
  Why the register's early years are sparse is a question for the DARS team
  (below); until it is answered the chart either starts in 2019 or marks
  2016–2018 as partial coverage.
- **Agreements differ by orders of magnitude.** Of the 983 agreements with files,
  the median has files in 3 months across 3 datasets, 247 in a single month; the
  largest span 93 months and 26 datasets, and one agreement has 4,912 files. A
  timeline has to read at both ends. Each version's `releases` already holds a
  `months` count per dataset, so the data for an agreement timeline is in hand.
- **Pages have room, with care.** The median agreement page is 58 KB; the largest
  is 1.3 MB. An inline SVG row per dataset adds a few KB; a table of every month
  would not fit the largest.
- **Step 4 is partly built.** The agreements list's opt-outs filter already has a
  "No files recorded" option (967 agreements), from `privacy.py`. What is left
  is the wording rules above applied to it, and whether it becomes its own
  filter.

## 2. Dataset pages

Merging renamed datasets and titling each page with the register's current
name were built in #54 (see [Built](#dataset-names)). Two parts of #25 need
hand-written data, and so a person to check it:

- **Related datasets** (#56): successors and versions that stay separate
  pages, such as MHMDS → MHLDDS → MHSDS and IAPT v1.5 → v2, in a
  `data/dataset-relations.json` shaped like the organisation relations file.
- **Descriptions** (#57): a sentence or two and a link to NHS England's page
  for each dataset, starting with the 20 most-named, which cover 79% of
  agreements.

A release timeline on each dataset page belongs with the release views above
(#47).

## 3. Amendments on the changes page

Issue #48. Every amendment now shows what changed, and register-wide edits are
reported once. Two smaller things were proposed and not done:

- lead the changes page with what an in-place amendment is: an edit NHS England
  made to an existing record without a new version number, for which there is
  no official changelog. That is the site's own contribution and it sits
  second, under "Added";
- make an agreement's "Amended this month" tag link to the change on its
  timeline.

## 4. Checking workbooks before a re-parse

Issue #49. The manifest records each ingested workbook's SHA-256. A `--verify`
flag on `ingest` that checks the files in `data/raw/` against it would catch a
wrong or corrupted download before a 70-minute re-parse, not during one. It
matters only when a re-parse is needed, which is rare.

## 5. Waiting on people

The decisions below are tracked in #51, and the dataset names in #55. One more waits on a design choice
rather than a person outside the project (#50): the headings inside folded
sections, such as an agreement's purpose sections, sit in a `<summary>`, and
some screen readers do not announce them as headings. The fix is either the
heading above the section, the sections left open, or the markup as it is.

- **Organisation names.** Two possible renames need someone who knows the
  companies: LA-SER Europe to Certara UK, and 2020 Delivery to The Public
  Service Consultants. They are listed, with the other decisions, in
  [organisation-names.md](organisation-names.md#waiting-for-a-decision).
  `odscheck` also lists NHS-looking names with no ODS code on every run: NHS
  England's regional offices before they were merged, and Welsh and Scottish
  bodies ODS does not hold usefully (NHS Lothian, NHS Wales Informatics
  Service).
- **Questions for the DARS team.** Why the latest versions of the UCL (MR623)
  and University of Bristol (Learning Disabilities Mortality Review) agreements
  left the register in February 2023, when the other four agreements that lost
  versions then were NHS England's own. Whether any test record other than
  DARS-NIC-401994-D5Q7S reached a published workbook. And why the release
  sheet lists so few files before 2019 (1,727 across 2016–2018, against 7,684
  in 2019 alone), which decides where a chart of files released can start.
- **Dataset names** (#55). Whether "Maternity Services Data Set" (180
  agreements, no files recorded) and "Maternity Services Data Set (MSDS) v1.5"
  (31) are one dataset, and "Alcohol Dependence" and "Alcohol Dependency
  Dataset" likewise. Both pairs are in use in the same edition, so
  `datasetcheck` cannot decide them.
- **The ODS licence.** The site credits ODS under the Open Government Licence
  v3.0. That could not be checked against ODS's own pages from the build
  environment, which digital.nhs.uk refuses. It is worth confirming once.

## 6. Considered and not planned

- **Filters on sensitivity, legal basis for provision and type of data** (#23).
  Deferred, not rejected: #23 built the two questions that mattered most,
  confidential data and patient opt-outs (`pipeline/privacy.py`). Legal basis
  records NHS England's power to release, and 1,887 of 1,950 agreements cite
  the Health and Social Care Act 2012 s261, so a filter on it separates almost
  nothing; its consent and s251 values would also sit beside the confidential
  data filter's, meaning something different. If it is added, group it by
  statute and tidy the dash and quote variants first.

- **CSV extracts of the register.** Published until 2026-09-27, then removed.
  They were one edition's three sheets as CSV, which the register's own
  workbook already provides, and carried none of what the site adds: merged
  names, successions, status or change history. Extending them (#26) meant a
  41 MB file of purpose text. The downloads page, kept at its address but out
  of the menu, points to the workbook and to the facts store.
- **A CSV of the site's own reading of the agreements.** Built on 2026-09-29
  and taken out the same day: one row per agreement with the merged
  organisation pages, sectors, status, confidential data bases and opt-outs
  the site works out, and no purpose text. It is a reformatted dataset, which
  the site does not set out to publish (see the top of this plan). It may be
  revisited; the code is in the git history (`pipeline/export.py`).
- **Change downloads.** `downloads/changes.csv`, one row per change across every
  edition held (edition, previous edition, reference, base reference,
  organisation, kind, the fields changed and the agreement's URL), and
  `downloads/changes.json`, the same with the old and new values, word edits
  and the source of each succession. No single workbook holds the change
  history, and it is computed at build time, so publishing it would be cheap.
  Not planned all the same: it is a reformatted dataset, which the site does
  not set out to publish (see the top of this plan). The changes pages show
  that history.
- **An amendment log for prose.** Proposed to show old and new text between
  editions. Unnecessary: the facts store keeps every edition's text, so the
  site shows prose redlines already.
- **Paging the changes pages.** December 2022 was 1,192 rows. As one
  register-wide edit it is one row and a collapsed list, and the largest page is
  now 370 KB.
- **Holding the facts store in memory** to shorten the build further. The
  build reads each agreement's file twice, once for the edition it shows and
  once for every edition's changes and timeline (`changes.every_edition`), in
  about 28 seconds. Reading one agreement at a time keeps peak memory near
  650 MB, which matters more.

## Built

### Dataset names

Part of #25, built in #54 in September 2026. The register relabels datasets,
and three things followed from how the site had handled it:

- **Renames in two steps.** SGSS and MHCYP were each renamed twice and
  recorded as two alias groups, and a name was resolved only one step, so the
  January 2023 changes page showed 97 dataset removals that were a rename.
  Every name now resolves to the end of its chain, a loop is refused, and a new
  rename joins the group its old name is in.
- **Titles.** An alias group's canonical name was the longest spelling, which
  titled 15 pages with names the register had dropped. The canonical name now
  makes only the page's address, which outlasts renames; the page is titled
  with the spelling its agreements' latest versions use most, and lists the
  others.
- **Finding renames.** `datasetcheck` read every workbook from `data/raw/`,
  which exists only where they were downloaded, and was not in the monthly
  routine. It now reads the store in seconds, is step 4 of the routine, and
  warns in CI.

It cannot decide two names that are both in use in one edition; those go to a
person (#55).

### Searching the purpose text

Issue #21, built in September 2026. What follows was the plan, kept because its
measurements still decide how a search matches words. When it was written, the
search on the agreements list matched the title, reference, organisation and
dataset names, never the objective, activities, outputs and benefits, which
are where an agreement's subject is. Measured on the September 2026 edition:

| Search | Matches today | With the purpose text |
| --- | ---: | ---: |
| dementia | 10 | 123 |
| pharmaceutical | 0 | 209 |
| police | 0 | 167 |
| insurance | 0 | 27 |
| machine learning | 3 | 59 |

#### What the measurements rule out

- **Putting the text in the page.** The latest versions' prose is 41 MB, a
  median of 21,000 characters an agreement. Even reduced to each agreement's
  distinct words it would add 2.6 MB gzipped to an agreements page that is
  223 KB today, and the HES APC dataset page would gain 1.3 MB.
- **Matching substrings, as the search does now.** Across that much text,
  short searches match everything: "ai" is in 1,942 of 1,950 agreements
  ("maintain", "detail"), "hiv" in 744 ("archive"), "art" in 1,926. Searches
  must match words: a whole word under four letters ("ai" 37, "hiv" 18), and
  the start of a word from four letters, so "pharma" finds 525 and "diabet"
  537.
- **Adding "s" to every short word.** Whole-word matching would miss "GPs"
  when someone searches "GP", but letting any short word also match itself
  plus "s" takes "ha" from 8 agreements to 1,871 ("has"), "doe" from 1 to 874
  ("does") and "los" (length of stay) from 16 to 137 ("loss"). The plurals
  worth matching are acronyms, and the text shows which those are: they are
  written in capitals with a lower-case "s".
- **Earlier versions' text.** The page shows the latest version, and a match
  only in superseded text could not be seen on it: "marketing" is in 106
  latest versions and 248 including earlier ones.

#### What was built

All four steps (`pipeline/search.py`, `assets/filter.js`,
`assets/highlight.js`).

1. **An index built with the site**, one JSON file per first character of the
   word (36 files, 927 KB gzipped in all, a median of 19 KB and at most 87 KB).
   Each maps a word to the agreements whose latest version uses it. Every word
   is kept: leaving out the commonest would make a search for "nhs" find
   nothing, and a word in more than one agreement in twelve is stored as a
   bitset, which keeps those small. Titles, references, organisation and dataset names go in too, so
   one set of word rules covers the whole search. Apostrophes are dropped from
   words, so "kings college" finds "King's College" (121 agreements; none today).
   An acronym's plural indexes as the acronym too, judged per agreement from
   how its own text writes the word: "GPs" also indexes as "gp", and "GP"
   written in capitals also as "gps". "gp" then finds 899 agreements (872 as
   a whole word alone) and "gps" 900 (392); "icbs" 734 (248), "ccgs" 550 (476).
   Ordinary words are untouched ("ha", "doe" and "los" match as before), and
   so is "mri", although the register also has "MRIS", a different acronym
   in capitals. Short ordinary plurals are not matched: "age" does not find
   "ages".
   The files sit under the edition's name, so a cached index never answers for
   another edition.
2. **The agreements list fetches the shards a search needs** when someone
   types, and caches them, so a page that is never searched loads nothing more
   and a two-word search usually costs one or two files. If the index fails to
   load, the search falls back to the text each row shows: title, reference,
   organisation and type. The rows carry no search text of their own, which
   was a third of the page.
3. **The organisation and dataset tables** use the same files, which the
   browser has already cached if the visitor searched elsewhere first.
4. **Show why a row matched.** A row found only in the purpose text has
   nothing on screen explaining the match, so while a search is active its link
   carries it (`?q=dementia`), and the agreement page highlights the words,
   opens the purpose sections they are in and scrolls to the first. The plan
   was a text fragment (`#:~:text=`), but that matches whole words only, so it
   could not show "pharmaceutical" for "pharma", and a page cannot read it to
   open a collapsed section in every browser.
