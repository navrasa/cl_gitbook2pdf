import asyncio
import glob
import os
import shutil
import sys

from app.job_store import JobStore
from app.models import JobStatus

# Limit to 1 concurrent conversion (memory protection)
_conversion_semaphore = asyncio.Semaphore(1)

# Paths
_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_SUBMODULE_DIR = os.path.join(_PROJECT_ROOT, "gitbook2pdf")
_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "output")


async def run_conversion(job_id: str, url: str, store: JobStore):
    """Run gitbook2pdf as a subprocess, streaming stdout lines as SSE progress events."""
    queue = store.get_queue(job_id)
    if not queue:
        return

    async with _conversion_semaphore:
        store.update_status(job_id, JobStatus.CRAWLING, message="Starting conversion...")
        await queue.put({"event": "progress", "data": "Starting conversion..."})

        os.makedirs(_OUTPUT_DIR, exist_ok=True)

        # Ensure the submodule has an output directory too
        submodule_output = os.path.join(_SUBMODULE_DIR, "output")
        os.makedirs(submodule_output, exist_ok=True)

        try:
            # Run gitbook2pdf as a separate process — completely avoids event loop conflicts
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "gitbook.py", url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=_SUBMODULE_DIR,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )

            # Stream stdout line by line to SSE
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    await queue.put({"event": "progress", "data": text})

            await proc.wait()

            if proc.returncode != 0:
                raise RuntimeError(f"gitbook2pdf exited with code {proc.returncode}")

            # Find the newest PDF in the submodule's output directory
            pdf_files = glob.glob(os.path.join(submodule_output, "*.pdf"))
            if not pdf_files:
                raise RuntimeError("Conversion completed but no PDF file was generated")

            newest_pdf = max(pdf_files, key=os.path.getmtime)
            filename = os.path.basename(newest_pdf)

            # Move to our output directory
            final_path = os.path.join(_OUTPUT_DIR, filename)
            shutil.move(newest_pdf, final_path)

            store.update_status(job_id, JobStatus.DONE, filename=filename)
            await queue.put({"event": "done", "data": filename})

        except Exception as e:
            error_msg = str(e)
            store.update_status(job_id, JobStatus.FAILED, error=error_msg)
            await queue.put({"event": "failed", "data": error_msg})
