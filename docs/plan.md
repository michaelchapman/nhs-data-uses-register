# Plan: what is left to do

The single list of outstanding work. The earlier plans (the facts store, the
local edition archive, version diffs, release coverage and NHS organisation
changes) are finished or folded in here, and their reasoning is kept in the git
history. What still governs the site lives in three places: the
[README](../README.md), the monthly routine in
[manual-updates.md](manual-updates.md), and the name rules in
[organisation-names.md](organisation-names.md).

Last reviewed 2026-09-27. In rough order of value:

1. [Searching the purpose text](#1-searching-the-purpose-text)
2. [Release views](#2-release-views)
3. [Change downloads](#3-change-downloads)
4. [Amendments on the changes page](#4-amendments-on-the-changes-page)
5. [Checking workbooks before a re-parse](#5-checking-workbooks-before-a-re-parse)
6. [Waiting on people](#6-waiting-on-people)
7. [Considered and not planned](#7-considered-and-not-planned)

## 1. Searching the purpose text

Issue #21. Search on the agreements list matches the title, reference,
organisation and dataset names, never the objective, activities, outputs and
benefits, which are where an agreement's subject is. Measured on the
September 2026 edition:

| Search | Matches today | With the purpose text |
| --- | ---: | ---: |
| dementia | 10 | 123 |
| pharmaceutical | 0 | 209 |
| police | 0 | 167 |
| insurance | 0 | 27 |
| machine learning | 3 | 59 |

### What the measurements rule out

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
- **Earlier versions' text.** The page shows the latest version, and a match
  only in superseded text could not be seen on it: "marketing" is in 106
  latest versions and 248 including earlier ones.

### To build

1. **An index built with the site**, one JSON file per first character of the
   word (36 files, a median of 17 KB and at most 79 KB gzipped). Each maps a word
   to the agreements whose latest version uses it. Words in more than half the
   agreements ("the", "nhs", 385 in all) are left out, as are numbers longer than
   four digits. Titles, references, organisation and dataset names go in too, so
   one set of word rules covers the whole search. Apostrophes are dropped from
   words, so "kings college" finds "King's College" (121 agreements; none today).
   The files sit under the edition's name, so a cached index never answers for
   another edition.
2. **The agreements list fetches the shards a search needs** when someone
   types, and caches them, so a page that is never searched loads nothing more
   and a two-word search usually costs one or two files. The in-page
   `data-search` text stays as the fallback until the index has loaded, and if
   it fails to load.
3. **The organisation and dataset tables** use the same files, which the
   browser has already cached if the visitor searched elsewhere first.
4. **Show why a row matched.** A row found only in the purpose text has
   nothing on screen explaining the match. Its link can carry a text fragment
   (`#:~:text=dementia`), which Chrome, Edge and Safari scroll to and highlight,
   opening the collapsed section if needed.

The purpose text in the CSVs (#26) is separate. It is 41 MB for the latest versions
alone, so it needs its own file and a decision on its size.

## 2. Release views

The facts store holds every file released, 104,451 rows from April 2016, one
per file with its month and opt-out flag. The site shows them only summarised
by dataset. All of the following are build-time work; nothing in the store
needs to change.

To build, in this order:

1. **`release-months.csv`** on the downloads page: files released per
   agreement, dataset and month. With it, a **release check** that the months
   add up to `releases.csv`, per agreement.
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

## 3. Change downloads

Everything on the changes pages is computed at build time, so publishing it is
cheap, and it makes the month-on-month history usable by other people's
tooling:

- `downloads/changes.csv`: one row per change across every edition held, with
  edition, previous edition, reference, base reference, organisation, kind
  (added, amended, no longer listed, register-wide edit, renamed, succeeded),
  the fields changed, and the agreement's URL;
- `downloads/changes.json`: the same, with the old and new values and word
  edits the pages show (`changes._details`), and the source of each succession
  (ODS or reviewed).

## 4. Amendments on the changes page

Every amendment now shows what changed, and register-wide edits are reported
once. Two smaller things were proposed and not done:

- lead the changes page with what an in-place amendment is: an edit NHS England
  made to an existing record without a new version number, for which there is
  no official changelog. That is the site's own contribution and it sits
  second, under "Added";
- make an agreement's "Amended this month" tag link to the change on its
  timeline.

## 5. Checking workbooks before a re-parse

The manifest records each ingested workbook's SHA-256. A `--verify` flag on
`ingest` that checks the files in `data/raw/` against it would catch a wrong or
corrupted download before a 70-minute re-parse, not during one. It matters only
when a re-parse is needed, which is rare.

## 6. Waiting on people

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
  versions then were NHS England's own. And whether any test record other than
  DARS-NIC-401994-D5Q7S reached a published workbook.
- **The ODS licence.** The site credits ODS under the Open Government Licence
  v3.0. That could not be checked against ODS's own pages from the build
  environment, which digital.nhs.uk refuses. It is worth confirming once.

## 7. Considered and not planned

- **An amendment log for prose.** Proposed to show old and new text between
  editions. Unnecessary: the facts store keeps every edition's text, so the
  site shows prose redlines already.
- **Paging the changes pages.** December 2022 was 1,192 rows. As one
  register-wide edit it is one row and a collapsed list, and the largest page is
  now 370 KB.
- **Holding the facts store in memory** to shorten the build further. Most of
  the remaining 47 seconds is reading it, but reading one agreement at a time
  keeps peak memory near 1 GB, which matters more.
