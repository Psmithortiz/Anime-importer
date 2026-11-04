import logging
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
from anime_importer.api.schemas import ChooseRequest, CreateSessionRequest, SessionView

STATIC_DIR = Path(__file__).parent / "static"


def get_registry(request: Request) -> SessionRegistry:
    return request.app.state.registry


RegistryDep = Annotated[SessionRegistry, Depends(get_registry)]


def get_managed(session_id: str, registry: RegistryDep) -> ManagedSession:
    try:
        return registry.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Sesión no encontrada") from None


ManagedDep = Annotated[ManagedSession, Depends(get_managed)]


def create_app(session_factory: SessionFactory | None = None) -> FastAPI:
    if session_factory is None:
        from anime_importer.bootstrap import build_session
        from anime_importer.config import Settings

        settings = Settings()

        def session_factory(titles):
            return build_session(settings, titles)

    app = FastAPI(title="Anime Importer")
    app.state.registry = SessionRegistry(session_factory)

    # Todos los endpoints son `def` (no `async def`): llaman a código bloqueante y FastAPI
    # los corre en un threadpool; con async def congelarían el event loop y el polling.
    @app.post("/api/sessions", status_code=202, response_model=SessionView)
    def create_session(
        body: CreateSessionRequest, registry: RegistryDep, background: BackgroundTasks
    ) -> SessionView:
        try:
            managed = registry.create(parse_titles(body.text))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        background.add_task(managed.run_start)
        return managed.view()

    @app.get("/api/sessions/{session_id}", response_model=SessionView)
    def get_session(managed: ManagedDep) -> SessionView:
        return managed.view()

    @app.post("/api/sessions/{session_id}/choose", response_model=SessionView)
    def choose(body: ChooseRequest, managed: ManagedDep) -> SessionView:
        try:
            managed.choose(body.option)
        except InvalidStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return managed.view()

    @app.post("/api/sessions/{session_id}/discard", response_model=SessionView)
    def discard(managed: ManagedDep) -> SessionView:
        try:
            managed.discard()
        except InvalidStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return managed.view()

    @app.get("/api/sessions/{session_id}/export.xml")
    def export_xml(managed: ManagedDep) -> Response:
        try:
            finished = managed.finished()
        except InvalidStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return Response(
            content=render_mal_xml(finished.imported),
            media_type="application/xml",
            headers={"Content-Disposition": 'attachment; filename="anime_import.xml"'},
        )

    # Se monta al final para que no tape las rutas /api.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run("anime_importer.api.app:create_app", factory=True)
