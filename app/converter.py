import asyncio
import glob
import io
import os
import sys
import threading

from app.job_store import JobStore
from app.models import JobStatus

# Limit to 1 concurrent conversion (stdout redirect + chdir are global, plus memory)
_conversion_semaphore = asyncio.Semaphore(1)


class ProgressCapture(io.TextIOBase):
    """Captures print() output and pushes it into an asyncio Queue as SSE events."""

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        self.queue = queue
        self.loop = loop

    def write(self, text: str) -> int:
        text = text.strip()
        if text:
            asyncio.run_coroutine_threadsafe(
                self.queue.put({"event": "progress", "data": text}),
                self.loop,
            )
        return len(text)

    def flush(self):
        pass


def _run_gitbook2pdf(url: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> str:
    """Run gitbook2pdf in a worker thread, capturing stdout for progress."""
    # Add the submodule to the import path
    submodule_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gitbook2pdf")
    if submodule_dir not in sys.path:
        sys.path.insert(0, submodule_dir)

    from gitbook2pdf import Gitbook2PDF

    capture = ProgressCapture(queue, loop)
    old_stdout = sys.stdout
    sys.stdout = capture

    try:
        # Ensure output directory exists
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
        os.makedirs(output_dir, exist_ok=True)

        # gitbook2pdf writes to ./output/ relative to CWD
        original_cwd = os.getcwd()
        os.chdir(os.path.dirname(os.path.dirname(__file__)))

        try:
            converter = Gitbook2PDF(url)
            converter.run()
        finally:
            os.chdir(original_cwd)

        # Find the newest PDF in the output directory
        pdf_files = glob.glob(os.path.join(output_dir, "*.pdf"))
        if not pdf_files:
            raise RuntimeError("Conversion completed but no PDF file was generated")
        return max(pdf_files, key=os.path.getmtime)
    finally:
        sys.stdout = old_stdout


async def run_conversion(job_id: str, url: str, store: JobStore):
    """Main entry point: acquire semaphore, run conversion in thread, update job state."""
    queue = store.get_queue(job_id)
    if not queue:
        return

    async with _conversion_semaphore:
        store.update_status(job_id, JobStatus.CRAWLING, message="Starting conversion...")
        await queue.put({"event": "progress", "data": "Starting conversion..."})

        loop = asyncio.get_running_loop()

        try:
            pdf_path = await asyncio.to_thread(_run_gitbook2pdf, url, queue, loop)
            filename = os.path.basename(pdf_path)
            store.update_status(job_id, JobStatus.DONE, filename=filename)
            await queue.put({"event": "done", "data": filename})
        except Exception as e:
            error_msg = str(e)
            store.update_status(job_id, JobStatus.FAILED, error=error_msg)
            await queue.put({"event": "error", "data": error_msg})
