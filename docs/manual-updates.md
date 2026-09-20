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
   - `data/editions/data-uses-register/agreements/<slug>.json` — the full
     extract the site is rendered from, one uncompressed file per agreement, with
     `extract.json` naming the edition. Only the newest edition is held; ingesting
     it replaces the last one's files, leaving unchanged agreements untouched and
     removing any that have left the register. Git stores the difference, usually
     well under 1 MB. Check `git diff --stat` before committing: a change of tens
     of megabytes means something other than a monthly update happened.

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
saying what counted as a change when they were written. **The rules are now
v5.** Five things changed:

- Text is normalised before hashing, so reformatting is no longer reported as
  an amendment. Between the February and March 2026 editions, 105 of the 122
  "amendments" were punctuation, spacing and capitalisation alone.
- Data controllers and each dataset's recorded attributes are fingerprinted.
  A change of data controller, or a dataset re-classified as sensitive, used
  to register as no change at all.
- A digest is kept per field rather than one per version, so the "what
  changed" page can say *which* fields moved rather than only that something
  did. This roughly doubles a snapshot, from about 208 KB to about 390 KB —
  call it 4 MB more across the whole archive.
- `extract.split_list` no longer breaks an organisation name on a comma
  inside it, so "MCKINSEY & COMPANY, INC. UNITED KINGDOM" stays one
  controller instead of becoming two, one of them called "INC.". This one is
  a parsing fix: rehydrating a stored extract cannot undo the damage, because
  re-splitting a list can only divide it further, so it takes effect on
  re-ingest and not before.
- The same fix, one case wider: an organisation whose own name contains a
  comma — "NHS Bristol, North Somerset and South Gloucestershire ICB - 15C",
  "Cumbria, Northumberland, Tyne and Wear NHS Foundation Trust" — was being
  cut in half, inventing eight organisations. The names to keep whole are
  taken from the register itself: Applicant Organisation holds one
  organisation per row and is never split, so whatever appears there is
  authoritative. Also needs a re-ingest.

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
they were — March 2026 should fall from 122 to roughly 17.

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
| `ingest --source-url URL` | Record a different source URL for one workbook |
| `run --workbook datausesregister_june2026.xlsx` | Build an older edition (the store holds only the newest) |
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
