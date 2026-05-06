from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class JobRecord:
    job_id: str
    status: str = 'created'
    progress: int = 0
    message: str = 'created'
    output_dir: Optional[str] = None
    input_name: Optional[str] = None
    garment_name: Optional[str] = None
    colors: List[Dict] = field(default_factory=list)
    prompt: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    error: Optional[str] = None


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobRecord] = {}

    def create(self, **kwargs) -> JobRecord:
        job_id = kwargs.pop('job_id', uuid.uuid4().hex)
        record = JobRecord(job_id=job_id, **kwargs)
        with self._lock:
            self._jobs[job_id] = record
        return record

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs) -> Optional[JobRecord]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            for key, value in kwargs.items():
                setattr(job, key, value)
            return job

    def list(self) -> List[JobRecord]:
        with self._lock:
            return list(self._jobs.values())

    def to_dict(self, job_id: str) -> Optional[Dict]:
        job = self.get(job_id)
        return asdict(job) if job else None
