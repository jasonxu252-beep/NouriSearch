"""Text normalization shared by ingest and search, so stored names and queries always match."""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")


def _strip_latin_accents(value: str) -> str:
    """Removes accents from Latin letters only.

    Combining marks carry meaning in other scripts. Japanese voicing marks and Hindi vowel signs
    are combining marks too, and removing them would change the word.
    """
    output = []
    for char in value:
        if not char.isascii() and "LATIN" in unicodedata.name(char, ""):
            decomposed = unicodedata.normalize("NFD", char)
            output.append("".join(c for c in decomposed if not unicodedata.combining(c)))
        else:
            output.append(char)
    return "".join(output)


def normalize_name(value: str) -> str:
    """Folds width, case, Latin accents, and punctuation, and keeps every script's letters."""
    composed = unicodedata.normalize("NFKC", value).casefold()
    folded = _strip_latin_accents(composed)
    spaced = "".join(" " if unicodedata.category(c)[0] in "PS" else c for c in folded)
    return _WHITESPACE.sub(" ", spaced).strip()


def slugify(value: str) -> str:
    """A readable identifier. Callers add a suffix when uniqueness needs it."""
    return normalize_name(value).replace(" ", "-")
