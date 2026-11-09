from pathlib import Path

from session_helpers import make_session

from anime_importer.bootstrap import SessionServices
from anime_importer.cli import ask_option, describe_question, main, run_interactive
from anime_importer.config import Settings
from anime_importer.domain.models import AnimeCandidate, ImportedAnime, NormalizedTitle
from anime_importer.domain.session import CandidateChoice, Finished
from anime_importer.services.import_session import ImportSession


class FakeNormalizer:
    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(1, "Hellsing")]


class FakeSearcher:
    def search(self, query):
        return [AnimeCandidate(10, "Hellsing"), AnimeCandidate(20, "Hellsing")]


def _session() -> ImportSession:
    return make_session(
        ["hellsing"], FakeNormalizer(), FakeSearcher(), run_in_background=lambda fn: fn()
    )


def _reader(answers: list[str]):
    iterator = iter(answers)
    return lambda _prompt: next(iterator)


def test_ask_option_retries_until_valid(capsys):
    assert ask_option(3, _reader(["abc", "9", "2"])) == 2
    output = capsys.readouterr().out
    assert "Not a number" in output
    assert "Out of range" in output


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
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")

    assert main(["--input", str(empty)]) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["empty.txt"]


class _AutoNormalizer:
    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(1, "Naruto")]


class _AutoSearcher:
    def search(self, query):
        return [AnimeCandidate(20, "Naruto")]


def test_main_writes_xml_with_update_on_import_one(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("MAL_CLIENT_ID", "m")
    monkeypatch.setattr(
        "anime_importer.cli.build_services",
        lambda settings, repository, with_franchise=True: SessionServices(
            repository=repository,
            normalizer=_AutoNormalizer(),
            searcher=_AutoSearcher(),
            franchise_finder=None,
            resolution_buffer=20,
            run_in_background=lambda fn: fn(),
        ),
    )
    titles = tmp_path / "list.txt"
    titles.write_text("naruto\n", encoding="utf-8")
    output = tmp_path / "out.xml"

    code = main(["--input", str(titles), "--output", str(output)])

    assert code == 0
    assert "<update_on_import>1</update_on_import>" in output.read_text(encoding="utf-8")


def test_main_without_keys_exits_with_2_naming_them(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("MAL_CLIENT_ID", raising=False)

    assert main(["--input", str(tmp_path / "x.txt")]) == 2
    assert "GEMINI_API_KEY" in caplog.text
    assert "MAL_CLIENT_ID" in caplog.text
