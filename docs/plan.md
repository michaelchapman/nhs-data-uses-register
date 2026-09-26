# Plan: what is left to do

The single list of outstanding work. The earlier plans (the facts store, the
local edition archive, version diffs, release coverage and NHS organisation
changes) are finished or folded in here, and their reasoning is kept in the git
history. What still governs the site lives in three places: the
[README](../README.md), the monthly routine in
[manual-updates.md](manual-updates.md), and the name rules in
[organisation-names.md](organisation-names.md).

Last reviewed 2026-09-26. In rough order of value:

1. [Release views](#1-release-views)
2. [Change downloads](#2-change-downloads)
3. [Amendments on the changes page](#3-amendments-on-the-changes-page)
4. [Checking workbooks before a re-parse](#4-checking-workbooks-before-a-re-parse)
5. [Waiting on people](#5-waiting-on-people)
6. [Considered and not planned](#6-considered-and-not-planned)

## 1. Release views

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

## 2. Change downloads

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

## 3. Amendments on the changes page

Every amendment now shows what changed, and register-wide edits are reported
once. Two smaller things were proposed and not done:

- lead the changes page with what an in-place amendment is: an edit NHS England
  made to an existing record without a new version number, for which there is
  no official changelog. That is the site's own contribution and it sits
  second, under "Added";
- make an agreement's "Amended this month" tag link to the change on its
  timeline.

## 4. Checking workbooks before a re-parse

The manifest records each ingested workbook's SHA-256. A `--verify` flag on
`ingest` that checks the files in `data/raw/` against it would catch a wrong or
corrupted download before a 70-minute re-parse, not during one. It matters only
when a re-parse is needed, which is rare.

## 5. Waiting on people

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

## 6. Considered and not planned

- **An amendment log for prose.** Proposed to show old and new text between
  editions. Unnecessary: the facts store keeps every edition's text, so the
  site shows prose redlines already.
- **Paging the changes pages.** December 2022 was 1,192 rows. As one
  register-wide edit it is one row and a collapsed list, and the largest page is
  now 370 KB.
- **Holding the facts store in memory** to shorten the build further. Most of
  the remaining 47 seconds is reading it, but reading one agreement at a time
  keeps peak memory near 1 GB, which matters more.
