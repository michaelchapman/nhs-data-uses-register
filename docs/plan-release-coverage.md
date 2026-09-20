# Plan: what a "file released" covers, and what it leaves out

Status: **accepted, store support implemented; site features parked.** The
record described in §4 is in `pipeline/facts.py`. The site wording in §5 and the
release views (a `release-months.csv`, a "no files recorded" line and filter, a
per-agreement timeline, a register-wide monthly chart, a release check) are
deliberately left for a separate piece of work, agreed 2026-09-20, so the
facts-store push carries no release-related site change. Nothing in the store
needs revisiting to build them: they are all build-time work.

This is a companion to [plan-facts-store.md](plan-facts-store.md), which decided
*how* releases are stored. This one decides what they can honestly be said to
mean, because the facts store makes several release-based views cheap to build
and each of them could mislead.

## 1. The claim we must not make

Half the register has no release recorded against it: of 1,950 agreements in
the September 2026 edition, 983 have had files released, 651 expired with none
recorded, 257 have run over a year with none, and 59 are too recent to tell.

The tempting headline — *half of these agreements never resulted in any data
being shared* — is false. A release row records **a physical file leaving
NHS England through DARS**, and that is one of several ways data reaches an
applicant. NHS England's own description of the register is "details of
physical files that were released and when".

## 2. What is out of scope, and why

**Access inside a secure environment.** Where an applicant analyses data in
place, no file is released and nothing appears in `DataReleases`. NHS England
names one such service on the register page — the OpenSAFELY COVID-19 service,
whose approved users are listed on OpenSAFELY's own site, not here.

**Onward releases by a recipient.** The register records NHS England releasing
a file to the applicant. Where the applicant may then share it on — a
commissioning support unit or DSCRO passing data to ICBs, for instance — those
onward releases are not recorded. The only signal in the data is the
sub-licensing flag: **91 of 1,950 agreements permit onward sharing, and 34 of
those have had files released.** Nothing downstream of those 34 is visible
here.

**NHS England's internal flows, from 1 February 2023.** On the merger of
NHS Digital and NHS England, agreements within the merged organisation left
this register for the Internal Data Flow Record. This is visible in our own
snapshots: **25 agreements disappeared between the January and February 2023
editions**, against a baseline of one or two a month.

```
  december2022 -> january2023:   1 agreements gone
  january2023  -> february2023: 25 agreements gone
  april2023    -> may2023:       2 agreements gone
```

Those 25 did not end. Read naively, the site would show them vanishing.

**Releases published in a different register.** NHS England publishes several
separately: the Internal Data Uses Register, the National Back Office register
(tracing and Demographics Batch Service Bureau), the NDRS register, the ONS
release register for the jointly controlled Public Health Research Database,
and the COVID-19 (non-DARS) register covering March 2020 to April 2022. Data
Sharing Framework Contracts sit above individual agreements and are published
separately again.

**Anything before the archive starts.** Releases in the workbook run from
2016-04, five years earlier than the July 2021 edition archive, so release
history is deeper than change history and the two must not be described as one
period.

### Still open

Whether commissioning support units acting on NHS England's behalf were ever
in scope *before* February 2023 is not answerable from the workbook: there is
no column naming who performed a release or under what mechanism. The three
sheets are `Agreements`, `Datasets` and `DataReleases`, and none carries an
access-mechanism, releasing-body or onward-release field. Answering it means
asking NHS England, not parsing harder.

## 3. What this requires of the store

The store must be able to hold releases that arrive from somewhere else later,
without a redesign and without a re-parse.

**Separate registers are already separate.** `data/facts/<register>/` is keyed
by register slug, and `sources.REGISTERS` already lists
`internal-data-uses-register` and `data-sharing-framework-contracts`, disabled
pending their sheet layouts. The National Back Office, NDRS and COVID-19
registers would be added the same way. Nothing new is needed.

**Channels within a register are not.** A file release and an in-place access
are different kinds of event about the same agreement, so every release record
carries a `channel`, today always `"file"`. This costs one field and buys two
things: a later source can be added alongside rather than merged into the file
releases, and the code cannot accidentally call a file release "access"
because the field it reads is named for what it holds.

**Provenance in time is already there.** Each record names the first edition
that reported it, so an edition shows the history it had.

## 4. The record, at file grain

The plan originally aggregated releases to (reference, dataset, month, count).
Checking the sheet showed that throws away more than it saves:

| Finding | Consequence |
| --- | --- |
| `File Reference` is unique across all 104,451 rows | The sheet has a primary key, and aggregating discards it |
| 737 rows carry attributes differing from the `Datasets` sheet | Per-release type, sensitivity, legal basis and frequency are not always the dataset's |
| 130 of 8,449 (reference, dataset) pairs hold more than one opt-out value | One opt-out flag per pair is wrong, and `extract`'s `setdefault` already hid this |

So a release is stored per file, grouped under the reference, dataset and
channel they share, with one row each:

```json
{"reference": "DARS-NIC-1-AAAAA-v2", "dataset": "MSDS …", "channel": "file",
 "files": [["FILE0074357", "2022-01", "Yes", "april2022"]]}
```

A row is `[file reference, month, opt-outs applied, first edition that reported
it]`. Rows rather than objects because there are 104,451 of them and an object
would spend more on repeating four key names than on the facts: measured, the
grouped form is 12 MB where one object per file was 49 MB.

Attributes are stored only where they cannot be inferred — the 737 rows that
disagree with the `Datasets` sheet, and rows whose dataset name the version
lists twice with different attributes, where "the same as its dataset" does not
name one answer. Everything else is rebuilt from its dataset on the way back.

This is genuinely append-only: a file reference, once issued, is a fact. A file
reported differently by a later edition is counted, not overwritten.

An opt-out flag that disagrees within a dataset is now representable, so
`summarise_releases` reports `"Mixed"` rather than silently taking whichever
row came first.

### Checked

Both the August and September 2026 workbooks record and read back identically,
file for file. September adds 745 released files and 37 states to August's
103,706 and 5,577, rewriting 211 release files and 36 agreements. Two editions
cost 12 MB of releases beside 149 MB of agreements.

Getting there caught two faults that only real data shows. `extract` compared a
release row with its dataset *before* `tidy_version` cleaned it while the
reader compared after, so the same edition summarised differently depending on
where it came from; and a version that lists one dataset name twice with
different attributes — an anonymised and an identifiable cut of the same
death-registration extract — made the answer depend on which record was read
last.

## 5. What the site may say

- **"No files recorded as released under this agreement"** rather than any
  wording that says data was not shared. §2 is the reason.
- Every release view states that it covers files released through DARS, and
  links to the other registers for what it does not cover.
- The February 2023 discontinuity is labelled wherever agreements leaving the
  register are counted, in the way the January 2025 gap already is.
- Release history is described as running from 2016, and register change
  history from July 2021, never as one span.
- A sub-licensing agreement's release list says that onward sharing is
  permitted and not recorded here.

## 6. Steps

1. **Store the release record of §4,** with `channel` and file grain. *Done.*
2. Carry the wording of §5 into the templates when the release views are built
   — see [plan-facts-store.md](plan-facts-store.md) §"What more could be done".
3. Label the February 2023 discontinuity on the changes pages.
4. Ask NHS England the question in §2, and record the answer here.
