import logging

from anime_importer.api.app import PollingAccessFilter

SESSION_ID = "0123456789abcdef"


def make_record(args) -> logging.LogRecord:
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "msg", None, None)
    record.args = args
    return record


def access_args(method: str, path: str, status: int) -> tuple:
    return ("127.0.0.1:5000", method, path, "1.1", status)


def test_hides_successful_polling():
    record = make_record(access_args("GET", f"/api/sessions/{SESSION_ID}", 200))
    assert PollingAccessFilter().filter(record) is False


def test_keeps_polling_with_error_status():
    record = make_record(access_args("GET", f"/api/sessions/{SESSION_ID}", 404))
    assert PollingAccessFilter().filter(record) is True


def test_keeps_choose_post():
    record = make_record(access_args("POST", f"/api/sessions/{SESSION_ID}/choose", 200))
    assert PollingAccessFilter().filter(record) is True


def test_keeps_export_download():
    record = make_record(access_args("GET", f"/api/sessions/{SESSION_ID}/export.xml", 200))
    assert PollingAccessFilter().filter(record) is True


def test_keeps_record_with_unexpected_args():
    assert PollingAccessFilter().filter(make_record(("only", "two"))) is True
    assert PollingAccessFilter().filter(make_record(None)) is True
