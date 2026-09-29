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

## The easy way: `--review`

```bash
.venv/bin/python -m pipeline.orgcheck --review
```

Goes through candidates one at a time:

```
[1/87] same reference code "03W"
  1) LEICESTERSHIRE AND RUTLAND ICB - 03W  (5 agreements)
  2) NHS LEICESTER, LEICESTERSHIRE AND RUTLAND ICB - 03W  (3 agreements)
  [m]erge  [i]gnore  [k]skip  [q]uit >
```

- **`m`** — merge. Asks which name to keep as canonical (or type your own),
  then an optional one-line reason. Written to
  `data/organisation-aliases.json` immediately.
- **`i`** — ignore. Also written immediately, to the same file's `ignored`
  list, so this exact candidate is never asked about again — not "not now",
  permanently, until someone edits the file.
- **`k`** — skip. Does nothing; asked again next run, useful for "not sure,
  need to check something first".
- **`q`** — quit. Whatever you've already decided this run is already saved;
  everything else shows up again next time.

Rebuild afterwards to see the result:

```bash
.venv/bin/python -m pipeline.run
```

No re-ingest needed — aliases are applied fresh on every build, so editing
this file (by hand or through `--review`) and rebuilding is enough. Open the
merged organisation's page: it lists every raw spelling it was recorded under
under "Also recorded in the register as", linking back to this file, so the
merge is always checkable against what the register actually says. Agreement
pages are never affected — they always show the applicant name exactly as
that row recorded it; only which organisation page it links to changes.

Commit `data/organisation-aliases.json` once you're happy with a session's
decisions — the reasons in the file are usually enough for the commit
message too.

## The manual way

`--review` is `data/organisation-aliases.json` written for you; nothing about
its format is special. To add a merge by hand instead:

```json
{
  "aliases": [
    {
      "canonical": "NHS Bedfordshire, Luton and Milton Keynes ICB - M1J4Y",
      "variants": ["Luton and Milton Keynes ICB - M1J4Y"],
      "reason": "Same ICB reference code (M1J4Y) recorded under a shorter name on some agreement rows."
    }
  ],
  "ignored": []
}
```

`canonical` is what the organisation page shows. `variants` is every other
spelling seen in the register that should land on that page — matching
ignores case and extra whitespace, but not wording, so list each spelling
that actually occurs. `ignored` is a list of candidates (each the sorted list
of names involved) that `--review` should stop suggesting.

`python -m pipeline.orgcheck` on its own — no `--review` — prints the same
candidates without prompting, if you'd rather read the whole list first.

## Renames: names that changed between editions

The candidates above all come from one edition — names sitting side by side
in the current data that might be the same organisation. A **rename** is
invisible to that, because the old spelling is not in the current edition at
all. It is only in the previous one.

This is not a rare case. In the October 2025 edition NHS England relabelled
itself from "NHS ENGLAND (QUARRY HOUSE)" to "NHS ENGLAND - X26" on 126
agreements, and the register issued no new version numbers and published no
changelog. The site read that as 126 agreements amended.

To find them, compare editions:

```bash
.venv/bin/python -m pipeline.orgcheck --renames --review
```

With no arguments it reads every workbook in `data/raw/`; name specific ones
to compare just those. It walks consecutive editions oldest first and looks
for a version whose organisation or controller changed from exactly one name
to exactly one other — a one-for-one swap. Anything less clear-cut (two names
leaving, three arriving) is a change of controller rather than a change of
name, and is not offered.

Rename candidates are listed first, and the review prompt marks the current
spelling and offers it as the canonical name, so accepting one is a keypress:

```
[1/29] renamed in October 2025, on 126 agreement versions
  1) NHS ENGLAND (QUARRY HOUSE)  (not in the current edition)
  2) NHS ENGLAND - X26  (46 agreements)  <- current
```

Only the Agreements sheet is read, so this is much faster than a re-ingest,
but it still parses every workbook — expect minutes, not seconds, across a
full archive.

Two things worth knowing. A rename found this way is still only a candidate:
"CITY, UNIVERSITY OF LONDON" becoming "CITY ST GEORGE'S UNIVERSITY OF LONDON"
is a real merger of two institutions, not a relabelling, and whether those
should share a page is a judgement. And the register sometimes reuses a name
for a genuinely different body, so a swap is evidence, not proof.

## Merging the obvious ones without reviewing them

Most candidates are not judgement calls. A name that differs only in
punctuation, in a bracketed acronym, or in whether it ends "Limited" or "Ltd"
is the same organisation written two ways, and reading through those to press
[m] is wasted effort.

```bash
.venv/bin/python -m pipeline.orgcheck --auto
```

applies exactly three kinds of merge and nothing else:

| Rule | Example |
| --- | --- |
| Punctuation, spacing or case only | `CITY ST GEORGE’S…` / `CITY ST GEORGE'S…` |
| A bracketed acronym appended | `Adult Psychiatric Morbidity Survey` / `… (APMS)` |
| Legal form only | `NEC Software Solutions` / `NEC Software Solutions Limited` |

With `--renames`, a fourth applies: a name that left the register while
another appeared on *exactly* the same agreements. That is evidence of one
organisation under two labels, and a better reason than anything the spelling
shows. Below total overlap it goes to review.

Each of these writes `"source": "auto"` and the reason that fired, so the
automatic entries can be found, audited or removed as a group later.

Nothing that adds or removes a word of substance is automated. "NHS Sussex"
and "NHS Surrey and Sussex" are different bodies, as are "NHS Essex" and "NHS
Mid and South Essex", and merging those would attribute one organisation's
data sharing to another. Those still come to you.

One case to spot-check: a merger reads exactly like a rename. "City,
University of London" becoming "City St George's, University of London" is
two institutions combining, and whether they should share a page is a
judgement `--auto` cannot make. Scanning the `source: auto` entries after a
run is worth the minute it takes.

## Datasets

Datasets get relabelled more often than organisations — in January 2023 the
register appended an acronym to most of them at once — and they have their
own file and tool:

```bash
.venv/bin/python -m pipeline.datasetcheck            # list
.venv/bin/python -m pipeline.datasetcheck --auto     # apply the clear ones
.venv/bin/python -m pipeline.datasetcheck --review   # decide the rest
```

It works only across editions, since a renamed dataset's old name is absent
from the current one, and it reads every edition from the facts store, so it
needs no workbooks and takes seconds. Candidates come from what left and arrived on the same
agreements, never from how alike two names look: "Mental Health Minimum Data
Set" and "Mental Health Services Data Set" are 79% alike and are different
datasets, while "GPES Data for Pandemic Planning and Research (COVID-19)" and
"COVID-19 General Practice Extraction Service (GPES) Data for Pandemic
Planning and Research (GDPPR)" are 62% alike and are one.

Decisions land in `data/dataset-aliases.json`, which `extract` applies when
grouping datasets, so a renamed dataset keeps one page and one history
instead of splitting at the rename.

A dataset's `canonical` name is not what its page is titled. It is what the
page's address is made from, and a rename is merged onto the name it replaced,
so the address a reader bookmarked or cited survives every later rename. The
page is titled with the spelling the latest versions of its agreements use
most, and lists the others as "Also recorded in the register as". A dataset
renamed twice stays one group: a new name joins the group its old name is
already in, and a chain left by hand is followed to its end when the file is
read.

## NHS reorganisations (ODS)

Aliases say two names are one organisation. NHS reorganisations need more:
a clinical commissioning group and the integrated care board that took over
from it are different bodies, and several CCGs often passed to one ICB. For
NHS organisations the site asks the NHS Organisation Data Service (ODS)
instead, which records codes, roles and who succeeded whom, and says three
things with it:

- **renamed**: two names ODS gives one record, or a sub-ICB location and its
  ICB. Not counted as a change.
- **succeeded**: one organisation took over from another, with ODS's date.
  Not counted as a change, and shown on the agreement's timeline and on both
  organisation pages.
- **one page per ICB**: every sub-ICB location's name goes to its ICB's page,
  which lists the locations with the CCG each continued. Names are shown
  without ODS codes, except in that list, where a code explains which body
  continued which.

Three committed files hold it, and the build never asks ODS anything:

| File | What it holds | Written by |
| --- | --- | --- |
| `data/organisation-codes.json` | the ODS code for each register name, with the evidence | `python -m pipeline.odscheck --apply` |
| `data/ods/organisations.json` | the ODS records those codes reach (Open Government Licence) | `python -m pipeline.ods` |
| `data/organisation-successions.json` | successions ODS has no record of, or dates misleadingly | by hand |

`odscheck` assigns a code only on evidence: the code is in the name ("NHS KENT
AND MEDWAY ICB - 91Q"); the name is exactly one ODS organisation's current
name; or the name is a CCG's, and the register replaced it with a coded name
whose ODS record was a CCG and became a sub-ICB location. That last case exists
because ODS kept most CCG records on 1 July 2022 and renamed them, so their
old names are gone from ODS. A CCG name only ever matches a CCG record: ODS
holds some prescribing records under old CCG names. An entry whose evidence
starts `reviewed:` was decided by a person, and every run keeps it.

How the pieces fit:

- A reviewed alias wins over ODS. Names an alias merges share whichever code
  one of them has, and the page keeps the reviewer's chosen name.
- A page takes ODS's name only where the register uses it too. Otherwise the
  register's own name stands, because ODS can be out of date ("Velindre NHS
  Trust" for Velindre University NHS Trust).
- A reviewed succession wins over any code the same name was matched to, and
  pages say it was recorded by hand. The first is the Health and Social Care
  Information Centre, succeeded by NHS England on 1 February 2023, which ODS
  dates to April 2013.

When a new edition names an NHS organisation the register has not used
before, run both commands and commit the two data files; see
[manual-updates.md](manual-updates.md).

## Deciding

For each candidate ask: is this the same legal entity recorded
inconsistently, or two different organisations that happen to look similar?
When in doubt, skip or ignore it — an unmerged near-duplicate is a cosmetic
inconvenience; a wrong merge attributes one organisation's data sharing to
another.

### Parts of an organisation

The register sometimes names a part of an organisation as the applicant: a
hospital ("Addenbrooke's Hospital"), a medical school or department ("Cardiff
University School of Medicine"), a unit ("National CJD Surveillance Unit").
None of these is a legal entity, so none can hold an agreement; the
organisation it belongs to does. Merge the part onto that organisation, so its
agreements are counted where they are held. The register usually confirms
which organisation that is, by naming it as data controller on the same
agreement.

Merged on 2026-09-27, each with its reason in the alias file: Addenbrooke's
Hospital, Norfolk and Norwich University Hospital, Royal Liverpool University
Hospital and the National Centre for Stereotactic Radiosurgery onto their
trusts; Barts and The London School of Medicine and Dentistry and the Wolfson
Institute of Preventive Medicine (Queen Mary University of London), Cardiff
University School of Medicine, Imperial College Business School, the Nuffield
Department of Primary Health Sciences and the Department of Paediatrics
(Oxford), the National CJD Surveillance Unit (Edinburgh), the Leeds Institute
of Health Sciences and the Institute of Child Health (UCL) onto their
universities.

Not merged, because the part belongs to more than one organisation or is a
legal entity itself: Hull York Medical School (the universities of Hull and
York), the Cambridge Centre for Health Services Research (Cambridge and RAND
Europe), Erasmus University Medical Centre, and St George's Hospital Medical
School, the legal name of St George's, University of London, which merged into
City St George's in 2024.

Also not merged, by decision on 2026-09-27: bodies hosted by an organisation
rather than part of it, even where the host is the only data controller named.
They are RM Partners (The Royal Marsden), Health Innovation Network South
London (Guy's and St Thomas'), the NIHR BioResource (Cambridge University
Hospitals), the Regional Drug & Therapeutic Centre (Newcastle upon Tyne
Hospitals), the Northern Ireland Clinical Trials Unit (Belfast Health and Social
Care Trust) and the National Institute for Health Research (the Department of
Health and Social Care); and the cancer alliances and commissioning support
units, whose hosts vary and change.

An applicant can rightly differ from the data controller: the Institute of
Child Health, as UCL, is a commissioned processor for the Department of Health
and Social Care, which is the controller on its agreement. Merging a part onto
its organisation changes only which page lists it as applicant; the controllers
are always shown as the register records them.

A hospital that changed hands goes to the organisation it belonged to when its
agreements were made. Every agreement version naming Royal Brompton Hospital
began before 1 February 2021, when Royal Brompton & Harefield NHS Foundation
Trust merged into Guy's and St Thomas' NHS Foundation Trust, so the name is
recorded under the former trust's ODS code (RT3) and its page takes that
trust's name. ODS records the merger, so the site shows Guy's and St Thomas' as
its successor, and an agreement renewed under Guy's and St Thomas' shows a
succession, not a change of applicant; DARS-NIC-144568-D7G6V says the same in
its own text. "GSTT @ Royal Brompton Hospital", the register's label for the
same agreements from October 2021 to May 2022, goes to Guy's and St Thomas'.
When the register went back to "Royal Brompton Hospital" in June 2022, that is
still reported as a change of applicant, as the register made it.

### Related, not merged

Organisations that belong together without being one organisation are linked
instead of merged, in `data/organisation-relations.json`, by page slug:

- **groups**: companies of one group, such as the four IQVIA companies;
- **hosted**: a body and the organisation hosting it, such as RM Partners and
  The Royal Marsden, the hosted bodies decided on above;
- **joint**: a body run by more than one organisation, such as Hull York
  Medical School;
- **merged**: an organisation that merged into another after its agreements
  were made, such as St George's Hospital Medical School into City St George's.

Each page named gets a "Related organisations" line linking the others, and
their agreements stay on their own pages. Every entry gives its reason. Nothing
is suggested automatically: names that share a word are more often neighbours
than relations. After an edition, check every slug still has a page:

```bash
.venv/bin/python -m pipeline.relations
```

## Waiting for a decision

Name changes seen in the register that might be one company renamed, or one
company taking over another, and that could not be settled from here. Each is
still counted as a change of data controller or applicant. Merge it in
`data/organisation-aliases.json` once it is known to be the same legal entity,
or add it to `ignored` once it is known not to be.

| From | To | Seen | Question |
| --- | --- | --- | --- |
| LA-SER Europe Limited (a Certara company) | Certara UK | 8 changes, 2 agreements | Is Certara UK the same legal entity, or the company that acquired LA-SER? |
| 2020 Delivery Ltd | The Public Service Consultants Limited | 2 changes, 1 agreement | A rebrand of one company, or a different one? |

Recorded 2026-09-26.

Also decided then, and not to be merged:
- **Royal Brompton Hospital** was left as written then, and is now placed by
  date (2026-09-27, below).
- **Three `orgcheck` candidates** are different bodies and are marked
  `ignored`: Sussex ICB and Surrey and Sussex ICB (ODS records the April 2026
  merger, which the site shows as a succession); Lancashire & South Cumbria
  NHS FT and the ICB; South Central and South Western ambulance trusts.

Successions ODS has no record of, or dates misleadingly, are recorded by hand in
`data/organisation-successions.json`, each with its reason. The first is the
Health and Social Care Information Centre (NHS Digital) succeeded by NHS
England on 1 February 2023, which ODS dates to April 2013.

## What this does and doesn't do

- It only affects the **organisation** field (the applicant, and the data
  controller cross-reference on organisation pages) — never agreement titles,
  dataset names, or any other free text from the register.
- It also decides what counts as a change. When a version's applicant or data
  controllers move from one name to another that the aliases call the same
  organisation, the site reports a rename, not an amendment. Merging two names
  therefore changes the "what changed" counts as well as the pages.
- It's forward and backward compatible with the committed edition store: an
  alias applies to every edition rebuilt after it's added, not just the one
  ingested at the time.
- A name merged away does not lose its address. Its old organisation page
  becomes a page that forwards to the one its agreements are now on, and an
  agreement whose applicant is listed under a differently named page says so.
- It does not edit or correct the register itself, and doesn't claim to —
  this site is a mirror (see the About page's caveats). It only decides which
  of this site's own pages a name's agreements appear on.
