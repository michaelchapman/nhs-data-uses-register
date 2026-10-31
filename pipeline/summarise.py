"""Write AI overviews of agreements with the Claude Batch API.

    python -m pipeline.summarise estimate          # what a full run would cost; no API call
    python -m pipeline.summarise pilot             # 40 agreements, on Haiku and Sonnet
    python -m pipeline.summarise run               # every agreement without a current overview
    python -m pipeline.summarise run --limit 100   # the first 100 of them
    python -m pipeline.summarise collect --wait    # fetch finished batches

A maintainer tool, never part of the build or CI. It needs `ANTHROPIC_API_KEY`
and the packages in requirements-summarise.txt. Batches run at half the
normal price and usually finish within an hour; `collect` picks up any that
have ended, so it can be run again later if the wait is cut short.

`pilot` writes `_summaries/pilot.md`, the two models' overviews side by side
with what each batch cost, to read before choosing a model. Nothing it writes
is published.

`run` writes to `data/summaries.json`, which the build reads (see
`pipeline.overviews`). Each overview is checked before it is stored. An
overview that fails a check is stored with its `flags` and not shown until a
person has read it and deleted the flags.

The overviews are not part of the register, and every page that shows one says
so. See docs/plan.md, "AI overviews".
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import time
from pathlib import Path

from . import clichecheck, overviews, sources
from .names import display_name
from .run import DEFAULT_SITE_URL, from_store

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "_summaries"
STATE = WORK / "batches.json"

DEFAULT_MODEL = "claude-sonnet-5-5"
PILOT_MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5"]
PILOT_COUNT = 40
# Fixed, so a pilot run twice compares the same agreements.
PILOT_SEED = 2026

# Standard list prices in US dollars per million tokens (input, output). A
# batch is billed at half of these. Prices as of October 2026; check
# https://claude.com/pricing before relying on them.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}
BATCH_DISCOUNT = 0.5
# Characters per token, for estimates only: the API counts the real tokens.
CHARS_PER_TOKEN = 3.5

MAX_WORDS = 90

# What an overview is written from. "Processing activities" is left out: it is
# mostly standard wording on storage and security, says little about purpose,
# and is over a quarter of the text. Long fields are cut, since their opening
# says what the agreement is for; reported benefits are sent in full, because
# updates are added at the end.
SOURCE_FIELDS = [
    ("Objective for processing", "objective", 4000),
    ("Expected output", "expected_output", 4000),
    ("Expected measurable benefits", "expected_benefits", 4000),
    ("Benefits reported so far", "yielded_benefits", None),
]

INSTRUCTIONS = """\
You write the overview shown at the top of a page about one NHS England data \
sharing agreement. The page then shows the register's own text in full. Your \
overview helps a member of the public decide whether the agreement is what \
they are looking for.

Write two to four sentences, at most 75 words, in plain English with UK \
spelling:
1. Who is using the data and what kind of data it is.
2. What they are using it for.
3. If the text states one clearly, the main intended benefit.
4. If "Benefits reported so far" describes a specific benefit that has \
already happened, such as a published paper, a changed service or a report \
used in a decision, say so in one sentence. Skip this if that section is \
empty, says benefits are not yet available or not required, or only restates \
the expected benefits.

Rules:
- Use only facts stated in the text you are given. Never add facts, numbers, \
names or context from elsewhere.
- Do not judge the agreement, praise it or criticise it.
- Do not say whether data has or has not been released or shared; the page \
reports that separately.
- Spell out an acronym the first time if the text spells it out; otherwise \
keep it as written.
- No headings, bullet points or quotation of the text. Start with the \
organisation's name, not with "This agreement".
- Reply with the overview only."""


def agreement_text(agreement: dict) -> str:
    """The text an overview is written from: the agreement's latest version."""
    version = agreement["latest"]
    datasets = sorted({d.get("name", "") for d in version.get("datasets") or [] if d.get("name")})
    parts = [
        f"Title: {agreement.get('title') or version.get('title') or ''}",
        # In ordinary case, as the page shows it, so the overview isn't in capitals.
        f"Organisation: {display_name(agreement.get('organisation') or version.get('organisation') or '')}",
        f"Organisation type: {version.get('organisation_type') or 'Not stated'}",
        "Datasets: " + ("; ".join(datasets) or "Not stated"),
    ]
    for heading, field, limit in SOURCE_FIELDS:
        text = (version.get(field) or "").strip() or "Not stated"
        if limit and len(text) > limit:
            text = text[:limit].rsplit(" ", 1)[0] + " [cut]"
        parts.append(f"\n## {heading}\n\n{text}")
    return "\n".join(parts)


def request_params(agreement: dict, model: str) -> dict:
    return {
        "model": model,
        # Thinking counts toward max_tokens; the overview itself is short.
        "max_tokens": 4096,
        "output_config": {"effort": "low"},
        "system": INSTRUCTIONS,
        "messages": [{"role": "user", "content": agreement_text(agreement)}],
    }


# Checks on what comes back --------------------------------------------------

RELEASE_CLAIM = re.compile(
    r"\b(no|not|never|yet to)\b[^.]{0,40}\b(released|shared|received|provided|disseminated)\b", re.I
)
CAPITALISED = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][A-Za-z0-9&'-]+\b")


def check(summary: str, source: str) -> list[str]:
    """Reasons a person should read `summary` before it is shown. Empty if none."""
    flags = []
    if not summary.strip():
        return ["empty"]
    words = len(summary.split())
    if words > MAX_WORDS:
        flags.append(f"long: {words} words")
    if RELEASE_CLAIM.search(summary):
        flags.append("says whether data was released")
    for check_id, label, regex in clichecheck.REGEX_CHECKS:
        if regex.search(summary):
            flags.append(f"cliché: {label} [{check_id}]")
    # Names and acronyms the source never uses may have been made up.
    lowered = source.lower()
    unknown = sorted({w for w in CAPITALISED.findall(summary)
                      if re.sub(r"['’]s$", "", w).lower().strip("'") not in lowered})
    if unknown:
        flags.append("names not in the text: " + ", ".join(unknown))
    return flags


# Batches --------------------------------------------------------------------


def client():
    try:
        import anthropic
    except ImportError:
        raise SystemExit("pip install -r requirements-summarise.txt first") from None
    return anthropic.Anthropic()


def load_state() -> list[dict]:
    return json.loads(STATE.read_text()) if STATE.exists() else []


def save_state(state: list[dict]) -> None:
    WORK.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1) + "\n")


def submit(agreements: list[dict], model: str, kind: str) -> dict:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    requests = [
        Request(
            custom_id=a["base_reference"].upper(),
            params=MessageCreateParamsNonStreaming(**request_params(a, model)),  # type: ignore[typeddict-item]
        )
        for a in agreements
    ]
    batch = client().messages.batches.create(requests=requests)
    record = {
        "id": batch.id,
        "kind": kind,
        "model": model,
        "submitted": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        # What each request was written from, so results are stored against
        # the text they describe even if a new edition lands meanwhile.
        "hashes": {a["base_reference"].upper(): overviews.text_hash(a["latest"]) for a in agreements},
        "collected": False,
    }
    state = load_state()
    state.append(record)
    save_state(state)
    print(f"submitted {len(requests)} requests to {model}: batch {batch.id}")
    return record


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return BATCH_DISCOUNT * (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def fetch(record: dict) -> dict | None:
    """`{reference: text}` and usage for a batch that has ended, else None."""
    api = client()
    batch = api.messages.batches.retrieve(record["id"])
    if batch.processing_status != "ended":
        counts = batch.request_counts
        print(f"{record['id']} ({record['model']}): {batch.processing_status}, "
              f"{counts.processing} processing, {counts.succeeded} done")
        return None
    texts: dict[str, str] = {}
    failed: list[str] = []
    usage = {"input": 0, "output": 0}
    for result in api.messages.batches.results(record["id"]):
        if result.result.type != "succeeded":
            failed.append(f"{result.custom_id}: {result.result.type}")
            continue
        message = result.result.message
        usage["input"] += message.usage.input_tokens + (message.usage.cache_read_input_tokens or 0)
        usage["output"] += message.usage.output_tokens
        if message.stop_reason not in ("end_turn", "stop_sequence"):
            failed.append(f"{result.custom_id}: stopped on {message.stop_reason}")
            continue
        texts[result.custom_id] = " ".join(b.text for b in message.content if b.type == "text").strip()
    for line in failed:
        print(f"  not written: {line}")
    return {"texts": texts, "usage": usage, "failed": failed}


def store(record: dict, fetched: dict, by_reference: dict[str, dict]) -> None:
    entries = overviews.load()
    written = record["submitted"][:10]
    flagged = 0
    for reference, summary in fetched["texts"].items():
        agreement = by_reference.get(reference)
        source = agreement_text(agreement) if agreement else ""
        entry = {"hash": record["hashes"][reference], "summary": summary, "model": record["model"], "written": written}
        flags = check(summary, source)
        if flags:
            entry["flags"] = flags
            flagged += 1
            print(f"  {reference}: " + "; ".join(flags))
        entries[reference] = entry
    overviews.write(entries)
    print(f"stored {len(fetched['texts'])} overviews in {overviews.PATH}, {flagged} flagged for review")


def write_pilot(records: list[dict], results: dict[str, dict], by_reference: dict[str, dict]) -> Path:
    references = sorted({r for record in records for r in record["hashes"]})
    lines = ["# Overview pilot", ""]
    lines.append("| Model | Input tokens | Output tokens | Cost (batch) |")
    lines.append("| --- | ---: | ---: | ---: |")
    for record in records:
        usage = results[record["id"]]["usage"]
        lines.append(f"| {record['model']} | {usage['input']:,} | {usage['output']:,} | "
                     f"${cost(record['model'], usage['input'], usage['output']):.2f} |")
    lines.append("")
    total_chars = sum(len(agreement_text(a)) for a in by_reference.values())
    sample_chars = sum(len(agreement_text(by_reference[r])) for r in references if r in by_reference) or 1
    lines.append(f"The sample is {sample_chars / total_chars:.1%} of the register's text by length, so a full run "
                 f"costs about {total_chars / sample_chars:.0f} times the figures above.")
    lines.append("")
    for reference in references:
        agreement = by_reference.get(reference, {})
        lines.append(f"## {agreement.get('title') or reference}")
        lines.append("")
        lines.append(f"{reference} · {display_name(agreement.get('organisation', ''))} · "
                     f"{DEFAULT_SITE_URL}/agreements/{agreement.get('slug', '')}/")
        lines.append("")
        for record in records:
            summary = results[record["id"]]["texts"].get(reference, "(not written)")
            flags = check(summary, agreement_text(agreement)) if agreement else []
            lines.append(f"**{overviews.MODEL_NAMES.get(record['model'], record['model'])}:** {summary}")
            if flags:
                lines.append(f"  _Flagged: {'; '.join(flags)}_")
            lines.append("")
    path = WORK / "pilot.md"
    WORK.mkdir(exist_ok=True)
    path.write_text("\n".join(lines))
    return path


# Commands -------------------------------------------------------------------


def all_agreements() -> list[dict]:
    register = sources.registers("data-uses-register")[0]
    data, _, _ = from_store(register, None)
    return data["agreements"] + data.get("archived", [])


def needing_overviews(agreements: list[dict], entries: dict[str, dict]) -> list[dict]:
    """Agreements with no overview written from their current text, flagged or not."""
    return [a for a in agreements
            if entries.get(a["base_reference"].upper(), {}).get("hash") != overviews.text_hash(a["latest"])]


def cmd_estimate(args) -> None:
    agreements = needing_overviews(all_agreements(), overviews.load())
    chars = sum(len(INSTRUCTIONS) + len(agreement_text(a)) for a in agreements)
    tokens_in = chars / CHARS_PER_TOKEN
    # The October 2026 pilot averaged about 120 output tokens an overview.
    tokens_out = 150 * len(agreements)
    print(f"{len(agreements):,} agreements need an overview: about {tokens_in / 1e6:.1f}M input tokens")
    for model in PRICES:
        print(f"  {model}: about ${cost(model, int(tokens_in), tokens_out):.2f} as a batch")


def cmd_pilot(args) -> None:
    listed = [a for a in all_agreements() if not a.get("archived")]
    listed.sort(key=lambda a: a["base_reference"])
    sample = random.Random(PILOT_SEED).sample(listed, min(args.count, len(listed)))
    for model in args.model or PILOT_MODELS:
        submit(sample, model, "pilot")
    print("run `python -m pipeline.summarise collect --wait` to fetch them")


def cmd_run(args) -> None:
    pending = {r for record in load_state() if not record["collected"] for r in record["hashes"]}
    agreements = [a for a in needing_overviews(all_agreements(), overviews.load())
                  if a["base_reference"].upper() not in pending]
    if args.limit:
        agreements = agreements[: args.limit]
    if not agreements:
        print("every agreement has a current overview, or one is on its way")
        return
    submit(agreements, args.model, "run")
    print("run `python -m pipeline.summarise collect --wait` to fetch them")


def cmd_collect(args) -> None:
    by_reference = {a["base_reference"].upper(): a for a in all_agreements()}
    while True:
        state = load_state()
        open_records = [r for r in state if not r["collected"]]
        if not open_records:
            print("no batches waiting")
            return
        # A pilot's batches are written up together, once both have ended.
        pilot = [r for r in open_records if r["kind"] == "pilot"]
        pilot_results = {}
        for record in open_records:
            fetched = fetch(record)
            if fetched is None:
                continue
            if record["kind"] == "pilot":
                pilot_results[record["id"]] = fetched
            else:
                store(record, fetched, by_reference)
                record["collected"] = True
                usage = fetched["usage"]
                print(f"  cost about ${cost(record['model'], usage['input'], usage['output']):.2f}")
        if pilot and len(pilot_results) == len(pilot):
            path = write_pilot(pilot, pilot_results, by_reference)
            for record in pilot:
                record["collected"] = True
            print(f"wrote {path.relative_to(ROOT)}")
        save_state(state)
        if not args.wait or all(r["collected"] for r in state):
            return
        time.sleep(60)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("estimate", help="estimate the cost of a full run").set_defaults(func=cmd_estimate)
    pilot = commands.add_parser("pilot", help="overviews of a sample, from both models")
    pilot.add_argument("--count", type=int, default=PILOT_COUNT)
    pilot.add_argument("--model", action="append", choices=sorted(PRICES),
                       help="a model to try; repeat for more (default: Haiku and Sonnet)")
    pilot.set_defaults(func=cmd_pilot)
    run = commands.add_parser("run", help="overviews of every agreement without a current one")
    run.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(PRICES))
    run.add_argument("--limit", type=int, help="submit at most this many")
    run.set_defaults(func=cmd_run)
    collect = commands.add_parser("collect", help="fetch batches that have ended")
    collect.add_argument("--wait", action="store_true", help="keep checking every minute until all have ended")
    collect.set_defaults(func=cmd_collect)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
