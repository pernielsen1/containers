import json
import os
import unicodedata
from typing import Dict


def _load_translation_table() -> Dict[str, str]:
    table_path = os.path.join(os.path.dirname(__file__), "util_convert_table.json")
    try:
        with open(table_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def _can_encode_iso8859_2(char: str) -> bool:
    try:
        char.encode("iso-8859-2")
        return True
    except UnicodeEncodeError:
        return False


class UtilConvert:
    _translation_table: Dict[str, str] = _load_translation_table()

    @classmethod
    def utf8_to_iso8859_2(cls, s: str) -> str:
        if s is None:
            return ""

        translated_chars = []
        for char in s:
            if ord(char) < 0x20:
                translated_chars.append(" ")
                continue

            if char in cls._translation_table:
                translated_chars.append(cls._translation_table[char])
                continue

            if _can_encode_iso8859_2(char):
                translated_chars.append(char)
                continue

            normalized = unicodedata.normalize("NFKD", char)
            fallback = next(
                (c for c in normalized if _can_encode_iso8859_2(c)),
                None,
            )
            if fallback:
                translated_chars.append(fallback)
                continue

            ascii_fallback = next(
                (c for c in normalized if ord(c) < 128 and c.isprintable()),
                "?",
            )
            translated_chars.append(ascii_fallback)

        return "".join(translated_chars)
