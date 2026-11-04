import argparse
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from google import genai

from anime_importer.adapters.gemini import GeminiNormalizer
from anime_importer.adapters.mal import MalSearcher
from anime_importer.adapters.mal_xml import write_mal_xml
from anime_importer.adapters.text_files import read_titles, write_rejected_report
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


def build_session(settings: Settings, titles: Sequence[str]) -> ImportSession:
    """Raíz de composición: el único lugar que decide qué adaptadores concretos se usan."""
    client = genai.Client(api_key=settings.gemini_api_key)
    normalizer = GeminiNormalizer(client=client, model=settings.gemini_model)
    return ImportSession(
        titles, normalizer=normalizer, searcher=MalSearcher(client_id=settings.mal_client_id)
    )


def describe_question(step: NormalizationChoice | CandidateChoice) -> str:
    lines = ["", "-" * 50]
    if isinstance(step, NormalizationChoice):
        lines.append(f'¿Qué quisiste decir con "{step.original_title}"? (LLM preguntando)')
        labels = list(step.options)
    else:
        lines.append(
            f'¿Qué quisiste decir con "{step.original_title}"/"{step.query}"? (MAL preguntando)'
        )
        labels = [f"{c.title} (MAL id {c.mal_id})" for c in step.options]
    lines.extend(f"({number})- {label}" for number, label in enumerate(labels, start=1))
    lines.append("(X)  Descartar")
    return "\n".join(lines)


def ask_option(count: int, read: Callable[[str], str] = input) -> int | None:
    """Pide una opción entre 1 y `count`. Devuelve None si el usuario descarta con X."""
    while True:
        raw = read(f"Ingresa el número de opción (1-{count}) o X: ").strip()
        if raw.upper() == "X":
            return None
        try:
            number = int(raw)
        except ValueError:
            print("No es un número. Intenta de nuevo.")
            continue
        if 1 <= number <= count:
            return number
        print("Fuera de rango. Intenta de nuevo.")


def run_interactive(session: ImportSession, read: Callable[[str], str] = input) -> Finished:
    step: Step = session.start()
    while not isinstance(step, Finished):
        print(describe_question(step))
        choice = ask_option(len(step.options), read)
        step = session.discard() if choice is None else session.choose(choice)
    return step


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa una lista de anime a MyAnimeList.")
    parser.add_argument("--input", type=Path, help="Lista de títulos (uno por línea)")
    parser.add_argument("--output", type=Path, help="Ruta del XML para MAL")
    parser.add_argument("--rejected", type=Path, help="Ruta del reporte de errores")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    input_path = args.input or settings.input_path
    output_path = args.output or settings.output_xml_path
    rejected_path = args.rejected or settings.rejected_report_path

    titles = read_titles(input_path)
    try:
        session = build_session(settings, titles)
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
        f"\nImportados: {len(finished.imported)} | Rechazados: {len(finished.rejected)}"
        f"\nXML: {output_path} | Errores: {rejected_path}"
    )
    return 0
