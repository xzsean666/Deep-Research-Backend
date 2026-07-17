import uuid

from fastapi import FastAPI, Request

from app.api.errors import EXCEPTION_HANDLERS
from app.api.routers import ALL_ROUTERS

app = FastAPI(title="Deep Research Backend", version="0.1.0")

for exc_type, handler in EXCEPTION_HANDLERS.items():
    app.add_exception_handler(exc_type, handler)

for router in ALL_ROUTERS:
    app.include_router(router)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response
