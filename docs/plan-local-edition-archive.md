# Plan: back out of live fetching, build from a local edition archive

Status: **accepted (Option B), implemented, then extended.** The decision to stop
fetching and commit the input stands. What is committed has since changed from
the newest edition's extract plus a digest per edition to the text of every
edition; see [plan-facts-store.md](plan-facts-store.md). The monthly routine is
in [manual-updates.md](manual-updates.md); this document records why the site
stopped fetching.

## 1. What is actually broken

Every run of `Build and deploy` has failed — four out of four:

| Run | Trigger | Date | Result |
| --- | --- | --- | --- |
| 1 | push to `main` | 2026-08-28 | `HTTP Error 403: Forbidden` |
| 2 | manual (branch with browser-shaped headers + 403/429/503 retry) | 2026-08-28 | `HTTP Error 403: Forbidden` |
| 3 | schedule (5th) | 2026-09-05 | `HTTP Error 403: Forbidden` |
| 4 | schedule (12th) | 2026-09-12 | `HTTP Error 403: Forbidden` |

The failure is in `pipeline/sources.fetch`, on the very first request — scraping
the landing page, before any workbook download.

This is not a bug in our code and not a rate limit. `digital.nhs.uk` sits behind
a WAF that refuses requests from datacentre address space. Checked from this
container:

```
GET /services/data-access-request-service-dars/data-uses-register   -> 403
  ... with the project User-Agent                                   -> 403
  ... with a default curl User-Agent                                -> 403
GET .../datausesregister_july2026.xlsx  (the asset itself)          -> 403
```

Run 2 already tried the obvious mitigation — full browser headers plus a
backoff-retry — and still got 403. So the remaining automated options are all
forms of evasion (residential proxy, headless browser, third-party mirror) or
depend on NHS England allow-listing us. None is worth it for a monthly file that
a person can download in one click from a normal browser, where the site serves
fine.

**Conclusion: stop trying to fetch. Make the register a committed input, and
add new editions by hand.** That is what the rest of this document plans.

## 2. What we have to work with

- NHS England publishes the current register **and an archive of previous
  editions** on the same landing page. That archive is the backfill: it gives us
  real month-on-month history from day one instead of accumulating it from the
  first successful CI run onwards.
- `data/snapshots/data-uses-register/july2026.json` — one edition fingerprint
  (5,546 agreement versions, 1.1 MB) from a local run, already committed.
- The pipeline itself is sound. `extract.py`, `build.py`, `snapshot.py` and the
  templates need almost no change; only where the bytes come from changes.

> Unverified: the exact shape of the archive section (how many editions, the URL
> pattern, whether older ones are grouped per year) cannot be checked from here —
> everything on `digital.nhs.uk` returns 403 to this container. Step 0 of the
> work below is a human opening the page in a browser and telling us. The plan is
> written so nothing depends on guessing it.

## 3. The real design question

Backing out of live fetching is easy. The question it forces is: **what does
GitHub Actions build from?** If the workbooks are not in the repo and CI cannot
download them, CI cannot build the site at all. Four answers:

### Option A — commit the workbooks via Git LFS

Drop `datausesregister_<month><year>.xlsx` into the repo, tracked by LFS. CI
checks out and builds exactly as today, minus the download.

- Byte-exact source retention; perfectly reproducible; the repo *is* the archive.
- 29 MB per edition. GitHub's free LFS allowance is 1 GB of storage and 1 GB of
  bandwidth a month — ~34 editions of storage, and roughly one CI build per
  month before the bandwidth allowance bites. A two-year backfill spends most of
  the storage on day one.
- Contributors need `git lfs` installed to get a usable checkout.

### Option B — commit a compact derived extract, keep workbooks local (recommended)

A new `pipeline.ingest` step reads a workbook you downloaded by hand and writes
two committed artefacts:

- `data/snapshots/<register>/<edition>.json.gz` — the existing fingerprint, for
  the change log and the editions timeline. ~1.1 MB raw, roughly 150–250 KB
  gzipped.
- `data/editions/<register>/<edition>.json.gz` — the **full** normalised extract
  (`agreements` / `organisations` / `datasets`), enough to render the whole site
  with no workbook present.

Crucially, **only the current edition needs a full extract**. The site renders
one edition; older editions are only used for "what changed" and the timeline,
and a fingerprint is all those need. So the steady state is one full extract plus
a growing tail of small fingerprints — the backfill costs ~200 KB an edition, not
29 MB.

- Repo stays small; no LFS; plain `git clone` works; CI builds offline.
- The xlsx is not retained byte-for-byte. Mitigated by recording its SHA-256,
  filename, source URL and publication month in a manifest, so any copy can be
  verified against what we ingested.
- Re-running an old edition through a changed `extract.py` needs the workbook
  again (keep the downloads in `data/raw/`, or re-download from the archive).

### Option C — build locally, commit `_site/`, let CI only deploy

- Simplest conceptually, no ingest layer at all.
- ~1,900 agreement pages re-committed every month is far more git churn than
  Option B's 200 KB, and it makes the repo's contents output rather than input.
- Rejected.

### Option D — keep fetching, from somewhere reachable

Wayback Machine, the UK Government Web Archive, `data.gov.uk`, or a residential
proxy. Adds a dependency on a third party's coverage of a 29 MB binary, or on
evading a block the publisher put there deliberately.

The National Archives copy was checked directly, at
`webarchive.nationalarchives.gov.uk/ukgwa/20250327085227/…/release-register-archive`.
It is not a way round the block:

- The page returns **HTTP 405 with an AWS WAF "Human Verification" JavaScript
  challenge**, with a plain client and with full browser headers alike.
- `webarchive.nationalarchives.gov.uk/robots.txt` is **`User-agent: * Disallow: /`**
  — the National Archives disallows automated access to the whole archive, and
  enforces it with the challenge.

So getting at it automatically would mean defeating a bot challenge on a site
that has asked crawlers to stay out. That is a line worth not crossing for a
file a person can download in one click. Rejected — and the check confirms the
manual route is the right one rather than merely the convenient one.

The archive page itself is still exactly what we want; a human just has to open
it. Its URL is now recorded as `sources.ARCHIVE_PAGE` and linked from the site's
about page.

**Recommendation: Option B**, with Option A as the fallback if byte-exact source
retention turns out to matter more than repo size. The two are compatible — the
manifest from B is what you would want alongside A anyway, and switching later
only means adding the files.

One number to check on first ingest: if a full extract gzips to more than ~10 MB,
Option B's "current edition" file is uncomfortably large, and the answer is
either LFS for that one file or splitting the extract per page-type. Ingest
prints the size and warns past 45 MB.

Measured so far: recompressing the existing July 2026 fingerprint took it from
1.13 MB to **212 KB**, so a three-year backfill is ~8 MB of history. The full
extract is smaller than a naive estimate suggests, because only `agreements` is
stored — `organisations` and `datasets` are pure functions of it, and
`agreement["latest"]` aliases a dict already inside `agreement["versions"]`, so
serialising all four would have duplicated most of the file.

## 4. The work

Phases 1–3 are done. Phase 0 is the one step that has to be a person.

### Phase 0 — fetch the archive (human)

Open the
[release register archive](https://digital.nhs.uk/services/data-access-request-service-dars/data-uses-register/release-register-archive)
in a browser and save the editions you want history for into `data/raw/`, keeping
the published filenames. Then `python -m pipeline.ingest data/raw/*.xlsx`.
Nothing else is blocked on this — the pipeline is in place and tested, it just
has one edition of data in it.

### Phase 1 — ingest and the edition store

1. **Done.** `pipeline/editions.py` — read/write the gzipped edition store and
   `data/editions/<register>/manifest.json`. Manifest entry per edition:
   `edition`, `published` (YYYY-MM), `source_file`, `source_url`, `sha256`,
   `ingested`, `counts`, `has_full_extract`.
2. **Done.** `pipeline/ingest.py` — `python -m pipeline.ingest data/raw/*.xlsx`. Extracts,
   writes a fingerprint per edition, writes the full extract for the newest
   edition only (`--full` to force others), updates the manifest. Idempotent, so
   re-running is safe.
3. **Done. Fixed edition ordering.** `snapshot.existing_editions` sorts by the
   `retrieved` timestamp, which is the moment *we* ran the pipeline. Backfilling
   a two-year archive in one afternoon gives every edition near-identical
   timestamps, so "previous edition" becomes whatever order we happened to
   ingest in. Parse the edition label (`july2026` → `2026-07`) and sort on that;
   keep `retrieved` as metadata only. Without this the change log is wrong.

### Phase 2 — build offline

4. **Done.** `pipeline/run.py` — defaults to building the newest edition in the store;
   `--edition <label>` to build an older one. `--workbook` stays, as the escape
   hatch for a one-off build without ingesting.
5. **Done.** `pipeline/sources.py` — deleted `discover()` and `fetch()` and the landing-page
   scrape. Keep the `Register` definitions (slug, name, description, sheets) and
   a filename pattern used to *recognise* a downloaded file rather than to find
   one online. Leave a comment recording why the network path went, so nobody
   re-adds it.
6. **Done.** `meta` for the templates comes from the manifest instead of the live fetch, so
   the per-agreement "Source: …" footers keep pointing at the right workbook URL
   for that edition.

### Phase 3 — CI and docs

7. **Done.** `.github/workflows/build.yml` — removed the `schedule:` block (nothing changes
   between manual ingests, so a cron run is a guaranteed no-op or a failure) and
   remove the "Commit edition snapshot" step and its `contents: write`
   permission. Build on push to `main` and on `workflow_dispatch`, from committed
   data, with no external requests. The workflow then cannot fail the way it has
   been failing.
8. **Done. Added a `.gitignore`.** There wasn't one — the README claimed
   `data/raw/` was gitignored and it was not, which under Option B is how a
   29 MB workbook ends up committed by accident. Now ignores `data/raw/`,
   `_site/`, `.venv/`, `__pycache__/`.
9. **Done.** README — replaced "How it stays current" with the manual procedure, and says
   plainly that automated retrieval is blocked by the publisher's WAF.
10. **Done.** `pipeline/templates/about.html` — a paragraph on how current the mirror is and
    how it is updated, so a reader is not left assuming it tracks the source
    automatically.

### Phase 4 (optional, later)

- A per-edition change log (`/changes/<edition>/`) rather than only latest vs
  previous, now that the full history exists.
- A "first seen / last seen" line on each agreement page, computed across all
  fingerprints — the thing the archive makes possible that a live fetch never
  could.

## 5. The monthly routine

See [manual-updates.md](manual-updates.md) for the full version.

```bash
# 1. Download the new workbook from the landing page in a browser, into data/raw/
# 2. Ingest it
.venv/bin/python -m pipeline.ingest data/raw/datausesregister_august2026.xlsx
# 3. Check the diff it reports, then commit the small files it wrote
git add data/snapshots data/editions
git commit -m "Add the August 2026 edition"
git push
# 4. CI builds and deploys. No network access to digital.nhs.uk required.
```

Roughly two minutes a month, and it fails loudly and locally rather than
silently in a scheduled job.

## 6. Risks

- **Archive coverage is unknown** until Phase 0. If NHS England only keeps a few
  months, the backfill is thinner than hoped — the plan still works, the history
  is just shorter.
- **Sheet layouts may have drifted** across older editions; `extract.py` was
  written against July 2026. Ingest should fail loudly per edition rather than
  silently producing an empty extract, and an edition that cannot be parsed can
  be skipped without blocking the rest.
- **It stops being current if nobody runs it.** Mitigated by surfacing the
  edition and ingest date prominently on the site.
