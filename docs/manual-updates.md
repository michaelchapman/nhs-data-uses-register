# Adding a new edition

NHS England publishes a new Data Uses Register each month. Automated retrieval
does not work — `digital.nhs.uk` sits behind a WAF that refuses requests from
datacentre address space, so both GitHub Actions and any scripted download get
`HTTP 403`, whatever headers they send. The page serves fine in an ordinary
browser, so the workbook is downloaded by hand and committed in a compact form.

Budget about two minutes a month.

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

   This prints the counts and the diff against the previous edition, then writes
   the two files that *are* committed:

   - `data/snapshots/data-uses-register/<edition>.json.gz` — the fingerprint of
     every agreement version, ~210 KB. One per edition, kept forever.
   - `data/editions/data-uses-register/<edition>.json.gz` — the full extract the
     site is rendered from. Only the newest edition keeps one; the previous
     edition's is pruned automatically.

   It also updates `data/editions/data-uses-register/manifest.json` with the
   workbook's SHA-256, size and source URL, so the file we ingested can always
   be identified.

3. **Check the numbers look sane,** then commit and push:

   ```bash
   git add data/snapshots data/editions
   git commit -m "Add the August 2026 edition"
   git push
   ```

4. GitHub Actions builds and deploys from the committed extract. It makes no
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
their filename and processed oldest first, so each diff compares against the
edition actually published before it. Only the newest gets a full extract; the
rest contribute a ~210 KB fingerprint each, so a three-year backfill costs about
8 MB in git.

Add `--fingerprints-only` to extend the history without touching the extract the
site is currently built from.

## Re-fingerprinting the archive

Fingerprints carry a rule version — `fingerprint_version` in each snapshot —
saying what counted as a change when they were written. **The rules changed in
v2:** text is normalised before hashing, so that reformatting is no longer
reported as an amendment. Between the February and March 2026 editions, 105 of
the 122 "amendments" were punctuation, spacing and capitalisation alone.

Every digest moves when the rules change, so editions fingerprinted under
different versions cannot be compared — a comparison would mark the whole
register as amended. `ingest` and `run` detect the mismatch, refuse the
comparison, and say so; nothing is silently wrong, but the "what changed" page
will have a gap until both sides agree.

The fix is a one-off re-ingest of every edition, in one command:

```bash
.venv/bin/python -m pipeline.ingest data/raw/*.xlsx
```

Editions are sorted by publication month regardless of the order they are
listed, so each one is compared against the edition before it. Expect this to
take a while — it parses every workbook — and to rewrite every file under
`data/snapshots/`. Verify your local copies against the manifest first
(see below), commit the whole `data/snapshots/` directory afterwards, and
check that the amendment counts printed along the way are markedly lower than
they were.

Until that happens the site keeps working and keeps showing the old counts,
with a warning on every build.

### Checking the local workbooks

The manifest records a SHA-256 for every edition ingested, so the local set can
be verified before a long run:

```bash
.venv/bin/python - <<'EOF'
import hashlib, json
from pathlib import Path
for e in json.load(open("data/editions/data-uses-register/manifest.json"))["editions"]:
    f = Path("data/raw") / e["source_file"]
    got = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    print(("ok  " if got == e["sha256"] else "BAD "), e["edition"], f.name)
EOF
```

## Useful flags

| Command | Effect |
| --- | --- |
| `ingest --fingerprints-only` | History only; leaves the current extract alone |
| `ingest --keep 2` | Keep full extracts for the newest two editions |
| `ingest --keep -1` | Keep every full extract (watch the repository size) |
| `ingest --source-url URL` | Record a different source URL for one workbook |
| `run --edition june2026` | Build an older edition (needs its full extract) |
| `run --workbook a.xlsx` | One-off build from a file, without ingesting |
| `run --base-path /repo-name` | Serve under a subpath (GitHub project pages) |

## If an edition will not ingest

`extract.py` was written against the July 2026 layout. An older archived edition
may name its sheets or columns differently, in which case ingest stops with a
message rather than writing an empty extract. Skip that edition — the rest still
ingest — and if it matters, compare its sheet and column names with the ones in
`pipeline/extract.py`.

## If the 403 ever goes away

Nothing here depends on it staying broken. Automated download was removed rather
than worked around, and `pipeline/sources.py` records what was tried. Reinstating
it would mean adding a fetch step in front of `pipeline.ingest`, which would
otherwise work unchanged.
