# Adding a new edition

NHS England publishes a new Data Uses Register each month. Automated retrieval
does not work — `digital.nhs.uk` sits behind a WAF that refuses requests from
datacentre address space, so both GitHub Actions and any scripted download get
`HTTP 403`, whatever headers they send. The page serves fine in an ordinary
browser, so the workbook is downloaded by hand and its contents recorded in the
repository.

Budget about two minutes a month, plus about a minute for the parse.

## The monthly routine

1. **Download the workbook.** Open the
   [Data Uses Register page](https://digital.nhs.uk/services/data-access-request-service-dars/data-uses-register)
   and save the current `.xlsx` (about 29 MB) into `data/raw/`. Keep the
   published filename — `datausesregister_<month><year>.xlsx` — because the
   edition label and the citation URL are read from it.

   `data/raw/` is gitignored. The workbooks are never committed.

2. **Ingest it.**

   ```bash
   .venv/bin/python -m pipeline.ingest data/raw/datausesregister_august2026.xlsx
   ```

   This prints the counts and what the edition changed against the one before
   it, then writes to `data/facts/data-uses-register/`:

   - `agreements/<slug>.json` — every version of an agreement and every state
     each has been published in. Only agreements whose text changed are
     rewritten.
   - `releases/<slug>.json` — the files released under an agreement.
   - `editions/<edition>.json` — which state each version was in that month,
     about 190 KB.
   - `manifest.json` — the workbook's SHA-256, size and source URL, so the file
     we ingested can always be identified.

   Nothing is ever deleted: an agreement that has left the register keeps its
   file and stops appearing in later editions. Git stores the difference, usually
   well under 1 MB. Check `git diff --stat` before committing: a change of tens
   of megabytes means something other than a monthly update happened.

3. **Check the numbers look sane,** then commit and push:

   ```bash
   git add data/facts
   git commit -m "Add the August 2026 edition"
   git push
   ```

   A typical month adds about 40 agreement versions, amends a handful and removes
   almost none. An edition that amends hundreds is either a real event or a
   change in how the register writes something down; its "what changed" page says
   which fields moved.

4. GitHub Actions builds and deploys from the committed facts. It makes no
   external requests, so it cannot fail the way the old scheduled job did.

To preview before pushing:

```bash
.venv/bin/python -m pipeline.run
.venv/bin/python -m http.server 8000 --directory _site
```

## Backfilling the archive

NHS England keeps previous editions on the
[release register archive](https://digital.nhs.uk/services/data-access-request-service-dars/data-uses-register/release-register-archive).
Download as many as you want history for into `data/raw/`, then ingest them in
one go:

```bash
.venv/bin/python -m pipeline.ingest data/raw/*.xlsx
```

Order on the command line does not matter — editions are sorted by the month in
their filename and processed oldest first, so each is compared with the edition
actually published before it. An edition already recorded writes nothing, so a
run can be stopped and restarted. An edition ingested after a later one is fine:
it is slotted in by its date.

The archive from July 2021 to September 2026 took 71 minutes to parse from
scratch and is about 42 MB packed in git.

## Changing what the site says without re-parsing

The facts store holds what each workbook said, and nothing derived from it. That
is the point of it: most changes to the site's answers are a rebuild.

| You want to | Do this | Re-parse? |
| --- | --- | --- |
| Merge two organisation or dataset names | Edit `data/organisation-aliases.json` or `data/dataset-aliases.json` (see [organisation-names.md](organisation-names.md)) | No |
| Change what counts as an amendment | Edit `changes._material` or `compare.compare_versions` | No |
| Change how names are displayed | Edit `pipeline/names.py` | No |
| Change how controllers are split, or how names are tidied | Edit `extract.py`; `facts.rehydrate` re-applies it on every read | Usually no |
| Capture a column the parser never read | Edit `extract.py` and re-ingest | **Yes** |
| Fix a bug in how a workbook is parsed | Edit `extract.py` and re-ingest | **Yes** |

A dataset alias applies to the whole archive at the next build: an amendment that
was only the register relabelling a dataset disappears from every edition at
once, with nothing to regenerate.

### When a re-parse is needed

Re-ingest every workbook. Delete `data/facts/` first, because the store is
append-only and cannot correct what it has already recorded:

```bash
rm -rf data/facts
.venv/bin/python -m pipeline.ingest data/raw/*.xlsx
```

Then check what moved with `git diff --stat data/facts` before committing. This
is the expensive operation the design exists to avoid, so it should be rare.

### Checking the local workbooks

The manifest records a SHA-256 for every edition ingested, so the local set can
be verified before a long run:

```bash
.venv/bin/python - <<'EOF'
import hashlib, json
from pathlib import Path
for e in json.load(open("data/facts/data-uses-register/manifest.json"))["editions"]:
    f = Path("data/raw") / e["source_file"]
    got = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    print(("ok  " if got == e["sha256"] else "BAD "), e["edition"], f.name)
EOF
```

`rm -rf data/facts` deletes the manifest along with everything else, and
re-ingesting rewrites it, but any `--source-url` you passed for an edition (the
January 2025 one) is lost with it. Note those before a re-parse and pass them
again.

## Useful flags

| Command | Effect |
| --- | --- |
| `ingest --source-url URL` | Record a different source URL for one workbook |
| `run --edition june2026` | Build any edition in the store, not only the newest |
| `run --workbook a.xlsx` | One-off build from a file, without ingesting |
| `run --base-path /repo-name` | Serve under a subpath (GitHub project pages) |

## What a gap looks like

If a month's workbook was never ingested, the comparison across it says so: the
"what changed" page states that it covers more than one month and names the
months not held, and an agreement first seen after a gap says it may have
appeared in either month. Ingest the missing workbook whenever you find it; it is
slotted in by date and the comparison narrows.

January 2025 was missing from NHS England's own archive and was recovered from
the UK Government Web Archive; its manifest entry records that source URL.

## If an edition will not ingest

`extract.py` reads the layout every edition from July 2021 to September 2026
shares: three sheets, `Agreements`, `Datasets` and `DataReleases`. If NHS England
changes it, ingest stops with a message rather than writing an empty edition. The
rest of the archive is unaffected. Compare the workbook's sheet and column names
with the ones in `pipeline/extract.py`.

## If the 403 ever goes away

Nothing here depends on it staying broken. Automated download was removed rather
than worked around, and `pipeline/sources.py` records what was tried. Reinstating
it would mean adding a fetch step in front of `pipeline.ingest`, which would
otherwise work unchanged.
