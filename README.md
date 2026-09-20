# NHS Data Access Explorer

A static site that reformats the [NHS England Data Uses Register](https://digital.nhs.uk/services/data-access-request-service-dars/data-uses-register)
— published monthly as a 29 MB, three-sheet spreadsheet — into pages you can
read, search, link to and cite.

It is unofficial. NHS England publishes the data; this repository only
rearranges it.

## What it produces

From one edition of the register (~5,500 agreement versions):

- **~1,900 agreement pages** — versions of the same agreement grouped together,
  with purpose, expected outputs, benefits, datasets and file releases joined
  from all three sheets onto one page.
- **~570 organisation pages** and **~210 dataset pages** — the two questions the
  spreadsheet makes hardest: what has this organisation been given, and who
  receives this dataset.
- **A "what changed" page** — agreements added, amended or withdrawn since the
  previous edition.
- **Flat CSV extracts** of agreements, datasets and releases.

Pages are plain semantic HTML with no cookies, analytics or third-party
requests. Table filtering and sorting are progressive enhancements: every row is in the
HTML, so the site works with JavaScript disabled. The filters and the sort are
kept in the URL, so a filtered view can be linked to.

## Running it locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pipeline.run
.venv/bin/python -m http.server 8000 --directory _site
```

`pipeline.run` builds the newest edition in `data/facts/` and writes the site to
`_site/`. It makes no network requests.

Useful flags:

| Flag | Effect |
| --- | --- |
| `--edition september2026` | Build any edition in the store, not only the newest |
| `--workbook path.xlsx` | One-off build from a local file; nothing is ingested or written to `data/` |
| `--base-path /repo-name` | Serve under a subpath (GitHub project pages) |
| `--output dir` | Write somewhere other than `_site/` |

## How it stays current

By hand, once a month. **[docs/manual-updates.md](docs/manual-updates.md) is the
runbook** — it takes about two minutes.

It is not automated, and that is deliberate. `digital.nhs.uk` sits behind a WAF
that refuses requests from datacentre address space: every scheduled build
failed with `HTTP 403`, including one that sent full browser headers and retried
with backoff. The asset URLs are blocked the same way, and so is the National
Archives' copy. Rather than work around a block the publisher put there on
purpose, the download step was removed. The page serves fine in an ordinary
browser, so a person downloads the workbook and runs one command:

```bash
.venv/bin/python -m pipeline.ingest data/raw/datausesregister_august2026.xlsx
git add data/facts && git commit -m "Add the August 2026 edition"
```

`.github/workflows/build.yml` then rebuilds and deploys on push to `main`, from
committed data only. Because it never reaches outside the repository, it cannot
fail the way the scheduled job did.

One thing is committed: **`data/facts/<register>/`**, the text of every
edition. Nothing derived is stored — what changed between editions, and the
organisation and dataset views, are worked out at build time — so a new alias or
a change to what counts as an amendment costs a rebuild, and never a re-parse of
the workbooks.

- **`agreements/<slug>.json`** — every version of one agreement, and each
  distinct state a version has been published in. One uncompressed file per
  agreement, deliberately not gzipped or bundled: consecutive editions restate
  almost all of the same prose, and git stores that as a small delta between two
  copies of the same file. `git log` on one of these is that agreement's history.
- **`releases/<slug>.json`** — every file released under an agreement, one row
  per file, and which edition first reported it.
- **`editions/<edition>.json`** — which state each version was in that month.
  About 190 KB, one per edition, kept forever.
- **`manifest.json`** — each workbook's SHA-256, size and source URL, so the file
  that was ingested can be identified.

The whole archive, July 2021 to September 2026, is about 420 MB on disk and
42 MB packed in git; a monthly ingest adds under 1 MB. See
[docs/plan-facts-store.md](docs/plan-facts-store.md) for why it is shaped this
way.

The workbooks themselves (29 MB each) are never committed: `data/raw/` is
gitignored.

### Backfilling the archive

NHS England keeps previous editions on the
[release register archive](https://digital.nhs.uk/services/data-access-request-service-dars/data-uses-register/release-register-archive).
Download as many as you want history for into `data/raw/` and ingest them
together — command-line order does not matter, as editions are sorted by the
month in their filename:

```bash
.venv/bin/python -m pipeline.ingest data/raw/*.xlsx
```

Ingesting an edition that is already recorded writes nothing, so a backfill can
be stopped and restarted.

### First-time setup

1. Push this repository to GitHub.
2. Settings → Pages → **Source: GitHub Actions**.
3. Ingest at least one edition and push it.
4. Run the workflow (Actions → Build and deploy → Run workflow).

Using a custom domain or a user page instead of a project page? Set
`SITE_BASE_PATH` to an empty string in the workflow.

## Layout

```
pipeline/sources.py             register definitions, filename and edition rules
pipeline/ingest.py              workbook -> the committed facts store
pipeline/facts.py               the facts store: every edition, its releases and its manifest
pipeline/extract.py             workbook -> agreements / organisations / datasets
pipeline/changes.py             what changed between editions, worked out from the facts
pipeline/compare.py             field-by-field comparison of two agreement versions
pipeline/build.py               renders the site and the CSV extracts
pipeline/orgcheck.py            finds organisation names that might be duplicates
pipeline/aliases.py             applies reviewed organisation and dataset merges
pipeline/datasetcheck.py        finds datasets the register has renamed
pipeline/clichecheck.py         flags LLM-cliché phrasing in the repo's own prose
pipeline/linkcheck.py           finds internal links in a built site that point nowhere
pipeline/templates/             Jinja2 templates
tests/                          unit tests and a synthetic register (python -m unittest)
assets/                         CSS and the table-filter script
data/raw/                       downloaded workbooks (gitignored)
data/facts/                     committed facts: every edition, and the manifest
data/organisation-aliases.json  reviewed organisation-name merges
data/dataset-aliases.json       reviewed dataset-name merges
docs/manual-updates.md          the monthly routine
docs/organisation-names.md      reviewing and merging organisation names
docs/plan-*.md                  design notes, accepted and proposed
```

## Adding another register

NHS England publishes several registers on the same page. `pipeline/sources.py`
already lists the internal register and the Data Sharing Framework Contracts
with `enabled=False`. To turn one on: check its sheet layout, teach
`extract.py` to read it, then set `enabled=True` and ingest with
`--register <slug>`. The site templates key off the shared agreement model, so a
register with the same shape needs no template changes.

## Caveats

- This is a mirror, and only as current as the last edition somebody added.
  The edition and the date it was added are in the footer of every page. For
  anything consequential, check the source workbook.
- File releases are summarised per dataset on the site. The facts store holds
  every file, but a release row records a physical file leaving NHS England
  through DARS; it says nothing about data analysed inside a secure environment
  or shared onward by a recipient. See
  [docs/plan-release-coverage.md](docs/plan-release-coverage.md).
- The register describes what applicants said they intended, not audited
  outcomes.

## Licence

Register content is published by NHS England under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
and stays under it. The code in this repository is MIT licensed.
