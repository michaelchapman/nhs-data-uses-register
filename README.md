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
requests. Table filtering is a progressive enhancement: every row is in the
HTML, so the site works with JavaScript disabled.

## Running it locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pipeline.run
.venv/bin/python -m http.server 8000 --directory _site
```

`pipeline.run` builds from the edition committed in `data/editions/` and writes
the site to `_site/`. It makes no network requests.

Useful flags:

| Flag | Effect |
| --- | --- |
| `--edition june2026` | Build an older edition instead of the newest |
| `--workbook path.xlsx` | One-off build from a local file, without ingesting |
| `--no-snapshot` | Don't record an edition fingerprint |
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
git add data/snapshots data/editions && git commit -m "Add the August 2026 edition"
```

`.github/workflows/build.yml` then rebuilds and deploys on push to `main`, from
committed data only. Because it never reaches outside the repository, it cannot
fail the way the scheduled job did.

Two things are committed per edition, both gzipped:

- **`data/editions/<register>/<edition>.json.gz`** — the full extract the site is
  rendered from. Only the newest edition keeps one.
- **`data/snapshots/<register>/<edition>.json.gz`** — a hash of every agreement
  version, ~210 KB. One per edition, kept forever; this is what the "what
  changed" page compares.

The workbooks themselves (29 MB each) are never committed — `data/raw/` is
gitignored. `data/editions/<register>/manifest.json` records each one's SHA-256,
size and source URL so the file that was ingested can be identified.

### Backfilling the archive

NHS England keeps previous editions on the
[release register archive](https://digital.nhs.uk/services/data-access-request-service-dars/data-uses-register/release-register-archive).
Download as many as you want history for into `data/raw/` and ingest them
together — command-line order does not matter, as editions are sorted by the
month in their filename:

```bash
.venv/bin/python -m pipeline.ingest data/raw/*.xlsx
```

At ~210 KB a fingerprint, three years of history costs about 8 MB in git.

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
pipeline/ingest.py              workbook -> committed edition store
pipeline/editions.py            the edition store and its manifest
pipeline/extract.py             workbook -> agreements / organisations / datasets
pipeline/snapshot.py            per-edition fingerprints and the month-on-month diff
pipeline/build.py               renders the site and the CSV extracts
pipeline/orgcheck.py            finds organisation names that might be duplicates
pipeline/aliases.py             applies reviewed organisation-name merges
pipeline/clichecheck.py         flags LLM-cliché phrasing in the repo's own prose
pipeline/templates/             Jinja2 templates
assets/                         CSS and the table-filter script
data/raw/                       downloaded workbooks (gitignored)
data/editions/                  committed extracts, and the manifest
data/snapshots/                 committed edition fingerprints
data/organisation-aliases.json  reviewed organisation-name merges
docs/manual-updates.md          the monthly routine
docs/organisation-names.md      reviewing and merging organisation names
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
- File releases are summarised per dataset, not listed file by file; the
  full rows are in the source workbook.
- The register describes what applicants said they intended, not audited
  outcomes.

## Licence

Register content is published by NHS England under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
and stays under it. The code in this repository is MIT licensed.
