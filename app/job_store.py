import asyncio
import os
import time
from app.models import JobInfo, JobStatus


class JobStore:
    def __init__(self):
        self.jobs: dict[str, JobInfo] = {}
        self.queues: dict[str, asyncio.Queue] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}

    def create_job(self, job_id: str) -> JobInfo:
        job = JobInfo(job_id=job_id)
        self.jobs[job_id] = job
        self.queues[job_id] = asyncio.Queue()
        return job

    def get_job(self, job_id: str) -> JobInfo | None:
        return self.jobs.get(job_id)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        message: str = "",
        filename: str = "",
        error: str = "",
    ):
        job = self.jobs.get(job_id)
        if not job:
            return
        job.status = status
        if message:
            job.progress_message = message
        if filename:
            job.filename = filename
        if error:
            job.error = error

    def get_queue(self, job_id: str) -> asyncio.Queue | None:
        return self.queues.get(job_id)

    def set_process(self, job_id: str, proc: asyncio.subprocess.Process):
        self.processes[job_id] = proc

    async def cancel_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status in (JobStatus.DONE, JobStatus.FAILED):
            return False
        job.cancelled = True
        proc = self.processes.pop(job_id, None)
        if proc and proc.returncode is None:
            proc.kill()
        self.update_status(job_id, JobStatus.FAILED, error="Cancelled by user")
        queue = self.queues.get(job_id)
        if queue:
            await queue.put({"event": "failed", "data": "Cancelled by user"})
        return True

    def cleanup_old_jobs(self, max_age_seconds: int = 3600):
        now = time.time()
        to_delete = []
        for job_id, job in self.jobs.items():
            age = now - job.created_at.timestamp()
            if age > max_age_seconds:
                to_delete.append(job_id)

        for job_id in to_delete:
            job = self.jobs.pop(job_id, None)
            self.queues.pop(job_id, None)
            if job and job.filename:
                pdf_path = os.path.join("output", job.filename)
                html_path = pdf_path.replace(".pdf", ".html")
                for path in (pdf_path, html_path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
