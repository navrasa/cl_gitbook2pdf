import asyncio
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from sse_starlette.sse import EventSourceResponse

from app.converter import run_conversion
from app.job_store import JobStore
from app.models import JobStatus

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")


async def periodic_cleanup(store: JobStore):
    """Remove jobs and output files older than 1 hour, every 10 minutes."""
    while True:
        await asyncio.sleep(600)
        store.cleanup_old_jobs(max_age_seconds=3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store = JobStore()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cleanup_task = asyncio.create_task(periodic_cleanup(app.state.store))
    yield
    cleanup_task.cancel()


app = FastAPI(title="GitBook to PDF", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ConvertRequest(BaseModel):
    url: HttpUrl


class ConvertResponse(BaseModel):
    job_id: str


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    with open(index_path) as f:
        return HTMLResponse(f.read())


@app.post("/convert", response_model=ConvertResponse, status_code=202)
async def convert(req: ConvertRequest):
    store: JobStore = app.state.store
    job_id = uuid.uuid4().hex[:12]
    store.create_job(job_id)
    asyncio.create_task(run_conversion(job_id, str(req.url), store))
    return ConvertResponse(job_id=job_id)


@app.get("/jobs/{job_id}/status")
async def job_status(job_id: str, request: Request):
    store: JobStore = app.state.store
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    queue = store.get_queue(job_id)

    async def event_generator():
        # If already terminal, send final event and stop
        if job.status == JobStatus.DONE:
            yield {"event": "done", "data": job.filename}
            return
        if job.status == JobStatus.FAILED:
            yield {"event": "failed", "data": job.error}
            return

        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield msg
                if msg["event"] in ("done", "failed"):
                    break
            except asyncio.TimeoutError:
                # Send keepalive
                yield {"event": "ping", "data": ""}

    return EventSourceResponse(event_generator())


@app.get("/jobs/{job_id}/download")
async def download(job_id: str):
    store: JobStore = app.state.store
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.DONE:
        raise HTTPException(status_code=409, detail="PDF not ready yet")

    pdf_path = os.path.join(OUTPUT_DIR, job.filename)
    if not os.path.isfile(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=job.filename,
        headers={"Content-Disposition": f'attachment; filename="{job.filename}"'},
    )
