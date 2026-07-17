from __future__ import annotations

import re


def normalize_column_name(name: str) -> str:
    return re.sub(r"\s+", "_", name.strip())


def normalize_table_name(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name.strip()):
        return name.strip()

    safe_name = name.strip()
    safe_name = "".join(char if char.isalnum() or char in {" ", "_", "-"} else " " for char in safe_name)
    return "_".join(part for part in safe_name.split() if part)