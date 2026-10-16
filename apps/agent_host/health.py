from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from supplymesh.persistence.database import get_engine

app = FastAPI(title="SupplyMesh Agent Host", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-host"}


@app.get("/ready")
def ready() -> dict[str, str]:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return {"status": "not_ready", "reason": type(exc).__name__}
    return {"status": "ready", "database": "ok"}
