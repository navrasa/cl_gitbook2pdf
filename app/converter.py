import asyncio
import glob
import os
import sys

from app.job_store import JobStore
from app.models import JobStatus

# Limit to 1 concurrent conversion (memory protection)
_conversion_semaphore = asyncio.Semaphore(1)

# Paths
_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_SCRAPER_PATH = os.path.join(_PROJECT_ROOT, "scraper.py")
_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "output")


async def run_conversion(job_id: str, url: str, include_subpages: bool, store: JobStore):
    """Run the Playwright scraper as a subprocess, streaming progress via SSE."""
    queue = store.get_queue(job_id)
    if not queue:
        return

    async with _conversion_semaphore:
        store.update_status(job_id, JobStatus.CRAWLING, message="Starting conversion...")
        await queue.put({"event": "progress", "data": "Starting conversion..."})

        os.makedirs(_OUTPUT_DIR, exist_ok=True)

        try:
            cmd = [sys.executable, _SCRAPER_PATH, url, _OUTPUT_DIR]
            if include_subpages:
                cmd.append("--subpages")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            store.set_process(job_id, proc)

            # Stream stdout line by line to SSE
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    await queue.put({"event": "progress", "data": text})

            await proc.wait()

            # If cancelled, the cancel handler already sent the failure event
            job = store.get_job(job_id)
            if job and job.cancelled:
                return

            if proc.returncode != 0:
                raise RuntimeError(f"Scraper exited with code {proc.returncode}")

            # Find the newest PDF in the output directory
            pdf_files = glob.glob(os.path.join(_OUTPUT_DIR, "*.pdf"))
            if not pdf_files:
                raise RuntimeError("Conversion completed but no PDF file was generated")

            newest_pdf = max(pdf_files, key=os.path.getmtime)
            filename = os.path.basename(newest_pdf)

            store.update_status(job_id, JobStatus.DONE, filename=filename)
            await queue.put({"event": "done", "data": filename})

        except Exception as e:
            error_msg = str(e)
            store.update_status(job_id, JobStatus.FAILED, error=error_msg)
            await queue.put({"event": "failed", "data": error_msg})
