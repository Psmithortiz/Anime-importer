from anime_importer.adapters.text_files import (
    parse_titles,
    read_titles,
    render_rejected_report,
    write_rejected_report,
)
from anime_importer.domain.models import RejectedTitle


def test_read_titles_ignores_blank_lines_and_whitespace(tmp_path):
    path = tmp_path / "lista.txt"
    path.write_text("  Naruto  \n\n   \nBleach\nÑandú\n", encoding="utf-8")

    assert read_titles(path) == ["Naruto", "Bleach", "Ñandú"]


def test_render_rejected_report():
    report = render_rejected_report(
        [RejectedTitle("Foo", "no encontrado"), RejectedTitle("Bar", "sin coincidencia")]
    )

    assert report == (
        "TITULO | MOTIVO DEL ERROR\n"
        "------------------------------\n"
        "Foo | no encontrado\n"
        "Bar | sin coincidencia\n"
    )


def test_render_rejected_report_empty_has_only_header():
    assert render_rejected_report([]) == "TITULO | MOTIVO DEL ERROR\n" + "-" * 30 + "\n"


def test_write_rejected_report(tmp_path):
    path = tmp_path / "bad.txt"
    rejected = [RejectedTitle("Foo", "no encontrado")]
    write_rejected_report(rejected, path)

    assert path.read_text(encoding="utf-8") == render_rejected_report(rejected)


def test_parse_titles_strips_and_drops_blank_lines():
    assert parse_titles("  a \n\n b\r\n") == ["a", "b"]
