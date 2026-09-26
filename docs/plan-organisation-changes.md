# Plan: NHS organisation changes, from ODS

Status: **proposed.** Nothing here is built. It follows from
[plan-version-diffs.md](plan-version-diffs.md) §11, which merged the
organisations the register had merely relabelled and left the NHS
reorganisations for this piece of work. All figures below are from the facts
store at the September 2026 edition, and from the ODS API on 2026-09-26.

## 1. The problem

The register names NHS organisations as they were called when an edition was
published. When the NHS reorganises, the names change on hundreds of
agreements at once, and the site reports each one as a change of data
controller or applicant. After §11's renames, these are most of what is left:

| | Amendments across the archive |
| --- | ---: |
| Now | 2,565 |
| If CCG to ICB changes were labelled as successions | about **1,686** |
| October 2022 alone, now and then | 881, then 2 |

October 2022 is when the register moved from CCG names to ICB names, three
months after the ICBs took over on 1 July 2022. It is the second-largest
amendment event in the archive and it is almost entirely this. (§10 of
plan-version-diffs.md put October to December 2022 down to dataset relabelling
"by inspection". For October that was wrong.)

The alias file cannot fix this, and should not be used to try. An alias says
two names are one organisation, for every purpose, and puts their agreements on
one page. A CCG and the ICB that took over its functions are different
statutory bodies. Often several CCGs passed to one ICB, so an alias would put
several bodies' agreements on one page. What these changes need is a third kind
of relation beside "same organisation" and "different organisation": **one
organisation succeeded by another, from a date**.

## 2. What ODS records

The Organisation Data Service is NHS England's reference for NHS organisation
codes, names, roles and relationships. It answers the question from records,
not from name matching.

**Access.** The ODS ORD API
(`https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations/<code>`)
answers from this environment without a key. The bulk CSV downloads on
`files.digital.nhs.uk` return 403 here, the same wall
[plan-local-edition-archive.md](plan-local-edition-archive.md) hit for the
register itself, so they would have to be fetched by hand if needed.

**A record keeps its code through a rename.** Each record has one code and its
*current* name only. ORD keeps no name history.

**CCGs mostly continued as sub-ICB locations, under the same code.** On 1 July
2022 most CCG records gained the sub-ICB location role (`RO319`), were renamed,
and were linked (`RE5`) to their ICB:

```
91Q   NHS KENT AND MEDWAY ICB - 91Q     roles RO98 (CCG) from 2020, RO319 from 2022-07-01
                                        in ICB QKS, NHS KENT AND MEDWAY INTEGRATED CARE BOARD
```

So the register's "NHS KENT AND MEDWAY CCG" becoming "NHS KENT AND MEDWAY ICB -
91Q" is, in ODS terms, one record renamed. The code in the register's ICB names
is the old CCG's code.

**Mergers are successor links.** A body that closed into another carries a
`Successor` link, and the body it closed into carries `Predecessor` links, with
the legal date:

```
03J   NHS NORTH KIRKLEES CCG    Inactive, successor X2C4Y from 2021-04-01
RH8   ROYAL DEVON UNIVERSITY HEALTHCARE NHS FOUNDATION TRUST
                                predecessor RBZ (Northern Devon Healthcare) from 2022-04-01
X26   NHS ENGLAND               predecessors T1430 (Health and Social Care
                                Information Centre, i.e. NHS Digital) and X09
```

Royal Devon shows both cases in one record: Royal Devon and Exeter kept its
code (RH8) and was renamed, and Northern Devon closed into it. §11's alias for
Royal Devon is therefore right for the renamed trust. Northern Devon's
agreements, if any, are a succession.

## 3. What the register gives us

Of 992 distinct organisation names in the archive (applicants and data
controllers):

- **107 carry an ODS code in the name**, all but one of them ICB names ("… ICB -
  91Q"); the other is "NHS ENGLAND - X26".
- **48 ICB names carry no code** ("NHS KENT AND MEDWAY INTEGRATED CARE BOARD").
  All 48 match an ODS record's current name exactly.
- **115 CCG names**, none of which ODS can find by name, because ODS now holds
  those records under their ICB names.

The register itself bridges that gap. Every one of the 115 CCG names is
replaced, on at least one agreement version, by exactly one coded ICB name.
(Nine appear to have no replacement only because they are mixed-case spellings
of names that do.) Taking the code from the replacement gives 106 codes, and
**ODS confirms all 106**: each was a CCG (`RO98`), is now a sub-ICB location
(`RO319`), and sits in an ICB.

Where several CCGs moved at once on one agreement (106 swaps, 28 distinct
combinations, such as nine Cheshire and Merseyside CCGs to nine sub-ICB
locations), the one-for-one swaps elsewhere have already fixed each name's
code, so each CCG pairs with its own sub-ICB location.

## 4. Design

### A code for every NHS name the register uses

`data/organisation-codes.json`, committed and reviewable like the alias file:

```json
{"name": "NHS KENT AND MEDWAY CCG", "code": "91Q",
 "evidence": "replaced by NHS KENT AND MEDWAY ICB - 91Q on 20 versions; ODS confirms 91Q was a CCG"}
```

Codes are assigned only on evidence, strongest first:

1. the code is in the name;
2. the name matches an ODS record's current name exactly;
3. the name was replaced by a coded name on the register, and ODS confirms
   the code's history (the CCG case above);
4. a person decided, with the reason recorded.

A command in the style of `orgcheck`, `python -m pipeline.odscheck`, proposes
codes from 1 to 3, applies the unambiguous ones, and asks about the rest. Names
without an NHS code (universities, companies, councils) get none and are
untouched.

### A committed snapshot of the ODS records we use

`data/ods/organisations.json`: for each code in the file above, and each code
its successor links reach, the ODS name, status, roles with dates, successor
and predecessor links, and ICB membership, with the date fetched. It is written
by `python -m pipeline.ods fetch`, which is the only part of the pipeline that
touches the network. The build reads the snapshot, so, as with editions, the
site never depends on ODS being reachable and a refresh is a reviewable diff.
Refresh it when an edition adds a new NHS name; `docs/manual-updates.md` gets
that step.

### Three outcomes for a name that changed

`compare_versions` already reports `renamed` beside real changes. With codes
and the snapshot it decides between:

| ODS says | Reported as | Counts as an amendment |
| --- | --- | --- |
| Same code, name changed, same role (a trust renamed) | renamed | no |
| Same code, CCG role ended 30 June 2022, now a sub-ICB location | **succeeded**: "NHS Kent and Medway CCG, succeeded by NHS Kent and Medway ICB (sub-ICB location 91Q)" | no |
| Different code, and the old one's successor chain reaches the new one | **succeeded** | no |
| Anything else | added and removed, as now | yes |

A controller list passes only if *every* removed NHS name is succeeded by one
of the added names. Otherwise the changes that cannot be explained stay
visible. Aliases are still applied first: they handle spelling, and ODS handles
identity over time.

### Wording on the site

- **Agreement pages:** the version redline and the edition timeline say
  "succeeded by", never "transferred to". The edition shows when the register
  caught up (October 2022). The date is ODS's ("ICBs took over from CCGs on 1
  July 2022"), stated as ODS's.
- **CCG organisation pages** keep their own agreements and gain a line:
  "Abolished 30 June 2022. Its functions passed to NHS Kent and Medway ICB",
  linking to that page.
- **ICB organisation pages** list their predecessor CCGs, linking back.
- Nothing here says why an organisation changed. As in §9 of
  plan-version-diffs.md, the site reports and does not narrate.

## 5. Decisions needed

1. **Is a sub-ICB location the same organisation as its ICB?** The register
   uses both forms: "NHS KENT AND MEDWAY ICB - 91Q" (a sub-ICB location, an
   ODS record in its own right) and "NHS KENT AND MEDWAY INTEGRATED CARE BOARD"
   (the statutory body, QKS). They are separate pages today. The legal
   controller is the ICB, so the recommendation is one page per ICB, with its
   sub-ICB locations listed on it. That is an ODS relationship (`RE5`), not an
   alias. This is the question most worth your judgement, because it decides
   what an ICB's page counts.
2. **ODS licence and attribution.** ODS data is published by NHS England. Its
   licence terms need confirming before a snapshot is committed, and the About
   page should credit it.
3. **Scope of the first pass.** Recommended: CCGs to ICBs only, which is where
   nearly all the effect is. Trust mergers and renames, commissioning support
   units, and NHS Digital to NHS England (whose ODS predecessor link exists)
   follow once the machinery works. Each is a few dozen swaps at most.

## 6. Steps

1. `pipeline.ods`: fetch ORD records for a list of codes, follow successor
   links, write the snapshot. Tests against recorded responses, not the live
   API.
2. `pipeline.odscheck` and `data/organisation-codes.json`: propose codes on the
   four kinds of evidence, apply the unambiguous ones, review the rest.
3. `compare_versions`: the `succeeded` outcome, and `_material` leaving it out.
   Tests for a one-for-one CCG, a many-to-many swap, a partial swap that must
   stay an amendment, and a renamed trust.
4. Templates: redline and timeline wording, CCG and ICB page lines, the About
   page credit.
5. Measure the archive before and after, and record the result here, as §8 and
   §11 of plan-version-diffs.md did.
6. The later scopes in §5.3.
