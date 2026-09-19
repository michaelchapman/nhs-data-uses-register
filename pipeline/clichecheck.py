"""Flag LLM-cliché phrasing in the repository's own prose.

    python -m pipeline.clichecheck              # check the repo's prose files
    python -m pipeline.clichecheck a.md b.py     # check specific files

Exits non-zero if anything is flagged, so CI can gate on it (see
.github/workflows/build.yml). The pattern list here is an independent
implementation covering the same categories as Simon Willison's
llm-cliche-highlighter (tools.simonwillison.net/llm-cliche-highlighter) —
credit to that tool for identifying which patterns are worth checking for;
the regexes and structural checks below are written from scratch for this
repo rather than copied from its source.

This checks wording, not substance — a clean run doesn't mean the prose is
good, only that it avoids a specific list of tells. It also isn't proof
text is AI-written or wasn't: these phrases turn up in ordinary human
writing too, just more rarely than they do in unedited LLM output.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files worth checking: the repo's own prose and comments, not the register
# data it publishes (data/) or build output (_site/).
DEFAULT_GLOBS = [
    "README.md",
    "docs/**/*.md",
    "pipeline/**/*.py",
    "pipeline/templates/**/*.html",
    "assets/*.css",
    "assets/*.js",
]


SELF = Path(__file__).resolve()


def default_files() -> list[Path]:
    # Excludes itself: this file's own pattern list and labels are full of
    # the exact words and phrases it's checking for, which would otherwise
    # make it permanently, uselessly non-clean.
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in DEFAULT_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file() and path != SELF and path not in seen:
                seen.add(path)
                files.append(path)
    return files


# Each entry: (id, human label, compiled regex). One hit is a hit — the
# point isn't frequency, it's whether this specific tell shows up at all.
_WORD = r"[A-Za-z][A-Za-z'’-]*"
REGEX_CHECKS: list[tuple[str, str, re.Pattern]] = [
    (
        "vocab",
        "AI-favoured vocabulary",
        re.compile(
            r"\b(delv(?:e|es|ed|ing)|tapestr(?:y|ies)|meticulous(?:ly)?|pivotal|"
            r"intricate(?:ly)?|intricacies|interplay|underscor(?:e|es|ed|ing)|"
            r"garner(?:s|ed|ing)?|bolster(?:s|ed|ing)?|vibrant|bustling|"
            r"multifaceted|seamless(?:ly)?|commendable|ever-evolving)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "not-just-but",
        '"not just X, but Y" / "it\'s not X — it\'s Y"',
        re.compile(
            r"\bnot\s+(?:just|only|merely|simply)\s+[^.!?\n;]*?\bbut(?:\s+also)?\b"
            r"|\b(?:it|this|that)(?:'s|\s+(?:is|was))\s+not\s+[^.!?\n,;—–]{1,60}"
            r"[,;—–]\s*(?:it|this|that)(?:'s|\s+(?:is|was))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "note-that",
        '"it\'s important to note" / "worth noting"',
        re.compile(
            r"\bit(?:'s|\s+(?:is|was))\s+(?:also\s+)?(?:important|worth|crucial|essential|vital)\s+"
            r"(?:to\s+(?:note|remember|understand|recognize|mention|pause|consider|ask)|"
            r"noting|mentioning|remembering|pausing|considering|asking)\b"
            r"|\bit\s+should\s+be\s+noted\b",
            re.IGNORECASE,
        ),
    ),
    (
        "testament",
        '"stands as a testament"',
        re.compile(
            r"\b(?:stand|stands|stood|serve|serves|served)\s+as\s+(?:a|an)\s+(?:\w+\s+)?"
            r"(?:testament|reminder)\b|\b(?:is|was|are|were|remains?)\s+a\s+(?:\w+\s+)?testament\s+to\b",
            re.IGNORECASE,
        ),
    ),
    (
        "crucial-role",
        '"plays a crucial role"',
        re.compile(
            r"\bplay(?:s|ed|ing)?\s+(?:a|an)\s+(?:\w+\s+)?"
            r"(?:crucial|pivotal|vital|key|significant|central|critical|important)\s+role\b",
            re.IGNORECASE,
        ),
    ),
    (
        "landscape",
        '"ever-evolving landscape" / "in today\'s fast-paced world"',
        re.compile(
            r"\b(?:ever-)?(?:evolving|changing|shifting)\s+landscape\b"
            r"|\bin\s+today's\s+(?:fast-paced|ever-changing|ever-evolving|digital|modern|competitive)\s+\w+",
            re.IGNORECASE,
        ),
    ),
    (
        "vague-experts",
        '"experts argue" / "observers suggest"',
        re.compile(
            r"\b(?:experts|critics|observers|scholars|analysts|commentators)\s+"
            r"(?:have\s+|often\s+|widely\s+)?(?:argu(?:e|es|ed)|not(?:e|es|ed)|suggest(?:s|ed)?|"
            r"believ(?:e|es|ed)|agree[ds]?|contend(?:s|ed)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "despite-challenges",
        '"despite these challenges" / "remains to be seen"',
        re.compile(
            r"\bdespite\s+(?:these|those|such)\s+(?:\w+\s+)?challenges\b"
            r"|\bchallenges\s+remain\b|\bremains\s+to\s+be\s+seen\b|\btime\s+will\s+tell\b",
            re.IGNORECASE,
        ),
    ),
    (
        "participle-tail",
        '", highlighting/underscoring/showcasing the ..."',
        re.compile(
            r",\s+(?:highlighting|underscoring|emphasizing|showcasing|reflecting|demonstrating|"
            r"illustrating|signaling|solidifying|cementing|reinforcing|underlining)\s+"
            r"(?:its|his|her|their|our|the|a|an|how|that|what|both)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "promo",
        'travel-brochure boilerplate ("nestled in", "hidden gem")',
        re.compile(
            r"\bnestled\s+(?:in|on|among|between|along|at)\b|\bin\s+the\s+heart\s+of\b"
            r"|\brich\s+(?:cultural\s+|historical\s+)?(?:heritage|tapestry)\b|\bhidden\s+gem\b"
            r"|\bmust-(?:visit|see|try)\b|\bbreathtaking\b|\bboasts?\s+(?:a|an|the)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "chatbot-leftovers",
        "pasted-from-a-chatbot artefacts",
        re.compile(
            r"\bas\s+an\s+ai(?:\s+language)?\s+model\b|\bas\s+of\s+my\s+last\s+(?:update|training)\b"
            r"|\bknowledge\s+cutoff\b|contentReference|oaicite|turn0(?:search|news|image)\d*|utm_source=",
            re.IGNORECASE,
        ),
    ),
    (
        "turns-out",
        '"turns out ..." as a scene-opener',
        re.compile(r"(?:^|[.!?]\s+)Turns\s+out\b|\bit\s+turns\s+out\s+that\b", re.MULTILINE),
    ),
    (
        "performative-honesty",
        '"I won\'t pretend" / "let\'s be honest"',
        re.compile(
            r"\bI\s+(?:will\s+not|won't)\s+pretend\b|\b(?:I'll|let's|to)\s+be\s+(?:honest|blunt)\b"
            r"|(?:^|[.!?–—]\s+)(?:Honestly|Truthfully|Frankly)\s*,",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "worth-naming",
        '"worth naming" (therapy-voiced)',
        re.compile(r"\bworth\s+naming\b(?!\s+names\b)", re.IGNORECASE),
    ),
    (
        "not-nothing",
        '"that\'s not nothing"',
        re.compile(r"\b(?:that|this|it|which)(?:'s|\s+(?:is|was))\s+not\s+nothing\b", re.IGNORECASE),
    ),
    (
        "whole-entire",
        '"the whole point/game" / "the entire point"',
        re.compile(
            r"(?:\b(?:is|was|are|were)|'s)\s+the\s+(?:whole|entire)\b(?:\s+\w+)?",
            re.IGNORECASE,
        ),
    ),
    (
        "heres-the-twist",
        '"here\'s the twist/catch/kicker"',
        re.compile(
            r"\bhere(?:'s|\s+is)\s+(?:the|a|my|one)\s+(?:twist|catch|kicker|rub)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "x-is-dead",
        '"X is dead" / "long live X"',
        re.compile(r"\b" + _WORD + r"(?:\s+" + _WORD + r"){0,3}\s+is\s+dead\b|\blong\s+live\s+\w+", re.IGNORECASE),
    ),
    (
        "the-only-i-trust",
        '"the only X I trust/need"',
        re.compile(
            r"\bthe\s+only\s+" + _WORD + r"(?:\s+" + _WORD + r"){0,2}?\s+"
            r"(?:I|you|we|it)\s+(?:trust|need|needs|care|want|wants|use|uses|believe)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "take-my-word",
        '"don\'t take my word for it"',
        re.compile(r"\b(?:you\s+)?(?:do\s+not|don't)\s+(?:have\s+to\s+)?take\s+my\s+word\s+for\b", re.IGNORECASE),
    ),
    (
        "fits-in-your-head",
        '"fits in your head" / "it just works" / "batteries included"',
        re.compile(
            r"\b(?:hold|fit|fits|holds|held)\s+(?:it\s+)?in\s+your\s+head\b|\bbatteries[-\s]included\b"
            r"|\bit\s+just\s+works\b|\bzero[-\s]config(?:uration)?\b|\bsane\s+defaults\b",
            re.IGNORECASE,
        ),
    ),
    (
        "sit-with",
        '"sit with that" (reflective/therapy-voiced)',
        re.compile(r"\bsit(?:s|ting)?\s+with\s+(?:that|this|it|the\s+(?:discomfort|feelings?|tension))\b", re.IGNORECASE),
    ),
    (
        "already-know",
        '"you already know"',
        re.compile(r"\byou\s+already\s+knows?\b", re.IGNORECASE),
    ),
    (
        "punchline",
        '"the punchline is"',
        re.compile(r"\bthe\s+punchline(?:\s+(?:is|was)\b|\s*[:?])", re.IGNORECASE),
    ),
    (
        "thats-why-mattered",
        '"that\'s why X mattered"',
        re.compile(
            r"\b(?:that|this)(?:'s|\s+(?:is|was))\s+why\b[^.!?\n]{0,80}?\b(?:matter(?:s|ed)?|count(?:s|ed)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "dont-verb-it",
        '"don\'t call it X, call it Y"',
        re.compile(
            r"\b(?:do\s+not|don't)\s+(\w+)\s+it\b[^.!?\n]*?[.!?;:]\s*\1\s+it\b",
            re.IGNORECASE,
        ),
    ),
]


def _sentences(text: str) -> list[tuple[str, int]]:
    """`(sentence_text, start_offset)` pairs, roughly split on sentence ends."""
    out = []
    for m in re.finditer(r"[^.!?\n]+[.!?]?", text):
        s = m.group(0).strip()
        if s:
            out.append((s, m.start()))
    return out


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def strip_markdown_code(text: str) -> str:
    """Blank out fenced and indented code blocks and inline code spans.

    A shell command or an ASCII file tree in a ```fence``` is not prose, but
    a naive sentence splitter reads its punctuation as sentence boundaries
    and its repeated leading tokens (`git`, four spaces of tree indent) as
    anaphora. Blanking rather than deleting keeps line numbers accurate for
    the findings that are left.
    """
    text = re.sub(r"```.*?```", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]+`", lambda m: " " * len(m.group(0)), text)
    return text


def find_no_chains(text: str) -> list[tuple[int, str]]:
    """2+ "no X" items in a row: "no cookies, no analytics and no tracking"."""
    hits = []
    for sentence, offset in _sentences(text):
        items = re.findall(r"\bno\s+[a-zA-Z-]+(?:\s+[a-zA-Z-]+){0,2}", sentence, re.IGNORECASE)
        if len(items) >= 2:
            hits.append((_line_of(text, offset), sentence[:100]))
    return hits


def find_stacked_questions(text: str) -> list[tuple[int, str]]:
    """2+ consecutive question sentences — a rhetorical-question run."""
    sentences = _sentences(text)
    hits = []
    run_start = None
    for i, (s, offset) in enumerate(sentences):
        if s.endswith("?"):
            if run_start is None:
                run_start = i
        else:
            if run_start is not None and i - run_start >= 2:
                hits.append((_line_of(text, sentences[run_start][1]), sentences[run_start][0][:100]))
            run_start = None
    if run_start is not None and len(sentences) - run_start >= 2:
        hits.append((_line_of(text, sentences[run_start][1]), sentences[run_start][0][:100]))
    return hits


ANAPHORA_SKIP = {
    "i", "it", "the", "a", "an", "this", "that", "we", "you", "they", "he", "she",
    "there", "but", "and", "so", "in", "as", "if", "my", "his", "her", "their",
    "its", "these", "those", "for", "at", "on", "of", "to", "is", "was",
}


def find_sentence_anaphora(text: str) -> list[tuple[int, str]]:
    """3+ consecutive sentences opening on the same (non-trivial) word."""
    sentences = _sentences(text)
    hits = []
    run_word, run_start = None, 0
    for i, (s, offset) in enumerate(sentences):
        match = re.match(r"[A-Za-z']+", s)
        first = match.group(0).lower() if match else None
        usable = first and first not in ANAPHORA_SKIP
        if usable and first == run_word:
            continue
        if run_word is not None and i - run_start >= 3:
            hits.append((_line_of(text, sentences[run_start][1]), sentences[run_start][0][:100]))
        run_word, run_start = (first if usable else None), i
    if run_word is not None and len(sentences) - run_start >= 3:
        hits.append((_line_of(text, sentences[run_start][1]), sentences[run_start][0][:100]))
    return hits


STRUCTURAL_CHECKS = [
    ("no-chain", '"no X, no Y" chains', find_no_chains),
    ("stacked-questions", "runs of rhetorical questions", find_stacked_questions),
    ("sentence-anaphora", "3+ sentences starting on the same word", find_sentence_anaphora),
]


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".md":
        text = strip_markdown_code(text)
    rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    findings = []

    for check_id, label, regex in REGEX_CHECKS:
        for m in regex.finditer(text):
            line = _line_of(text, m.start())
            snippet = text[max(0, m.start() - 20) : m.end() + 20].replace("\n", " ").strip()
            findings.append(f"{rel}:{line}: [{check_id}] {label} — …{snippet}…")

    # The structural checks need real sentence boundaries — a "." or "?" that
    # means end-of-sentence, not object.attribute access, a regex
    # alternation, or a CSS selector. That's only reliably true in Markdown;
    # elsewhere they fire on the file's syntax, not its English.
    if path.suffix == ".md":
        for check_id, label, finder in STRUCTURAL_CHECKS:
            for line, snippet in finder(text):
                findings.append(f"{rel}:{line}: [{check_id}] {label} — {snippet}")

    return findings


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    files = [Path(a) for a in argv] if argv else default_files()

    all_findings = []
    for path in files:
        if path.is_file():
            all_findings.extend(check_file(path))

    if not all_findings:
        print(f"clichecheck: clean ({len(files)} files checked)")
        return 0

    print(f"clichecheck: {len(all_findings)} finding(s) in {len(files)} files checked\n")
    for line in all_findings:
        print(line)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
