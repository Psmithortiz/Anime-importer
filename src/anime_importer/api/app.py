import logging
import re
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles

from anime_importer.adapters.mal_xml import render_mal_xml
from anime_importer.adapters.text_files import parse_titles
from anime_importer.api.registry import (
    InvalidStateError,
    ManagedSession,
    SessionFactory,
    SessionNotFoundError,
    SessionRegistry,
)
from anime_importer.api.schemas import (
    ChooseManyRequest,
    ChooseRequest,
    CreateSessionRequest,
    SessionView,
)

STATIC_DIR = Path(__file__).parent / "static"

_POLLING_PATH = re.compile(r"^/api/sessions/[0-9a-f]+$")


class PollingAccessFilter(logging.Filter):
    """Hides successful polling requests (GET /api/sessions/<id> → 200) from the access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5:
            return True
        _client, method, path, _http_version, status = args
        return not (
            method == "GET"
            and isinstance(path, str)
            and _POLLING_PATH.match(path) is not None
            and status == 200
        )


def get_registry(request: Request) -> SessionRegistry:
    return request.app.state.registry


RegistryDep = Annotated[SessionRegistry, Depends(get_registry)]


def get_managed(session_id: str, registry: RegistryDep) -> ManagedSession:
    try:
        return registry.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found") from None


ManagedDep = Annotated[ManagedSession, Depends(get_managed)]


def create_app(session_factory: SessionFactory | None = None) -> FastAPI:
    if session_factory is None:
        from anime_importer.bootstrap import build_session
        from anime_importer.config import Settings

        settings = Settings()

        def session_factory(titles):
            return build_session(settings, titles)

    app = FastAPI(
        title="Anime Importer",
        description="Normalize a messy anime list with Gemini and import it into MyAnimeList.",
    )
    app.state.registry = SessionRegistry(session_factory)

    # All endpoints are `def` (not `async def`): they call blocking code and FastAPI
    # runs them in a threadpool; with async def they would freeze the event loop and the polling.
    @app.post(
        "/api/sessions",
        status_code=202,
        response_model=SessionView,
        tags=["sessions"],
        summary="Create an import session",
    )
    def create_session(
        body: CreateSessionRequest, registry: RegistryDep, background: BackgroundTasks
    ) -> SessionView:
        try:
            managed = registry.create(parse_titles(body.text))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        background.add_task(managed.run_start)
        return managed.view()

    @app.get(
        "/api/sessions/{session_id}",
        response_model=SessionView,
        tags=["sessions"],
        summary="Get session state",
    )
    def get_session(managed: ManagedDep) -> SessionView:
        return managed.view()

    @app.post(
        "/api/sessions/{session_id}/choose",
        response_model=SessionView,
        tags=["sessions"],
        summary="Choose one option",
    )
    def choose(body: ChooseRequest, managed: ManagedDep) -> SessionView:
        try:
            managed.choose(body.option)
        except InvalidStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return managed.view()

    @app.post(
        "/api/sessions/{session_id}/choose-many",
        response_model=SessionView,
        tags=["sessions"],
        summary="Choose several candidates",
    )
    def choose_many(body: ChooseManyRequest, managed: ManagedDep) -> SessionView:
        try:
            managed.choose_many([(item.option, item.status) for item in body.selections])
        except InvalidStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return managed.view()

    @app.post(
        "/api/sessions/{session_id}/discard",
        response_model=SessionView,
        tags=["sessions"],
        summary="Discard current title",
    )
    def discard(managed: ManagedDep) -> SessionView:
        try:
            managed.discard()
        except InvalidStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return managed.view()

    @app.get(
        "/api/sessions/{session_id}/export.xml",
        tags=["sessions"],
        summary="Export MAL XML",
    )
    def export_xml(managed: ManagedDep, overwrite: bool = False) -> Response:
        try:
            finished = managed.finished()
        except InvalidStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return Response(
            content=render_mal_xml(finished.imported, update_on_import=overwrite),
            media_type="application/xml",
            headers={"Content-Disposition": 'attachment; filename="anime_import.xml"'},
        )

    # Mounted last so it does not shadow the /api routes.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = uvicorn.Config("anime_importer.api.app:create_app", factory=True)
    # Config configures uvicorn's logging in its constructor, so the filter goes after it.
    logging.getLogger("uvicorn.access").addFilter(PollingAccessFilter())
    uvicorn.Server(config).run()
