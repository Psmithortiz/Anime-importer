import argparse
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from anime_importer.adapters.mal_xml import write_mal_xml
from anime_importer.adapters.text_files import read_titles, write_rejected_report
from anime_importer.bootstrap import build_session
from anime_importer.config import Settings
from anime_importer.ports import NormalizationError
from anime_importer.services.import_session import (
    CandidateChoice,
    Finished,
    ImportSession,
    NormalizationChoice,
    Step,
)

logger = logging.getLogger(__name__)


def describe_question(step: NormalizationChoice | CandidateChoice) -> str:
    lines = ["", "-" * 50]
    if isinstance(step, NormalizationChoice):
        lines.append(f'What did you mean by "{step.original_title}"? (LLM asking)')
        labels = list(step.options)
    else:
        lines.append(f'What did you mean by "{step.original_title}"/"{step.query}"? (MAL asking)')
        labels = [f"{c.title} (MAL id {c.mal_id})" for c in step.options]
    lines.extend(f"({number})- {label}" for number, label in enumerate(labels, start=1))
    lines.append("(X)  Discard")
    return "\n".join(lines)


def ask_option(count: int, read: Callable[[str], str] = input) -> int | None:
    """Ask for an option between 1 and `count`. Return None if the user discards with X."""
    while True:
        raw = read(f"Enter the option number (1-{count}) or X: ").strip()
        if raw.upper() == "X":
            return None
        try:
            number = int(raw)
        except ValueError:
            print("Not a number. Try again.")
            continue
        if 1 <= number <= count:
            return number
        print("Out of range. Try again.")


def run_interactive(session: ImportSession, read: Callable[[str], str] = input) -> Finished:
    step: Step = session.start()
    while not isinstance(step, Finished):
        print(describe_question(step))
        choice = ask_option(len(step.options), read)
        step = session.discard() if choice is None else session.choose(choice)
    return step


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import an anime list into MyAnimeList.")
    parser.add_argument("--input", type=Path, help="List of titles (one per line)")
    parser.add_argument("--output", type=Path, help="Path of the MAL XML output")
    parser.add_argument("--rejected", type=Path, help="Path of the rejected-titles report")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    input_path = args.input or settings.input_path
    output_path = args.output or settings.output_xml_path
    rejected_path = args.rejected or settings.rejected_report_path

    titles = read_titles(input_path)
    try:
        session = build_session(settings, titles, with_franchise=False)
    except ValueError as exc:
        logger.error("%s: %s", input_path, exc)
        return 1
    try:
        finished = run_interactive(session)
    except NormalizationError as exc:
        logger.error("%s", exc)
        return 1

    write_mal_xml(finished.imported, output_path)
    write_rejected_report(finished.rejected, rejected_path)
    print(
        f"\nImported: {len(finished.imported)} | Rejected: {len(finished.rejected)}"
        f"\nXML: {output_path} | Rejected: {rejected_path}"
    )
    return 0
