# src/main.py - app FastAPI con health, readiness e lifecycle cache/db
import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api import accounts, admin, advice, agent, auth, categorize, chat, glossary, movements
from src.cache import chiudi_redis, get_redis
from src.config import settings
from src.db.session import AsyncSessionLocal, engine
from src.exceptions import AppError, RateLimitError
from src.observability.json_log import configura_log, request_id
from src.types.error import ErrorResponse

configura_log()
logger = logging.getLogger(__name__)
ID_VALIDO = re.compile(r"[A-Za-z0-9-]{8,64}")


class Credentials(BaseModel):
    openai: bool
    anthropic: bool


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    app_name: str
    version: str
    environment: str
    credentials: Credentials


class ComponenteReady(BaseModel):
    stato: str
    dettaglio: str | None = None


class ReadyResponse(BaseModel):
    status: str
    timestamp: str
    controlli: dict[str, ComponenteReady]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await chiudi_redis()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="LipariBank AI Assistant",
    lifespan=lifespan,
)


def _busta(
    req: Request, status: int, codice: str, messaggio: str, dettagli: list[str] | None = None
) -> dict[str, object]:
    return ErrorResponse(
        timestamp=datetime.now(UTC),
        status=status,
        error=codice,
        message=messaggio,
        path=req.url.path,
        details=dettagli,
    ).model_dump(mode="json")


@app.exception_handler(AppError)
async def handle_app_error(req: Request, exc: AppError) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimitError) else None
    return JSONResponse(
        status_code=exc.status_code,
        headers=headers,
        content=_busta(req, exc.status_code, exc.code, exc.message),
    )


CODICI_HTTP = {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
}


@app.exception_handler(StarletteHTTPException)
async def handle_http(req: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content=_busta(
            req, exc.status_code, CODICI_HTTP.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)
        ),
    )


def _campo(loc: tuple[int | str, ...]) -> str:
    return ".".join(str(p) for p in loc[1:]) or str(loc[0])


@app.exception_handler(RequestValidationError)
async def handle_validation(req: Request, exc: RequestValidationError) -> JSONResponse:
    dettagli = [
        f"{'corpo' if e['type'] == 'json_invalid' else _campo(e['loc'])}: {e['msg']}"
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_busta(req, 422, "VALIDATION_ERROR", "La richiesta non e valida", dettagli),
    )


@app.exception_handler(Exception)
async def handle_unexpected(req: Request, exc: Exception) -> JSONResponse:
    logger.exception("errore_non_gestito", extra={"path": req.url.path})
    return JSONResponse(
        status_code=500,
        headers={"X-Request-Id": getattr(req.state, "request_id", "-")},
        content=_busta(req, 500, "INTERNAL_ERROR", "Errore inatteso"),
    )


@app.middleware("http")
async def add_request_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    ricevuto = request.headers.get("X-Request-Id", "")
    rid = ricevuto if ID_VALIDO.fullmatch(ricevuto) else str(uuid.uuid4())
    request_id.set(rid)
    request.state.request_id = rid
    inizio = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-Id"] = rid
    response.headers["X-Process-Time"] = f"{time.perf_counter() - inizio:.4f}"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
)


async def _database() -> ComponenteReady:
    try:
        async with AsyncSessionLocal() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=1.0)
        return ComponenteReady(stato="ok")
    except Exception:
        return ComponenteReady(stato="errore", dettaglio="database non raggiungibile")


async def _cache_check() -> ComponenteReady:
    r = get_redis()
    if r is None:
        return ComponenteReady(stato="disattivata")
    try:
        await asyncio.wait_for(r.ping(), timeout=0.2)
        return ComponenteReady(stato="ok")
    except Exception:
        return ComponenteReady(stato="degradata", dettaglio="cache non raggiungibile")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="UP",
        timestamp=datetime.now(UTC).isoformat(),
        app_name=settings.app_name,
        version="1.0.0",
        environment=settings.environment,
        credentials=Credentials(
            openai=bool(settings.openai_api_key),
            anthropic=bool(settings.anthropic_api_key),
        ),
    )


@app.get("/ready", response_model=ReadyResponse)
async def ready() -> JSONResponse:
    db = await _database()
    cache = await _cache_check()
    ready_ok = db.stato == "ok"
    status = "READY" if ready_ok else "NOT_READY"
    payload = ReadyResponse(
        status=status,
        timestamp=datetime.now(UTC).isoformat(),
        controlli={"database": db, "cache": cache},
    )
    return JSONResponse(
        status_code=200 if ready_ok else 503,
        content=payload.model_dump(mode="json"),
    )


app.include_router(chat.router)
app.include_router(glossary.router)
app.include_router(categorize.router)
app.include_router(movements.router)
app.include_router(accounts.router)
app.include_router(advice.router)
app.include_router(auth.router)
app.include_router(agent.router)
app.include_router(admin.router)
app.state.limiter = advice.limiter


@app.exception_handler(RateLimitExceeded)
async def handle_rate_limit(req: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": "60"},
        content=_busta(req, 429, "RATE_LIMIT", "Troppe richieste: riprova fra un minuto"),
    )
