from pathlib import Path

from anime_importer.cli import ask_option, describe_question, main, run_interactive
from anime_importer.config import Settings
from anime_importer.domain.models import AnimeCandidate, ImportedAnime, NormalizedTitle
from anime_importer.services.import_session import CandidateChoice, Finished, ImportSession


class FakeNormalizer:
    def normalize(self, titles):
        return [NormalizedTitle(1, "Hellsing")]


class FakeSearcher:
    def search(self, query):
        return [AnimeCandidate(10, "Hellsing"), AnimeCandidate(20, "Hellsing")]


def _session() -> ImportSession:
    return ImportSession(["hellsing"], FakeNormalizer(), FakeSearcher())


def _reader(answers: list[str]):
    iterator = iter(answers)
    return lambda _prompt: next(iterator)


def test_ask_option_retries_until_valid(capsys):
    assert ask_option(3, _reader(["abc", "9", "2"])) == 2
    output = capsys.readouterr().out
    assert "No es un número" in output
    assert "Fuera de rango" in output


def test_ask_option_lowercase_x_discards():
    assert ask_option(3, _reader(["x"])) is None


def test_run_interactive_choose_option():
    finished = run_interactive(_session(), _reader(["2"]))

    assert isinstance(finished, Finished)
    assert finished.imported == (ImportedAnime(20, "Hellsing"),)


def test_run_interactive_discard():
    finished = run_interactive(_session(), _reader(["X"]))

    assert finished.imported == ()
    assert len(finished.rejected) == 1


def test_describe_question_includes_candidate_ids():
    step = CandidateChoice(
        original_title="hellsing",
        query="Hellsing",
        options=(AnimeCandidate(10, "Hellsing"), AnimeCandidate(20, "Hellsing")),
    )

    text = describe_question(step)

    assert "(MAL id 10)" in text
    assert "(MAL id 20)" in text


def test_settings_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("MAL_CLIENT_ID", "m")

    settings = Settings()

    assert settings.gemini_api_key == "k"
    assert settings.gemini_model == "gemini-2.5-flash"
    assert settings.input_path == Path("anime_list.txt")
    assert settings.output_xml_path == Path("output.xml")
    assert settings.rejected_report_path == Path("errores.txt")


def test_main_empty_input_returns_1_without_writing_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("MAL_CLIENT_ID", "m")
    empty = tmp_path / "vacio.txt"
    empty.write_text("", encoding="utf-8")

    assert main(["--input", str(empty)]) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["vacio.txt"]
