from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class JobRecord:
    job_id: str
    product_id: str = ''
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
    cancelled: bool = False
    # checkpoint fields
    image_paths: List[str] = field(default_factory=list)
    colors_text: str = ''
    completed_combos: List[List[int]] = field(default_factory=list)
    # resume params
    prompt_template: str = ''
    guidance: float = 3.5
    steps: int = 20
    steps_8: int = 8
    target_width: int = 1601
    target_height: int = 2086
    # engine fields
    engine: str = 'comfyui'
    api_model: str = ''


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobRecord] = {}

    def create(self, **kwargs) -> JobRecord:
        job_id = kwargs.pop('job_id', uuid.uuid4().hex)
        record = JobRecord(job_id=job_id, **kwargs)
        with self._lock:
            self._jobs[job_id] = record
        self._persist(record)
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
        self._persist(job)
        return job

    def list(self) -> List[JobRecord]:
        with self._lock:
            return list(self._jobs.values())

    def delete(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self._jobs:
                return False
            del self._jobs[job_id]
        from .persistence import delete_job_record
        delete_job_record(job_id)
        return True

    def to_dict(self, job_id: str) -> Optional[Dict]:
        job = self.get(job_id)
        return asdict(job) if job else None

    def restore_from_disk(self) -> None:
        from .persistence import list_all_job_records, save_job_record
        for record in list_all_job_records():
            if record.status == 'running':
                record.status = 'paused'
                record.message = 'interrupted, ready to resume'
                save_job_record(record)
            with self._lock:
                self._jobs[record.job_id] = record

    @staticmethod
    def _persist(record: JobRecord) -> None:
        from .persistence import save_job_record
        save_job_record(record)
