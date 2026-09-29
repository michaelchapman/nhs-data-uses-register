"""Agreement references, and the slugs pages are named by.

Reference numbers carry a version suffix (``DARS-NIC-00574-V2H1F-v4.2``). The
published register therefore repeats the same agreement once per renewal, which
is the single biggest reason it is hard to read. The site groups versions under
their base reference, and shows one page per agreement with its history.
"""

from __future__ import annotations

import re
import unicodedata

VERSION_SUFFIX = re.compile(r"-v([0-9]+(?:\.[0-9]+)?)$", re.IGNORECASE)

# "Smart" punctuation the register uses inconsistently for the same name —
# ST GEORGE'S vs ST GEORGE’S. NFKD + ascii-encode drops these silently rather
# than folding them to their plain-ASCII equivalent, which used to give the
# same organisation two different slugs (and so two different pages) purely
# because one row used a curly apostrophe and another a straight one.
SMART_PUNCTUATION = str.maketrans("’‘“”–—", "''\"\"--")


def slugify(value: str, max_length: int = 80) -> str:
    value = (value or "").translate(SMART_PUNCTUATION)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:max_length].strip("-") or "unknown"


def base_and_version(reference: str) -> tuple[str, str]:
    match = VERSION_SUFFIX.search(reference)
    if not match:
        return reference, ""
    return reference[: match.start()], match.group(1)


def version_key(version: str) -> tuple:
    return tuple(int(p) for p in version.split(".")) if version else (0,)
