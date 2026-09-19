# Reviewing and merging organisation names

The register records an organisation's name as free text on every row it
appears on. The same real organisation sometimes gets recorded under more
than one spelling — a shortened ICB name, a trailing "Limited" dropped, a
comma moved — and each spelling gets its own organisation page unless someone
tells the site otherwise.

Two organisations with genuinely similar names are not the same thing (two
different NHS trusts, two different councils), so nothing is merged
automatically. A merge only happens because a person looked at a candidate
and added it to `data/organisation-aliases.json`.

## The easy way: `--review`

```bash
.venv/bin/python -m pipeline.orgcheck --review
```

Goes through candidates one at a time:

```
[1/87] same reference code "03W"
  1) LEICESTERSHIRE AND RUTLAND ICB - 03W  (5 agreements)
  2) NHS LEICESTER, LEICESTERSHIRE AND RUTLAND ICB - 03W  (3 agreements)
  [m]erge  [i]gnore  [k]skip  [q]uit >
```

- **`m`** — merge. Asks which name to keep as canonical (or type your own),
  then an optional one-line reason. Written to
  `data/organisation-aliases.json` immediately.
- **`i`** — ignore. Also written immediately, to the same file's `ignored`
  list, so this exact candidate is never asked about again — not "not now",
  permanently, until someone edits the file.
- **`k`** — skip. Does nothing; asked again next run, useful for "not sure,
  need to check something first".
- **`q`** — quit. Whatever you've already decided this run is already saved;
  everything else shows up again next time.

Rebuild afterwards to see the result:

```bash
.venv/bin/python -m pipeline.run
```

No re-ingest needed — aliases are applied fresh on every build, so editing
this file (by hand or through `--review`) and rebuilding is enough. Open the
merged organisation's page: it lists every raw spelling it was recorded under
under "Also recorded in the register as", linking back to this file, so the
merge is always checkable against what the register actually says. Agreement
pages are never affected — they always show the applicant name exactly as
that row recorded it; only which organisation page it links to changes.

Commit `data/organisation-aliases.json` once you're happy with a session's
decisions — the reasons in the file are usually enough for the commit
message too.

## The manual way

`--review` is `data/organisation-aliases.json` written for you; nothing about
its format is special. To add a merge by hand instead:

```json
{
  "aliases": [
    {
      "canonical": "NHS Bedfordshire, Luton and Milton Keynes ICB - M1J4Y",
      "variants": ["Luton and Milton Keynes ICB - M1J4Y"],
      "reason": "Same ICB reference code (M1J4Y) recorded under a shorter name on some agreement rows."
    }
  ],
  "ignored": []
}
```

`canonical` is what the organisation page shows. `variants` is every other
spelling seen in the register that should land on that page — matching
ignores case and extra whitespace, but not wording, so list each spelling
that actually occurs. `ignored` is a list of candidates (each the sorted list
of names involved) that `--review` should stop suggesting.

`python -m pipeline.orgcheck` on its own — no `--review` — prints the same
candidates without prompting, if you'd rather read the whole list first.

## Deciding

For each candidate ask: is this the same legal entity recorded
inconsistently, or two different organisations that happen to look similar?
When in doubt, skip or ignore it — an unmerged near-duplicate is a cosmetic
inconvenience; a wrong merge attributes one organisation's data sharing to
another.

## What this does and doesn't do

- It only affects the **organisation** field (the applicant, and the data
  controller cross-reference on organisation pages) — never agreement titles,
  dataset names, or any other free text from the register.
- It's forward and backward compatible with the committed edition store: an
  alias applies to every edition rebuilt after it's added, not just the one
  ingested at the time.
- It does not edit or correct the register itself, and doesn't claim to —
  this site is a mirror (see the About page's caveats). It only decides which
  of this site's own pages a name's agreements appear on.
