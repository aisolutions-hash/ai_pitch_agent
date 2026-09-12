from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routers import (
    auth_router,
    contacts_router,
    email_router,
    social_router,
    system_router,
)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
        app.state.db_ready = True
    except Exception:  # pragma: no cover - depends on DB availability
        app.state.db_ready = False
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Sales pipeline: contacts, IMAP/SMTP, LinkedIn/Reddit hiring alerts.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_prefix = "/api"
app.include_router(system_router, prefix=api_prefix)
app.include_router(auth_router, prefix=api_prefix)
app.include_router(contacts_router, prefix=api_prefix)
app.include_router(email_router, prefix=api_prefix)
app.include_router(social_router, prefix=api_prefix)


@app.get("/", include_in_schema=False)
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": settings.PROJECT_NAME, "docs": "/docs"}


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
