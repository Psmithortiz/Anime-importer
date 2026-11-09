import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import uvicorn
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from anime_importer.adapters.mal_xml import render_mal_xml
from anime_importer.adapters.text_files import parse_titles
from anime_importer.api.registry import (
    InvalidStateError,
    ManagedSession,
    NotConfiguredError,
    SessionNotFoundError,
    SessionRegistry,
)
from anime_importer.api.schemas import (
    AppInfo,
    ChooseManyRequest,
    ChooseRequest,
    ConfigUpdate,
    ConfigView,
    CreateSessionRequest,
    SessionSummaryOut,
    SessionView,
)
from anime_importer.ports import PersistenceError

if TYPE_CHECKING:
    from anime_importer.bootstrap import FileConfigurator
    from anime_importer.config import Settings

logger = logging.getLogger(__name__)

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


class RevalidatingStaticFiles(StaticFiles):
    """StaticFiles that makes the browser revalidate on every load.

    Without Cache-Control browsers apply heuristic caching and keep running an old app.js after
    an update. `no-cache` still allows a 304 answer thanks to the ETag/Last-Modified headers.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def get_registry(request: Request) -> SessionRegistry:
    return request.app.state.registry


RegistryDep = Annotated[SessionRegistry, Depends(get_registry)]


def get_managed(session_id: str, registry: RegistryDep) -> ManagedSession:
    try:
        return registry.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found") from None


ManagedDep = Annotated[ManagedSession, Depends(get_managed)]


def create_app(
    registry: SessionRegistry | None = None,
    demo_text: str | None = None,
    configurator: "FileConfigurator | None" = None,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    if registry is None:
        from anime_importer.adapters.sqlite_repository import SqliteSessionRepository
        from anime_importer.bootstrap import FileConfigurator, build_provider
        from anime_importer.config import Settings, config_file_path

        settings = Settings()
        if settings.demo:
            demo_text = (settings.demo_data_dir / "list.txt").read_text(encoding="utf-8")
        database = settings.demo_database_path if settings.demo else settings.database_path
        repository = SqliteSessionRepository(database)
        # Everything is built ONCE per app: adapters (throttle, caches) are shared by all sessions.
        registry = SessionRegistry(build_provider(settings, repository))
        configurator = FileConfigurator(registry, repository, config_file_path())
        allowed_hosts = settings.allowed_hosts

    app = FastAPI(
        title="Anime Importer",
        description="Normalize a messy anime list with Gemini and import it into MyAnimeList.",
    )
    if allowed_hosts is not None:
        # Rejects requests whose Host header is not ours (DNS rebinding protection).
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.state.registry = registry

    @app.exception_handler(PersistenceError)
    def persistence_error(request: Request, exc: PersistenceError) -> JSONResponse:
        logger.error("Persistence error on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=503, content={"detail": "Could not save the session; try again"}
        )

    @app.exception_handler(SessionNotFoundError)
    def session_not_found(request: Request, exc: SessionNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Session not found"})

    @app.exception_handler(NotConfiguredError)
    def not_configured(request: Request, exc: NotConfiguredError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "Configure your API keys first"})

    @app.get("/api/info", response_model=AppInfo, tags=["meta"], summary="App mode info")
    def info() -> AppInfo:
        configured = configurator.configured if configurator is not None else True
        return AppInfo(demo=demo_text is not None, configured=configured, sample_text=demo_text)

    @app.get("/api/config", response_model=ConfigView, tags=["meta"], summary="API key status")
    def get_config() -> ConfigView:
        if configurator is None:
            raise HTTPException(status_code=404, detail="Not found")
        return configurator.status()

    @app.put("/api/config", response_model=ConfigView, tags=["meta"], summary="Save API keys")
    def put_config(body: ConfigUpdate) -> ConfigView:
        if configurator is None:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            return configurator.save(body.model_dump(exclude_none=True))
        except InvalidStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

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
        "/api/sessions",
        response_model=list[SessionSummaryOut],
        tags=["sessions"],
        summary="List recent sessions",
    )
    def list_sessions(
        registry: RegistryDep, limit: Annotated[int, Query(ge=1, le=100)] = 20
    ) -> list[SessionSummaryOut]:
        return [
            SessionSummaryOut(
                id=item.id,
                created_at=item.created_at,
                updated_at=item.updated_at,
                title_count=item.title_count,
                preview=list(item.preview),
                decision_count=item.decision_count,
            )
            for item in registry.list_recent(limit)
        ]

    @app.get(
        "/api/sessions/{session_id}",
        response_model=SessionView,
        tags=["sessions"],
        summary="Get session state",
    )
    def get_session(managed: ManagedDep) -> SessionView:
        return managed.view()

    @app.delete(
        "/api/sessions/{session_id}",
        status_code=204,
        tags=["sessions"],
        summary="Delete a session",
    )
    def delete_session(session_id: str, registry: RegistryDep) -> Response:
        try:
            registry.delete(session_id)
        except InvalidStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return Response(status_code=204)

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
            managed.choose_many([(item.mal_id, item.status) for item in body.selections])
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

    @app.post(
        "/api/sessions/{session_id}/undo",
        response_model=SessionView,
        tags=["sessions"],
        summary="Undo the last decision",
    )
    def undo(managed: ManagedDep) -> SessionView:
        try:
            managed.undo()
        except InvalidStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return managed.view()

    @app.post(
        "/api/sessions/{session_id}/retry",
        status_code=202,
        response_model=SessionView,
        tags=["sessions"],
        summary="Rebuild a failed session and start it again",
    )
    def retry(session_id: str, registry: RegistryDep) -> SessionView:
        try:
            managed = registry.retry(session_id)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="Session not found") from None
        except InvalidStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return managed.view()

    @app.get(
        "/api/sessions/{session_id}/export.xml",
        tags=["sessions"],
        summary="Export MAL XML",
    )
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

    # Mounted last so it does not shadow the /api routes.
    app.mount("/", RevalidatingStaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def build_server(settings: "Settings") -> uvicorn.Server:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = uvicorn.Config(
        "anime_importer.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
    )
    # Config configures uvicorn's logging in its constructor, so the filter goes after it.
    logging.getLogger("uvicorn.access").addFilter(PollingAccessFilter())
    return uvicorn.Server(config)


def run() -> None:
    from anime_importer.config import Settings

    build_server(Settings()).run()
