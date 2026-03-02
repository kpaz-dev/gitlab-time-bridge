import logging
from fastapi import FastAPI
from app.routes.webhook import router as webhook_router


def create_app() -> FastAPI:
    # Basic structured logging (key=value style)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = FastAPI(title="GitLab-Teamwork Time Sync", version="0.1.0")
    app.include_router(webhook_router, prefix="/webhook", tags=["webhook"])
    return app


app = create_app()
