# NHS Data Uses Register, readable

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

`pipeline.run` scrapes the register landing page for the current workbook,
downloads it to `data/raw/` (gitignored, and reused on later runs), and writes
the site to `_site/`. A full build takes about 70 seconds.

Useful flags:

| Flag | Effect |
| --- | --- |
| `--workbook path.xlsx` | Build from a local copy instead of downloading |
| `--edition july2026` | Edition label to use with `--workbook` |
| `--no-snapshot` | Don't record an edition fingerprint |
| `--base-path /repo-name` | Serve under a subpath (GitHub project pages) |
| `--output dir` | Write somewhere other than `_site/` |

## How it stays current

`.github/workflows/build.yml` runs on the 5th and 12th of each month, on every
push to `main`, and on demand. It rebuilds from whatever the landing page
currently links to and deploys to GitHub Pages.

Change detection works off `data/snapshots/<register>/<edition>.json`: a hash of
every agreement version in that edition, committed by the workflow. Comparing
the current edition with the previous one produces the "what changed" page, so
the history accumulates from the first run onwards. The snapshots are ~1 MB per
month; the workbooks themselves are never committed.

### First-time setup

1. Push this repository to GitHub.
2. Settings → Pages → **Source: GitHub Actions**.
3. Run the workflow (Actions → Build and deploy → Run workflow).

Using a custom domain or a user page instead of a project page? Set
`SITE_BASE_PATH` to an empty string in the workflow.

## Layout

```
pipeline/sources.py    register definitions; finds the current download link
pipeline/extract.py    workbook -> agreements / organisations / datasets
pipeline/snapshot.py   per-edition fingerprints and the month-on-month diff
pipeline/build.py      renders the site and the CSV extracts
pipeline/templates/    Jinja2 templates
assets/                CSS and the table-filter script
data/snapshots/        committed edition fingerprints
```

## Adding another register

NHS England publishes several registers on the same page. `pipeline/sources.py`
already lists the internal register and the Data Sharing Framework Contracts
with `enabled=False`. To turn one on: check its sheet layout, teach
`extract.py` to read it, then set `enabled=True` and build with
`--register <slug>`. The site templates key off the shared agreement model, so a
register with the same shape needs no template changes.

## Caveats

- This is a mirror. For anything consequential, check the source workbook.
- File releases are summarised per dataset, not listed file by file; the
  full rows are in the source workbook.
- The register describes what applicants said they intended, not audited
  outcomes.

## Licence

Register content is published by NHS England under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
and stays under it. The code in this repository is MIT licensed.
