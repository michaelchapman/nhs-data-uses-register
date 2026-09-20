# Plan: store the facts, derive the rest

Status: **accepted, in progress.** Step 1 of §6 is implemented
(`pipeline/facts.py`); nothing is wired to the site yet.

This supersedes the storage half of
[plan-version-diffs.md](plan-version-diffs.md) — the fingerprint snapshots and
their rule versions — and extends the store designed in
[plan-local-edition-archive.md](plan-local-edition-archive.md) from one edition
to all of them. The monthly routine in [manual-updates.md](manual-updates.md)
is unaffected until step 6.

## 1. The problem, stated once

Every rules change so far has cost a full re-parse of 63 workbooks, about two
hours, because **what is committed is a derivative of the rules rather than a
record of the facts.**

The symptoms have been treated one at a time:

| Symptom | Treatment | Still true |
| --- | --- | --- |
| Reformatting reported as amendments | normalise text before hashing (v5) | fingerprints must be rewritten to change the rule |
| A relabelled dataset reported as an amendment everywhere | apply aliases at comparison time (v6) | only datasets; a bespoke mechanism per field |
| Gzip defeats git delta compression | (proposed) plain JSONL | every rules change still rewrites the whole archive |
| Editions under different rules cannot be compared | `FINGERPRINT_VERSION` gate, "cannot be compared" notice | a gap on the site whenever the rules move |

v6 is the right instinct — never bake the rules into what you store — applied
to one field. This plan applies it to all of them.

## 2. What the archive actually contains

Measured on 2026-09-20 against the 63 committed snapshots, which record every
version present in every edition:

| Measure | Value |
| --- | --- |
| Editions held | 63, July 2021 – September 2026, no gaps |
| Workbooks on disk, SHA-256 in the manifest | 63 of 63 |
| Version-entries summed across all editions | 263,342 |
| Distinct (agreement, version) references ever | **5,702** |
| Distinct agreements ever | 1,979 |
| Versions in the newest edition alone | 5,613 |
| Mean editions a reference appears in | 46.2 |
| References that ever vanish and return | 15 |
| Distinct (reference, content-state) records | **12,439** (mean 2.18 per reference) |

Reproduce with:

```bash
.venv/bin/python - <<'EOF'
import gzip, json, collections
from pathlib import Path
from pipeline import sources
files = sorted(Path("data/snapshots/data-uses-register").glob("*.json.gz"),
               key=lambda p: sources.edition_sort_key(p.name.split(".")[0]))
states = collections.defaultdict(set)
for f in files:
    for ref, e in json.loads(gzip.open(f).read())["versions"].items():
        states[ref].add(json.dumps(e.get("hashes") or e.get("hash"), sort_keys=True))
print(len(states), "references,", sum(map(len, states.values())), "content-states")
EOF
```

Two things follow.

**The newest edition holds 5,613 of the 5,702 references that have ever
existed.** Over five years the register has dropped 89. It is very nearly
append-only, and the history we are paying to compress is mostly the present
restated 46 times.

**The content-state count is the real size of history: 12,439 records,
2.2× the newest edition** — and the extra records are near-duplicates of the
ones they follow, which is the case git deltas handle best. The 2.18 average is
measured under v5 rules, so it includes the dataset relabelling that v6
discounts; it is an upper bound on what a reader would call a change, but it is
the right number for storage, because the workbook really did say something
different.

### What that costs today

| Path | Working tree | Packed in git |
| --- | --- | --- |
| `data/editions` — full text, **one** edition | 153 MB | 20.6 MB |
| `data/snapshots` — lossy digests, **all 63** editions | 20 MB | 19.8 MB |

The full text of one edition costs about what the fingerprints of the entire
archive cost. The fingerprint store exists to avoid storing history and is not
saving anything.

## 3. Options

**A. Keep fingerprints, drop gzip.** Plain one-version-per-line JSON: the
archive falls from 20 MB to about 1 MB packed and a rules change costs about
2 MB instead of 20 MB. But every rules change still means re-parsing 1.3 GB of
workbooks, and the `FINGERPRINT_VERSION` gate stays.

**B. Store the facts, derive everything.** One record per (agreement, version,
content-state), with the comparison rules moved into the build, so nothing
stored can gate a comparison. A rules change costs a rebuild of seconds.
**Recommended.**

**C. Timeline / runs.** The compact form: 263,342 entries collapse to 13,950
runs, 17 MB of working tree, 4.1 MB packed. Real, but it is an optimisation of
B that trades diff readability for size. Hold it in reserve.

**D. Releases or Git LFS.** Smallest repo, but no reviewable diffs, extra auth
and quota, and `clone && build` stops working.

**E. Committed SQLite.** Compact and queryable, but binary — the objection that
ruled out gzip. Better as a build output on the downloads page than as a store.

## 4. Recommendation: B

The original argument for fingerprints was size. §2 shows history is 2.2× the
current edition and near-duplicate, so the argument does not hold.

Estimated cost, **and this is an estimate, not a measurement**: about 340 MB of
working tree (12,439 records at the 27 KB/record the current extract averages),
and roughly 30–40 MB packed against the 40 MB committed today. Step 4 below
checks this before anything is committed; if it comes out badly, C is the
fallback and the stored facts are still correct.

What it deletes: `FINGERPRINT_VERSION` and its gates, the gzip reader, the
digest machinery in `snapshot.py`, and the "cannot be compared" gap. Of 4,275
pipeline lines, `snapshot.py` and `compare.py` are 886.

What it gives: a rules change, a new alias, a new derived field, or a bug fix in
`extract` becomes a rebuild rather than a re-parse. Field-level history for the
whole archive, which [plan-version-diffs.md](plan-version-diffs.md) lists as
R3 and R7 "not started", becomes available without new storage.

## 5. The record

```
data/facts/<register>/
  agreements/<slug>.json   1,979 files: every version, and every state it held
  releases/<slug>.json     when files were released, and which edition said so
  editions/<edition>.json  63 files: which state of which version that edition had
  manifest.json            per-edition workbook checksum, as now
```

An agreement file is today's file with one level added — a version holds the
list of distinct states it has been published in, oldest first:

```json
{
 "base_reference": "DARS-NIC-1-AAAAA",
 "versions": [
  {"version": "1",
   "reference": "DARS-NIC-1-AAAAA-v1",
   "states": [{"title": "Maternity study", "…": "…"},
              {"title": "Maternity study (revised)", "…": "…"}]}
 ]
}
```

An edition file names the state each version was in that month:

```json
{"edition": "april2022",
 "versions": {"DARS-NIC-1-AAAAA-v1": 0, "DARS-NIC-1-AAAAA-v2": 1}}
```

Four properties make this cheap and safe:

- **Append-only.** States are appended in first-seen order, so an index, once
  written, always means the same record. A month's ingest touches only the
  agreements whose text actually changed.
- **Nothing is deleted.** An agreement that leaves the register keeps its file
  and simply stops appearing in edition indexes. This is the difference from
  `editions.write_extract`, which deletes, and it is how history survives.
- **A state is a distinct stored record, not a rules verdict.** States are told
  apart by exact equality of the canonical JSON. There is no normalising, no
  hashing and no version to gate on. Whether a difference counts as an
  *amendment* is a question the build answers, and it can change its mind
  freely.
- **Edition files delta well.** Consecutive editions differ in roughly a
  hundred of 5,613 lines.

Storage canonicalises one thing: a version's `datasets` are sorted by name.
Row order in the workbook carries no meaning for a set of datasets, and
storage should not be sensitive to it — a reshuffled sheet should not read as
an amendment to every agreement on it. Everything else is stored as `extract`
produced it.

This has one visible consequence. 315 of the 1,950 agreements in the September
2026 edition list their datasets in some order other than by name, so their
agreement pages will show them alphabetically instead of in sheet order. That
looks like the better order anyway, but it is a change to the site and not only
to the store.

### File releases are kept apart, because they move every month

A version's text is fixed once published, but its file releases are not: the
register appends to them monthly by design. The fingerprints already excluded
them for that reason —

> `releases` and `files_released` stay out on purpose. They move every month by
> design, and folding them in would mark most of the register amended every
> edition, which is the same failure as counting typography.

— and a facts store that held them inside a version's state would be worse than
a fingerprint that counted them: it would append a fresh copy of that
agreement's *whole prose* every month, for a counter. Measured between the
August and September 2026 editions:

| Measure | Value |
| --- | --- |
| Release rows in the workbook | 104,451 |
| References with any releases | 2,330 |
| References whose releases changed in one month | **211** |
| Distinct (reference, dataset, month) cells | 41,370 |
| Cells that shrank or vanished between the two editions | **0** |

211 a month across 62 edition boundaries is roughly 13,000 extra states, about
doubling the store. It would also have invalidated §2: the 12,439 figure is
measured from fingerprints that exclude releases, and is only the right number
for storage if the states exclude them too.

So releases are stored once, per agreement, as the count of files released each
month and the first edition that reported it:

```json
{"reference": "DARS-NIC-1-AAAAA-v2", "dataset": "MSDS …",
 "opt_outs_applied": "Yes",
 "months": [["2022-01", 3, "april2022"], ["2022-02", 1, "may2022"]]}
```

`read_edition` replays this up to the edition being read, so an edition shows
the release history it actually had rather than everything known since, and
`files_released` becomes derived like every other total. A month whose count is
later reported differently appends a second observation rather than overwriting
the first; that has not been seen, but silently overwriting a fact is not
something to leave to luck.

This also stops throwing information away. `extract` reduced 104,451 rows to
8,449 summaries holding only a count and a first and last month; keeping the
per-month counts costs 41,370 entries and 5.9 MB for the whole archive, because
release history is cumulative and the newest edition already contains nearly
all of it. A release timeline on the site becomes possible without another
parse — and **step 4 is the only cheap chance to capture it**, since adding it
afterwards means parsing 63 workbooks again.

### Checked against the real editions

The September 2026 extract — 1,950 agreements, 5,613 versions — records and
reads back identical field for field, apart from the dataset ordering above, in
4.5 s and 0.8 s.

Then both the August and September 2026 workbooks were parsed and recorded in
order. Both round-trip identically, and the second edition shows the shape the
whole design turns on:

| September 2026, on top of August | Value |
| --- | --- |
| Versions | 5,613 |
| New states | **37** — 36 of them new versions, so one genuine in-place edit |
| Agreement files rewritten | 36 of 1,950 |
| New release months | 369, across 211 release files |

Two editions occupy 149 MB of agreements, 5.9 MB of releases and 384 KB of
indexes. At 26.7 KB a state, the 12,439 states of the full archive come to
about 332 MB, plus 12 MB of indexes and the 5.9 MB of releases — close to the
§4 estimate, and still to be confirmed packed at step 4.

## 6. Steps

The expensive step is parsing 63 workbooks, and it is needed under every
option, so the store shape is settled before it runs and the parse happens
once.

1. **The record, reader, release store and edition index,** against fixtures
   and two real editions. No callers.
2. **`ingest` writes facts.** Keep the gzip snapshot reader so the site still
   builds from the old store.
3. **Move the rules into the build.** `changes` derives amendments and the
   per-agreement timeline from the facts, at build time, under the alias files
   as they are now. v6's alias handling survives in `compare`; its storage half
   falls away. *Done.*

   `run` still reads the fingerprints, because the facts store is empty until
   step 4 and a half-populated store would build a half-wrong site. The
   switch-over belongs with the parse that makes it possible, so it moved into
   step 4.
4. **One full parse** of all 63 workbooks, then point `run` at `changes`.
   Check `git gc` size against the §4 estimate before committing anything.
5. **Verify against the current site**: page counts, amendment counts, and the
   cases already known — March 2026 should fall from 122 to about 17, and
   October 2022 (881) and January 2023 (2,455) should fall sharply.
6. **Delete `snapshot.py` and `data/snapshots`** in their own commit, once the
   site is verified.
7. **Push once**, code and data together.

The v6 fingerprint work is not committed as its own step: committing the
intermediate form would mean a re-parse to reach it and another to leave it.

## 7. What is lost

The gzipped snapshots stay in the history from the last push, about 20 MB,
unless a second `filter-branch` removes them. Not worth it.

Editions before July 2021 are not in NHS England's archive, so the facts store
starts where the workbooks do. Nothing about the design assumes otherwise: an
older edition found later is appended like any other.
