from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


COMBO_FINISHED_STATUSES = {'completed', 'failed', 'cancelled'}


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
    combos: List[Dict] = field(default_factory=list)
    total_combos: int = 0
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    active_count: int = 0


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobRecord] = {}

    def create(self, **kwargs) -> JobRecord:
        job_id = kwargs.pop('job_id', uuid.uuid4().hex)
        record = JobRecord(job_id=job_id, **kwargs)
        record.created_at = record.created_at or time.time()
        record.updated_at = record.updated_at or record.created_at
        self._recalculate(record)
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
            job.updated_at = kwargs.get('updated_at', time.time())
            self._recalculate(job)
        self._persist(job)
        return job

    def update_combo(self, job_id: str, image_index: int, color_index: int, **kwargs) -> Optional[JobRecord]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            combo = self._find_combo(job, image_index, color_index)
            if not combo:
                return None
            combo.update(kwargs)
            job.updated_at = time.time()
            self._recalculate(job)
        self._persist(job)
        return job

    def list(self) -> List[JobRecord]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

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
            if record.status in ('running', 'cancelling'):
                record.status = 'paused'
                record.message = '服务重启后暂停，可重试未完成组合'
                for combo in record.combos:
                    if combo.get('status') == 'running':
                        combo['status'] = 'queued'
                        combo['started_at'] = None
                        combo['finished_at'] = None
                save_job_record(record)
            self._recalculate(record)
            with self._lock:
                self._jobs[record.job_id] = record

    @staticmethod
    def _find_combo(record: JobRecord, image_index: int, color_index: int) -> Optional[Dict]:
        for combo in record.combos:
            if combo.get('image_index') == image_index and combo.get('color_index') == color_index:
                return combo
        return None

    @staticmethod
    def _recalculate(record: JobRecord) -> None:
        if not record.combos:
            n_colors = max(1, len(record.colors)) if record.colors else 0
            total = len(record.image_paths) * n_colors
            completed = len(record.completed_combos or [])
            if not completed and record.status == 'completed' and total:
                completed = total

            record.total_combos = total or record.total_combos
            record.completed_count = completed
            record.failed_count = 1 if record.status == 'failed' and not completed else 0
            record.cancelled_count = 1 if record.status == 'cancelled' else 0
            record.active_count = 1 if record.status == 'running' else 0
            if record.status == 'completed' and record.total_combos:
                record.progress = 100
            return

        total = len(record.combos)
        completed = sum(1 for combo in record.combos if combo.get('status') == 'completed')
        failed = sum(1 for combo in record.combos if combo.get('status') == 'failed')
        cancelled = sum(1 for combo in record.combos if combo.get('status') == 'cancelled')
        active = sum(1 for combo in record.combos if combo.get('status') == 'running')
        finished = sum(1 for combo in record.combos if combo.get('status') in COMBO_FINISHED_STATUSES)

        record.total_combos = total
        record.completed_count = completed
        record.failed_count = failed
        record.cancelled_count = cancelled
        record.active_count = active
        record.completed_combos = [
            [combo['image_index'], combo['color_index']]
            for combo in record.combos
            if combo.get('status') == 'completed'
        ]
        record.progress = int((finished / total) * 100) if total else record.progress

    @staticmethod
    def _persist(record: JobRecord) -> None:
        from .persistence import save_job_record
        save_job_record(record)
