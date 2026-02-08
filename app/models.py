from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime


class JobStatus(str, Enum):
    PENDING = "pending"
    CRAWLING = "crawling"
    GENERATING_PDF = "generating_pdf"
    DONE = "done"
    FAILED = "failed"


@dataclass
class JobInfo:
    job_id: str
    status: JobStatus = JobStatus.PENDING
    progress_message: str = ""
    filename: str = ""
    error: str = ""
    cancelled: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
