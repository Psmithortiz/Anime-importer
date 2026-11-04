from collections.abc import Sequence
from pathlib import Path

from anime_importer.domain.models import RejectedTitle


def parse_titles(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def read_titles(path: Path) -> list[str]:
    return parse_titles(path.read_text(encoding="utf-8"))


def render_rejected_report(rejected: Sequence[RejectedTitle]) -> str:
    lines = ["TITLE | REASON", "-" * 30]
    lines.extend(f"{item.original_title} | {item.reason}" for item in rejected)
    return "\n".join(lines) + "\n"


def write_rejected_report(rejected: Sequence[RejectedTitle], path: Path) -> None:
    path.write_text(render_rejected_report(rejected), encoding="utf-8")
