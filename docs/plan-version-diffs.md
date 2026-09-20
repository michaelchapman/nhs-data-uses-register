# Plan: show what actually changed between versions of an agreement

Status: **partly implemented.**

| Recommendation | State |
| --- | --- |
| R1 per-agreement edition timeline | shipped |
| R2 per-field digests, so amendments name the fields that moved | shipped (fingerprint rules v3, now v5) |
| R4 redlines between versions of an agreement | shipped (`pipeline/compare.py`) |
| R3 amendment log, R7 stored values for short fields | not started: the site can say *which* fields an edition changed in place, not their old and new text |
| R5 vocabulary for in-place amendments, R6 machine-readable change outputs | not started |

The sections below are kept as written, so §1 describes the site as it was
before R1, R2 and R4 shipped; the table above is the current state.

Revised four times: after confirming the published workbooks were held
locally, after running the probe (§7), after the re-ingest that applied
the new fingerprint rules (§8), and after the archive was extended back
to July 2021 (§10). Each pass overturned part of the one before — §8
corrects a conclusion in §7, and §10 corrects one in §2. The sections
are kept in the order they were written rather than tidied, so the
corrections stay visible. That changes the plan materially: field-level history can be
backfilled across the whole archive rather than starting from whichever
edition the work lands in, so this is no longer a race against the next
publication. See [§6](#6-backfilling-the-archive).

When it was written the site answered *which* agreements changed this month
(`/changes/`, and one page per edition pair) but not *what* changed in any of
them. This document proposes closing that gap, in increments that can ship
independently.

## 1. What we can say today, and what we can't

`snapshot._fingerprint` reduces each agreement version to a single 16-hex
digest over 13 text fields plus the sorted dataset names. `snapshot.diff`
compares two editions' digests and buckets every version into added,
amended or removed.

That is enough for "this changed" and structurally incapable of anything
more. A digest is one bit of information: same or different. It cannot
say which field moved, by how much, or in which direction.

The gap shows up twice:

- **Between versions of an agreement.** The agreement page lists
  `v1.0`, `v2.0`, `v2.1` as collapsible blocks with each one's full text
  repeated. A reader comparing a renewal against the version it replaced
  has to read two 3,000-word prose blocks side by side and spot the
  difference themselves. Nothing on the page marks the delta, even though
  both texts are right there in the same extract.
- **Within a version, between editions.** An agreement modified in place
  keeps its reference number, so it never appears as a new version at
  all — it lands in the "amended" bucket with no further detail.

## 2. Evidence: in-place amendment is the normal case, not an edge case

Fingerprint comparison across the 19 committed editions:

| Edition (vs previous) | Added | Amended in place | Removed |
| --- | ---: | ---: | ---: |
| April 2025 | 58 | 2 | 0 |
| May 2025 | 53 | 0 | 0 |
| June 2025 | 59 | 3 | 0 |
| July 2025 | 52 | 41 | 0 |
| August 2025 | 45 | 1 | 0 |
| September 2025 | 39 | 0 | 0 |
| October 2025 | 51 | 52 | 0 |
| November 2025 | 47 | 16 | 0 |
| December 2025 | 37 | 2 | 0 |
| January 2026 | 32 | 0 | 0 |
| February 2026 | 55 | 72 | 0 |
| March 2026 | 25 | 122 | 0 |
| April 2026 | 47 | 1 | 0 |
| May 2026 | 53 | 73 | 0 |
| June 2026 | 44 | 73 | 0 |
| July 2026 | 59 | 15 | 0 |
| August 2026 | 31 | 20 | 0 |
| September 2026 | 36 | 1 | 0 |

Three things stand out.

**Nothing is ever removed** — *wrong, see [§10](#10-what-five-years-changed).*
In the 18 edition pairs available when this was written, not one
agreement version had left the register, and the "No longer listed"
section of `/changes/` had been empty every month. Extending the
archive back to July 2021 found 106 removals, 83 of them in a single
edition. The conclusion held only for the window it was drawn from.

**Amendment volume is spiky, and the spikes are mostly not real.** March
2026 amended 122 versions — five times that month's new agreements.
February, May and June 2026 amended 70+. The probe has since measured
two of these pairs (§7): 86% of March's amendments are typographic
churn, and the site is currently reporting 122 changes in a month where
17 happened. The spike was worth explaining, and the explanation turns
out to be mostly an artefact of how the fingerprint compares text.

**The user-reported case is real and is this month's only amendment.**
`DARS-NIC-788663-G4F2D-v0.2` (Office for National Statistics, *Health
and Growth Accelerator (HGA) Programme National Evaluation*) is present
in both August and September 2026 under the same reference, with
different digests:

```
august2026     8350b60a84ce9386
september2026  cda7c782d1f38cc4
```

It is the sole amendment in the September edition. The site can say so.
It cannot say what was edited, because the August full extract has been
pruned (`editions.DEFAULT_KEEP = 1`) and the August workbook is not in
this repository (`data/raw/` is gitignored).

It is, however, recoverable — the August and September workbooks both
exist on the maintainer's machine. That is the difference between this
revision and the first draft. The argument for recording amendment
detail at ingest is no longer "otherwise it is lost forever"; it is that
reconstructing it requires a 530 MB local archive that only one person
has, which is not a basis for a published site. Capture it at ingest so
it lives in git, and use the local workbooks to backfill what was never
captured.

## 3. Blind spots in what counts as a change

Before adding detail, the definition of "changed" needs two fixes.

**Fields that should be fingerprinted and aren't.** `FINGERPRINTED`
omits `controllers` entirely. A change of data controller — arguably the
most consequential single edit an agreement can receive, and the thing a
journalist or a patient would most want flagged — currently produces no
change at all. Dataset *attributes* are also invisible: `_fingerprint`
hashes `sorted(d["name"] for d in version["datasets"])`, so a dataset
being re-classified from non-sensitive to sensitive, or its legal basis
changing from consent to Section 251 support, registers as no change.

Recommended additions: `controllers` (sorted), and per-dataset
`(name, legal_basis, sensitivity, type_of_data, confidentiality)` tuples
rather than bare names. `frequency` is borderline — it is often restated
in different words for the same meaning; include it, and let the
normalisation below absorb the noise.

`releases` and `files_released` should stay out. They change every month
by design; folding them in would mark most of the register as amended
every edition and drown the signal.

**Normalisation.** `_fingerprint` hashes `clean()`ed text, which collapses
`\r\n` and runs of blank lines but preserves trailing spaces, double
spaces, non-breaking spaces, smart-vs-straight quotes and case. The probe has since measured
this: 86% of the 122-amendment spike is exactly that kind of churn (§7). For
hashing only — never for display — normalise: `NFKC`, collapse all
whitespace runs to a single space, strip, and fold the register's `~`
bullet markers to a consistent form. Keep the displayed text exactly as
published.

This changes every digest. In the first draft that was a real cost — the
edition where it landed would have shown an artificial mass amendment,
with 19 editions of inconsistent digests behind it. With the workbooks
available it is a non-issue: re-ingest the archive in publication order
and every digest is recomputed under the same rules, so the amendment
counts stay honest all the way back to March 2025. Land the
normalisation and the new fields together, in one change, followed by
one full re-ingest.

**Update:** all three have shipped, together, as fingerprint rules v3 —
the normalisation, the missing fields, and R2's per-field digests. They
were deliberately landed in one reset so a single re-ingest applies them
all; that re-ingest is the remaining step and has not happened yet.

## 4. Recommendations

### R1 — Per-agreement edition timeline (no new data required)

**Implemented.** Ship this first. It needs no format change, re-ingest or new
dependency: every fingerprint file is already committed, and loading all
19 and indexing them by base reference takes 0.26s.

On each agreement page, add a short "Register history" list:

> First listed in the **March 2025** edition.
> `v0.2` amended in the **September 2026** edition.
> `v2.0` first appeared in the **February 2026** edition.

This alone answers "has this agreement been quietly edited, and when?" —
today unanswerable from the site even though the data is sitting in git.
It also gives the in-place amendments a permanent home: `/changes/` is
a monthly snapshot nobody revisits, whereas the agreement page is the
URL people cite.

Implementation: build an index of `base_reference -> [(edition, reference,
hash)]` once in `run.main`, pass it into `build.build`, and hand each
agreement its own slice. Cost is a few hundred lines of extra HTML per
page and no measurable build time.

### R2 — Per-field digests, so the site can name the fields that moved

**Implemented**, as fingerprint rules v3, together with the missing fields
from §3. Takes effect on re-ingest.

Replace the single `hash` per version in the snapshot with a map of
per-field digests:

```python
def _fingerprints(version: dict) -> dict[str, str]:
    fields = {key: _normalise(version.get(key, "")) for key in FINGERPRINTED}
    fields["controllers"] = sorted(map(_normalise, version["controllers"]))
    fields["datasets"] = sorted(
        [d["name"], d["legal_basis"], d["sensitivity"], d["type_of_data"]]
        for d in version["datasets"]
    )
    return {k: _digest(v) for k, v in fields.items()}
```

The combined digest stays derivable (`_digest` of the sorted per-field
digests), so `diff` keeps working unchanged and no field is duplicated on
disk. `diff` then reports `changed_fields` alongside each amended entry,
and `/changes/` can show:

> **Health and Growth Accelerator (HGA) Programme National Evaluation** —
> ONS — `DARS-NIC-788663-G4F2D-v0.2` — *expected measurable benefits,
> end date*

Measured cost, now that it is built: a September 2026 snapshot under the
new rules is 3.2 MB raw and **387 KB gzipped**, against 208 KB under the
old ones. So 1.9x per edition and about 4 MB more across the full
archive — as estimated. That is an
acceptable price for turning "something changed" into "the end date
changed", and it scales: every future edition carries it for free.

It also makes the spikes readable, which §7 shows is the main thing
standing between the "what changed" page and being trustworthy.

One caveat the probe has since added: the *invisible* changes this was
partly justified by did not appear. In both pairs measured, no version
changed only in `controllers` or a dataset attribute — every such change
came alongside a field the fingerprint already sees. The field additions
are still right (a controller change that happens to travel alone would
be missed, and the next months may differ), but they are a correctness
fix at the margin, not the headline. The per-field digests earn their
keep on the cosmetic/substantive split instead.

### R3 — An amendment log, for genuine redline

Field names are enough for a change summary. A redline needs the old
text, and after pruning the old text is gone. So write it at ingest
time, when both editions are briefly in hand, into a small permanent
file:

```
data/amendments/<register>/<edition>.json.gz
```

One entry per amended version, one record per changed field, holding the
previous value and the new one. Only changed fields, only amended
versions — so the file is proportional to the month's churn, not to the
register:

| | Amendments | Rough raw size | Gzipped |
| --- | ---: | ---: | ---: |
| Typical month (15 amendments, ~2 fields each) | 15 | ~90 KB | ~25 KB |
| Worst observed (March 2026) | 122 | ~2.9 MB | ~600 KB |

Even the worst month is smaller than one edition fingerprint. Compare
that with the alternative of raising `editions.DEFAULT_KEEP` to 2, which
costs **32 MB of git history per edition** and still only lets you diff
one month back.

**The probe has weakened the case for the redline half of this.** Across
both pairs measured, not one amendment had a substantive prose change:
every edition-to-edition change to a long free-text field was
typography. The substantive edits were scalar (an organisation renamed)
or list-shaped (datasets added and removed) — before/after pairs, not
redlines. So the log is still worth writing, because a before/after pair
needs the old value just as much as a redline does and the old value is
what pruning destroys. But it should be built for the scalar and list
cases first, and the prose redline treated as a path that may rarely
fire between editions.

Note this says nothing about version-to-version prose, which is a
different question and comes out the other way: 3,370 of 3,663
consecutive version pairs in the September 2026 extract have genuinely
rewritten prose. That case is implemented and needs no stored history.

Mechanics: `ingest` already has the new extract; it needs the previous
edition's to compare against. `ingest.main` already sorts its workbooks
oldest first precisely so each edition diffs against the one before it,
so a whole-archive run has both extracts in hand at the right moment.
Compute the amendment log there, *before* `prune_extracts` runs, holding
the previous edition's extract in memory for exactly one iteration.
`DEFAULT_KEEP` stays at 1 and nothing extra lands in git.

Two cases still need handling. A single monthly ingest has no previous
extract on disk (it was pruned last month), so it either re-extracts the
previous workbook from `data/raw/` when it is there, or writes no log for
that pair and records `"comparable": false` — the per-field digests from
R2 still name the changed fields, only the text is missing. And a skipped
or unavailable edition leaves a genuine gap, which the page should state
rather than paper over.

With the full archive re-ingested in one pass, the log covers all 18
pairs from the start, so this degraded path should be rare.

**Fix `ingest`'s memory use first.** `main` currently accumulates every
extracted workbook in a dict (`extracts[(slug, edition)]`) so it can
write the newest one after the loop. One extract is **393 MB** in memory
(measured, September 2026), so a 19-workbook backfill retains roughly
7.5 GB — survivable on a 16 GB machine and nothing else. Adding the
amendment log on top of that is not. The fix is small and wanted anyway:
process oldest first, keep only the previous edition's extract per
register, and write the full extract when the current edition is the
newest for its register. Peak drops to about two extracts, ~800 MB. Do
this before attempting the backfill, not after discovering it swaps.

### R4 — Rendering: summary by default, redline on request

**Implemented for the version-to-version case** (`pipeline/compare.py`).
The edition-to-edition case still waits on R3's stored history.

Three levels, in increasing cost to the reader:

1. **Field summary** (from R2) — on `/changes/` and in the agreement's
   register history. Always shown.
2. **Before/after pairs** for short, scalar fields (dates, Yes/No flags,
   controller lists, dataset membership). A two-column table reads better
   than a redline for `2027-03-31 → 2028-03-31`, and much better for
   "dataset added: *Civil Registration - Deaths*".
3. **Word-level redline** for the five long prose fields (`objective`,
   `activities`, `expected_output`, `expected_benefits`,
   `yielded_benefits`). These are where a redline earns its keep:
   3,400-character blocks where a single sentence has been rewritten.

For (3), `difflib.SequenceMatcher` over word tokens is in the standard
library — no new dependency, consistent with the project's two-package
`requirements.txt`. Render as semantic `<ins>`/`<del>` inside a
`<details>` block, collapsed by default, with unchanged paragraphs
elided behind a "show unchanged text" summary. Colour must not be the
only signal: keep the strikethrough on `<del>`, keep underline on
`<ins>`, and add `aria-label`s, in keeping with the site's existing
no-JavaScript-required posture. Every diff must be in the HTML; none of
it should depend on script.

The same rendering serves **version-to-version diffs**, which need no new
stored data at all — consecutive versions of one agreement are both in
the current extract. On the agreement page, each version block after the
first gets a "What changed from `v1.0`" `<details>`. This is arguably the
highest-value item in the whole plan relative to its cost, and it can
ship alongside R1 without waiting for R2 or R3.

### R5 — Give in-place amendments their own vocabulary

The register's own model has no concept of an unversioned edit, so the
site has to supply one. Concretely:

- Split the agreement page's current "Version history" into **Version
  history** (new reference numbers) and **Amendments** (same reference,
  changed content), so `DARS-NIC-788663-G4F2D-v0.2` reads as one version
  amended once rather than as an unexplained tag.
- Reword the `/changes/` "Amended" section, which currently says
  "changed in place" only in passing. Lead with it: these are edits NHS
  England made to an existing agreement record without issuing a new
  version, and there is no official changelog for them anywhere. That is
  the site's genuinely novel contribution and it is currently buried
  under "Added".
- Keep the existing `tag-amended` badge but make it a link to the diff.
- Say plainly what an amendment is *not*: the register is a periodic
  publication, so an edit appearing in the September edition means only
  that it was made at some point between the two publication dates.

### R6 — Machine-readable change outputs

The site already publishes flat CSVs. Add, per edition:

- `downloads/changes-<edition>.csv` — one row per changed version:
  `edition, previous_edition, reference, base_reference, organisation,
  change_type, changed_fields, url`.
- `changes/<edition>/changes.json` — the same plus old/new values where
  R3 has them.

This is cheap (both are already-computed structures) and it makes the
month-on-month history citable by other people's tooling, which is the
stated point of the project.

## 5. Suggested sequencing

| Step | State | Value |
| --- | --- | --- |
| Verify the local workbook set against the manifest ([§6](#6-backfilling-the-archive)) | done | Precondition |
| Probe three edition pairs ([§7](#7-what-the-probe-found)) | done | Sized the problem, and changed it |
| R1 register history + R4 version-to-version redlines | **done** | Shipped; needed no new data |
| R3 normalisation, applied to the fingerprint | **done** | Shipped; takes effect on re-ingest |
| R5 vocabulary and page structure | next | High |
| Full re-ingest, to apply the new rules | **done** | 494 amendments across the archive became 297; see §8 |
| `ingest` memory fix | **done** | Peak drops from ~7.5 GB to ~800 MB |
| R2 per-field digests + the missing fields | **done** | Shipped; takes effect on re-ingest |
| R3 amendment log | **next** | Scalar and list first — it is what would say who October 2025's controllers became |
| Full re-ingest of all 19 editions | todo | Restates the whole archive's counts honestly |
| R6 exports | todo | Medium |

The probe reorders this. Normalisation was housekeeping in the first
two drafts and is now the single most valuable change on the list: it is
the difference between the "what changed" page reporting 122 amendments
and reporting 17. Everything else on the page is accurate; that number
is not.

It also demotes the edition-to-edition redline, which was the headline
of the first draft. There was no substantive prose change to redline in
either pair measured. The version-to-version redline, which turned out
to be the case with the real prose rewrites, is already shipped.

## 6. Backfilling the archive

All 19 editions have a manifest entry carrying the SHA-256, byte count
and source URL of the workbook they came from, so the local set can be
verified rather than assumed — `source_file` in the manifest is the
published filename, which is also what `sources.parse_edition` reads. A
mismatch means a re-download, not a re-ingest, and it is worth knowing
before a multi-hour run rather than during it. Worth adding as a
`--verify` flag on `ingest`, or as a few lines in the runbook:

```python
import hashlib, json
from pathlib import Path
for e in json.load(open("data/editions/data-uses-register/manifest.json"))["editions"]:
    f = Path("data/raw") / e["source_file"]
    got = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    print(("ok  " if got == e["sha256"] else "BAD "), e["edition"], f.name)
```

The whole set is 530 MB across 19 files. Nothing about the backfill is
expensive except the extraction itself, which is bounded by openpyxl.

**Probe before building.** *Run — see [§7](#7-what-the-probe-found) for
the results.* One question drove how much of this machinery was worth
writing: were March 2026's 122 amendments substantive, or a bulk
template restatement? The answer is two workbooks away, and it
needs none of the code proposed here — `pipeline/probe.py` is written and
changes nothing:

```bash
.venv/bin/python -m pipeline.probe \
    data/raw/datausesregister_february2026.xlsx \
    data/raw/datausesregister_march2026.xlsx
```

It reports every field that differs for each version present in both
editions, counted twice — as published, and after the normalisation
proposed in §3 — so the cosmetic share can be read straight off. It also
compares `controllers` and the per-dataset attributes, which the current
fingerprint ignores, and counts the amendments that are invisible today.
Its added/amended/removed totals mirror `snapshot.diff` exactly, so the
numbers are comparable with the table in §2. `--show N` prints word-level
redlines for the largest prose rewrites.

Either argument may be a committed extract rather than a workbook, which
loads in a second or so instead of minutes. Two workbooks is about
800 MB of memory.

If most of the 122 are whitespace or punctuation churn, R3's
normalisation is the highest-value item here and the redline renderer is
a nicety. If they are rewritten benefits statements and shifted end
dates, the redline is the point and normalisation is housekeeping. Run
the probe first; it is an afternoon's difference in what gets built.

**What the backfill yields.** Across the 18 edition pairs there are 494
amended versions. Storing old and new text for changed fields only — at
the observed mean of 23.7 KB of fingerprinted text per version, and
assuming two or three changed fields per amendment — puts the whole
historical amendment log in the low single-digit megabytes gzipped, in
the same order as the fingerprints already committed. Every one of those
494 edits becomes a readable redline on the agreement page it belongs
to, including whatever NHS England did to 122 agreements in March 2026,
which is currently the largest unexplained event in the register's
recent history and the kind of thing this site exists to surface.

**What is still unrecoverable.** Editions published before March 2025.
The site's history starts where NHS England's release archive does, and
no amount of local storage changes that. Anything the register itself
overwrote between two publication dates is also gone — an agreement
edited twice in one month shows as one amendment, because a monthly
snapshot cannot see inside the month. Worth stating on the page:
amendments are attributed to the edition they first appear in, not to the
date the edit was made.

## 7. What the probe found

Run on 19 September 2026 against the workbooks, with `pipeline.probe`.

### February 2026 → March 2026 — the 122-amendment spike

```
added        25     amended  122     removed  0
  substantive after normalising    17
  cosmetic only                   105   (86% of the amendments)
  controllers or dataset attributes only   0

field              as published  normalised  fingerprinted
expected_benefits            67           0  yes
expected_output              19           0  yes
controllers                  17          17  NO — proposed
organisation                 17          17  yes
title                        10           0  yes
activities                    6           0  yes
objective                     5           0  yes
yielded_benefits              3           0  yes
```

Every prose field normalises to zero. All 105 cosmetic amendments are
typography — punctuation, spacing or case — in text whose meaning did
not move. What did happen is narrower and more interesting than the
headline: 17 versions changed `organisation` *and* `controllers`, the
same count in both, which reads as an organisational rename carried
across both fields rather than 17 unrelated edits.

So the register's largest recent "change" event is a formatting pass
over roughly a hundred agreements plus one rename. The site currently
presents that as 122 amendments.

### June 2026 → July 2026 — a different shape entirely

```
added        59     amended   15     removed  0
  substantive after normalising    12
  cosmetic only                     3   (20% of the amendments)
  controllers or dataset attributes only   0

field               as published  normalised  fingerprinted
dataset_attributes            15          12  NO — proposed
dataset_names                 12          12  yes
expected_output                3           0  yes
```

Here the amendments are real and they are all about datasets: which
datasets an agreement covers, and their recorded attributes. No prose
was substantively touched in either month.

### What follows from it

1. **Normalisation is the highest-value change in this plan**, not the
   housekeeping item the first two drafts called it.
2. **Spikes and ordinary months differ in kind, not degree.** March is
   a reformatting pass; July is dataset churn.
3. **The edition-to-edition prose redline has little to show.** Neither
   pair contained one substantive prose change.
4. **The blind spots looked marginal.** No amendment in either pair was
   invisible to the fingerprint of the day.
5. **Two pairs are not eighteen.** Both conclusions above rest on a
   sample of two.

Point 5 turned out to matter, and point 4 was wrong. See §8.

### Version-to-version, for contrast

Measured directly on the September 2026 extract while implementing R1
and R4, across all 3,663 consecutive version pairs:

| | Pairs |
| --- | ---: |
| With any change | 3,651 |
| With substantively rewritten prose | 3,370 |
| With a changed scalar field | 3,606 |
| With changed datasets or controllers | 1,189 |

The contrast is the point. Between *editions* the prose barely moves;
between *versions* of an agreement it is rewritten nine times out of
ten. The redline belongs on the version history — where it now is — and
the edition comparison needs a change summary far more than it needs a
redline.

## 8. What the re-ingest found

The archive was re-ingested under rules v3 on 19 September 2026: every
edition re-fingerprinted with normalised text, data controllers and
dataset attributes included, and a digest per field. The table below is
computed from the committed snapshots alone — no workbook needed, which
is what the per-field digests bought.

| Edition (vs previous) | Was | Now | Δ | Dominant fields |
| --- | ---: | ---: | ---: | --- |
| April 2025 | 2 | 3 | +1 | controllers, output, objective |
| May 2025 | 0 | 0 | — | |
| June 2025 | 3 | 3 | — | applicant organisation 3 |
| July 2025 | 41 | 60 | +19 | **controllers 51**, organisation 39 |
| August 2025 | 1 | 6 | +5 | controllers 4 |
| September 2025 | 0 | 0 | — | |
| October 2025 | 52 | **154** | **+102** | **controllers 135**, organisation 37, datasets 14 |
| November 2025 | 16 | 16 | — | datasets 15 |
| December 2025 | 2 | 6 | +4 | controllers 6 |
| January 2026 | 0 | 0 | — | |
| February 2026 | 72 | **0** | **−72** | |
| March 2026 | 122 | **17** | **−105** | organisation 17, controllers 17 |
| April 2026 | 1 | 1 | — | end date 1 |
| May 2026 | 73 | **1** | **−72** | |
| June 2026 | 73 | **0** | **−73** | |
| July 2026 | 15 | 12 | −3 | datasets 12 |
| August 2026 | 20 | 17 | −3 | organisation 15, controllers 10 |
| September 2026 | 1 | 1 | — | datasets 1 |
| **Total** | **494** | **297** | **−197** | |

### The net figure hides two opposite movements

**340-odd amendments disappeared**, and they were the spikes. February,
May and June 2026 fall to nothing at all; March 2026 falls from 122 to
17, matching the probe's prediction almost exactly. Four of the five
largest "change events" in the site's history were reformatting passes.

**131 appeared**, and these are the interesting half. They are changes
the register made and the old fingerprint could not see.

### Correction: the blind spots were not marginal

§7 concluded from two edition pairs that the missing fields were "real
but not urgent", since neither pair contained an amendment invisible to
the fingerprint of the day. Across all eighteen pairs, **130 amendments
were a change of data controller and nothing else** — invisible, in a
register whose whole purpose is recording who holds patient data. The
two pairs probed happened to be the wrong two. The sample was flagged as
thin at the time; it was thinner than it looked.

### October 2025

One edition accounts for most of it. Its 154 amendments break down as:

| | Count |
| --- | ---: |
| Data controllers alone | 101 |
| Data controllers *and* applicant organisation | 34 |
| Datasets | 14 |
| Applicant organisation alone | 3 |
| Prose (benefits) | 2 |

135 agreements had their data controller changed in a single month,
across 29 organisations, concentrated in NHS England — X26 (39), the
Royal College of Physicians of London (18) and the National Institute
for Cardiovascular Outcomes Research (10). No version numbers were
issued and no changelog was published. Under the old rules the site
reported 52 amendments that month, none of them about controllers.

This is the largest finding the project has produced, and it is exactly
the class of change the register makes hardest to see: an edit in place,
to the field that says who holds the data, across a hundred-odd
agreements at once.

**What this cannot yet say is what the controllers changed *to*.** The
snapshots hold digests, not values, so the site can say that a
controller changed and not how. Answering that needs either R3's
amendment log or a probe run over the September and October 2025
workbooks — which is now the most interesting thing left to do, and
argues for building R3's log for the scalar and list cases first, as §4
already concluded for a different reason.

## 9. Making data-controller changes visible, with from and to

§8 established that a change of data controller is the most common
amendment in the archive — 130 of them invisible until the rules
changed, 135 in October 2025 alone — and the one the site is least able
to explain. It can now say *that* the controller changed. It cannot say
from whom, to whom. Snapshots hold digests, and a digest is not
reversible.

This section recommends the cheapest fix, which turns out to be much
cheaper than the amendment log proposed in R3.

### R7 — Store values for short fields, digests for long ones

The reason the snapshot holds digests is prose. Measured on the
September 2026 edition, stored per version:

| Stored | Raw | Gzipped | On a 426 KB snapshot |
| --- | ---: | ---: | ---: |
| Controllers alone | 404 KB | **46 KB** | +11% |
| Controllers + the short scalar fields | 1.0 MB | 92 KB | +22% |
| Both, plus dataset names | 2.7 MB | 144 KB | +34% |
| The five prose fields | 128 MB | **21 MB** | +5,000% |

Prose is roughly 150 times the cost of everything else put together.
That is why the snapshot hashes rather than stores — and it is an
argument for hashing *prose*, not for hashing the fields people
actually want to read. Controllers cost 46 KB an edition, about
870 KB across the whole archive: less than a fifth of what the
per-field digests already added, for the answer to the question §8
raised.

So: keep digests for the five prose fields, and store the values of the
short ones — controllers first, then the scalars and dataset names if
they prove as useful.

Interning the names into a lookup table was measured too. There are 587
distinct controller names across 7,305 entries, so the raw saving is
large (404 KB to 217 KB) and the compressed saving is not (46 KB to
41 KB): gzip already exploits the repetition. Store them inline and
skip the indirection.

**Why this beats R3's amendment log for this purpose.** The log records
what changed *between* two editions, so writing it needs both extracts
in hand at ingest, which is what forced the ordering and pruning
constraints in R3 and the memory fix that preceded it. Stored values
need none of that: each edition's snapshot is independently meaningful,
any two can be compared at any time, and the whole archive backfills
with the re-ingest that is now routine. It also answers questions the
log cannot, because the log only holds the versions that changed —
"who were the controllers on this agreement in March 2025" is a
question about an edition, not about a change.

R3 remains the only way to get from-and-to for *prose*. Given §7 found
no substantive prose change between editions in either pair probed,
that is a narrower prize than it looked, and R7 should come first.

### What it makes possible

1. **On the agreement page.** The register history already names the
   changed field; with values it can show the change itself, in the
   same added/removed form `compare_versions` already produces for
   version-to-version dataset changes:

   > **October 2025** — Amended `DARS-NIC-139035-X4B7K-v10.2`
   > Data controllers: **+** UNIVERSITY OF SHEFFIELD · **−** NHS DIGITAL

2. **On the changes page.** The "what changed" column becomes the
   change, not the field name, for short fields.

3. **An organisation-level view, which is the one that matters.** On an
   organisation page: the agreements where this organisation was added
   or removed as a controller, and in which edition. That is what makes
   October 2025 legible — not 135 separate agreement pages, but one
   page saying what NHS England — X26 took on that month. It needs
   nothing beyond the stored values and the history index that already
   exists.

4. **A controller-change feed** at `/changes/controllers/`, across all
   editions rather than one pair. The register's least visible and most
   consequential field deserves its own page, and the archive now has
   eighteen editions of history to fill it.

### Three things to get right

**A rename is not a transfer.** Controller names drift in spelling, and
the alias work already on `main` exists precisely because of it.
Compare and group by canonical slug through `aliases.resolve`, but
display the raw text: "NHS DIGITAL" becoming "NHS ENGLAND" is a
renaming, and showing it as one organisation replacing another would be
wrong. These should carry different labels on the page — *renamed*
against *added* and *removed* — and the rename case should probably not
count as an amendment at all, which is the same argument normalisation
already won for typography.

**Attribution is to an edition, not a date.** An edit appearing in the
October 2025 edition happened at some point between two publication
dates. The page says this already; it matters more when the sentence is
"these 135 agreements changed hands in October 2025", which is a claim
a reader may repeat.

**The register records the field, not the reason.** A controller change
may be a transfer, a restructuring, or the correction of a data-entry
error made three years earlier. The site should report the change and
resist narrating it — the same discipline the existing caveats apply to
expected benefits.

### Before any of this

The probe answers October 2025 today, from two workbooks and no new
code:

```bash
.venv/bin/python -m pipeline.probe \
    data/raw/datausesregister_september2025.xlsx \
    data/raw/datausesregister_october2025.xlsx
```

It names the amended versions and their changed fields, and tallies the
departures and arrivals for controllers and datasets across the whole
edition — so a hundred agreements renamed from one organisation to
another collapse into one row, while genuine one-off transfers stand
apart at a count of one. That distinction decides which half of R7 is
the feature: if October 2025 is one organisation renamed, the rename
handling matters and the from-to display is a detail; if they are
transfers, it is the other way round.

The probe has since been run over that pair, with the transition
tally. It answers the question.

### October 2025 was a relabelling, not a transfer

135 controller changes, and **three distinct changes** between them:

```
    126 ×   − NHS ENGLAND (QUARRY HOUSE)
            + NHS ENGLAND - X26

      7 ×   − CITY
            − UNIVERSITY OF LONDON
            + CITY ST GEORGE'S UNIVERSITY OF LONDON

      2 ×   − BCP COUNCIL  [BOURNEMOUTH
            − CHRISTCHURCH AND POOLE]
            + BCP COUNCIL  (BOURNEMOUTH, CHRISTCHURCH AND POOLE)
```

No agreement changed hands. NHS England relabelled itself from its Leeds
building to its organisation code on 126 agreements; City, University of
London became City St George's after its merger with St George's; and
BCP Council swapped square brackets for round ones. The 13 dataset
changes in the same edition are the same kind of thing — NICOR audits
losing their version suffixes, so "NICOR Heart Failure V5_Full" becomes
"NICOR Heart Failure".

That settles what §7 and §9 could not. **The rename handling is the
feature and the from-and-to display is the detail.** The largest
apparent governance event in the register's recent history is an
editorial pass, and the site would currently report it as 154
agreements amended.

It also strengthens the case for resolving through the alias map before
counting: NHS England — X26 and NHS England (Quarry House) are one
organisation, so 126 of those amendments are cosmetic at the level a
reader cares about, exactly as the March 2026 typography was. The
difference is that normalisation catches typography automatically,
while this needs a human-reviewed alias. Two of the three changes here
are already candidates `orgcheck` would surface.

**A caveat on the middle row, which is a bug in this repository rather
than a change in the register.** "CITY, UNIVERSITY OF LONDON" and "BCP
COUNCIL [BOURNEMOUTH, CHRISTCHURCH AND POOLE]" are single organisations
whose names contain commas. `extract.split_list` treated those commas
as list separators, so the *before* side of both rows is an artefact of
our own parsing: the register never named an organisation "CITY" or
"CHRISTCHURCH AND POOLE]". The square-bracket case is now fixed. The
comma-inside-a-name case is not fixable by bracket rules and still
produces phantom controllers — "INC", "INC." and "INC. UNITED KINGDOM"
across 15 versions of the current edition, from names like "MCKINSEY &
COMPANY, INC. UNITED KINGDOM". That wants either a corporate-suffix
exception in the splitter or an alias, and either changes controller
values, so it should ride a re-ingest.

### What to build now

1. **Resolve controllers through the alias map before calling something
   an amendment.** A relabelling is not a change of controller, and on
   the evidence it is the common case. This is the single highest-value
   item left.
2. **Store the values** (R7) — still right, and now clearly for the
   rename display as much as for transfers: "NHS England (Quarry House)
   → NHS England — X26" is a useful thing for a page to say, provided it
   is labelled a renaming.
3. **Fix the remaining splitter artefact**, so the register's own
   organisation names survive parsing.

An honest note for the site: on this evidence the register's in-place
amendments are, so far, overwhelmingly editorial — typography,
relabelling, and dropped version suffixes. That is worth saying plainly
rather than implying a governance event every time a field moves. It
also makes the rare substantive amendment much easier to spot, which
was the point.

## 10. What five years changed

The archive was extended back to July 2021 — 63 editions, 61 comparable
pairs, re-ingested under rules v4. Every conclusion in §2 and §8 was
drawn from the 19 editions available at the time, and two of them do
not survive the longer window.

| | Five years (61 pairs) | Of which 2025–26 (19 pairs) |
| --- | ---: | ---: |
| Added | 3,037 | 1,006 |
| Amended | 6,742 | 302 |
| Removed | **106** | 0 |

### Removal happens, and it is concentrated

§2 said nothing is ever removed. Across five years, 106 agreement
versions left the register:

| Edition | Removed |
| --- | ---: |
| February 2023 | **83** |
| August 2022, May 2023 | 4 each |
| January 2023, July 2023, October 2023, August 2024, October 2024 | 2 each |
| April 2022, May 2022, October 2022, December 2022, March 2024 | 1 each |

February 2023 dropped 83 versions in one month while adding 56. That is
the event the "No longer listed" section was built for and never had
occasion to show, and it happened two years before the window §2 looked
at. The recommendation in §2 — keep the section, do not give it equal
visual weight to a bucket with a hundred entries — was right for the
wrong reason. Removal is rare and clustered rather than absent, which
is a better argument for keeping the section than the one originally
given.

### The amendment history is not where we were looking

302 of the 6,742 amendments are in 2025–26. Four consecutive editions
hold three quarters of everything:

| Edition | Amended |
| --- | ---: |
| January 2023 | 2,455 |
| December 2022 | 1,192 |
| October 2022 | 881 |
| November 2022 | 540 |
| September 2021 | 448 |
| August 2021 | 388 |

October 2022 to January 2023 is 5,068 amendments — 75% of five years,
on a register of roughly 1,450 agreements. Most agreements in the
register were restated more than once in those four months.

These counts are already normalised, so unlike March 2026 they are not
typography. The probe has since been run over the largest pair, and
the answer is the same shape as October 2025.

### January 2023 was a dataset relabelling

2,455 amendments, and every one is a dataset name gaining its acronym:

```
  Hospital Episode Statistics Admitted Patient Care
    -> Hospital Episode Statistics Admitted Patient Care (HES APC)
  Civil Registration - Deaths
    -> Civil Registrations of Death
  GPES Data for Pandemic Planning and Research (COVID-19)
    -> COVID-19 General Practice Extraction Service (GPES) Data for
       Pandemic Planning and Research (GDPPR)
```

Nothing changed hands, no dataset was added to an agreement, and no
purpose was rewritten. NHS England restyled its dataset names and the
site recorded it as the largest event in the register's history —
three quarters of five years of amendments, from one editorial pass.

So the pattern established in §9 for organisations holds for datasets
too, and more strongly. Of the five largest amendment events in the
archive, four are now known to be editorial: March 2026 typography,
October 2025 organisation relabelling, January 2023 dataset
relabelling, and by inspection the October–December 2022 editions
leading into it, which show the same dataset transitions part-applied.

**This changed the tool, not just the conclusion.** The probe first
reported January 2023 as "193 distinct changes", because it tallied
whole-set transitions: the same twenty-odd renames appeared once per
distinct combination of datasets an agreement happened to hold. Renames
are now found per name, and the same edition reads as roughly twenty
renames with nothing else.

Finding them cannot be done by comparing how alike two names look.
"Mental Health Minimum Data Set" and "Mental Health Services Data Set"
are 79% alike and are different datasets; the GPES pair above is 62%
alike and is one. What separates them is behaviour: a renamed dataset
disappears from the edition entirely while something else appears on
exactly the agreements it used to be on, whereas two datasets that
merely read alike both carry on existing.

### Datasets need the alias treatment organisations have

`data/organisation-aliases.json` and `orgcheck --renames` exist because
organisations get relabelled. Datasets get relabelled more, and they
have none of that machinery. Nothing records that "Civil Registration
- Deaths" and "Civil Registrations of Death" are one dataset, entitled
to one page and one history.

The same three pieces would do it — an alias file, resolution at build
time, and a reviewed workflow fed by the rename detection that now
exists. The evidence for each candidate is stronger than for
organisations, because a dataset rename shows up as a clean
disappearance-and-appearance across hundreds of agreements at once
rather than as two similar strings sitting side by side.

Until that exists, the register's dataset pages silently split a
dataset's history at each rename, and any count of "agreements using
HES APC" covers only the editions since it was called that.

### A gap in the archive

There is no January 2025 edition: the sequence goes December 2024 to
February 2025, and the February comparison therefore covers two months.
Either NHS England did not publish that month or the workbook was not
downloaded. The site attributes every change to the edition it first
appears in, so February 2025's 93 additions and 3 amendments silently
include January's. Worth either finding the workbook or noting the gap
on the changes page, since a reader has no way to see it.

### What the comma fix did

The v4 re-ingest dropped the September 2026 organisation count from 640
to 637 — exactly the three phantoms that `split_list` had been
inventing from "MCKINSEY & COMPANY, INC. UNITED KINGDOM". No amendment
count in 2025–26 moved, so those controller strings had been stable
across editions: the bug was creating false organisations rather than
false changes.

### Scale

63 editions cost about 25 MB of snapshots and a 29-second build, which
is what the 19-edition build cost before `history_index` stopped
re-reading the archive. The January 2023 changes page carries 2,455
rows at 778 KB, or 70 KB gzipped as served. Both are fine; neither has
much headroom left, and a register that keeps growing will need the
per-edition pages paginated or trimmed eventually.
