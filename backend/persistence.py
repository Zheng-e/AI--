from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from .config import STORAGE_DIR
from .jobs import JobRecord

logger = logging.getLogger(__name__)

JOBS_DIR = STORAGE_DIR / 'jobs'


def _ensure_dir() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)


def save_job_record(record: JobRecord) -> None:
    _ensure_dir()
    path = JOBS_DIR / f'{record.job_id}.json'
    data = asdict(record)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def load_job_record(job_id: str) -> Optional[JobRecord]:
    path = JOBS_DIR / f'{job_id}.json'
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return JobRecord(**data)
    except Exception:
        logger.exception('Failed to load job record %s', job_id)
        return None


def list_all_job_records() -> List[JobRecord]:
    _ensure_dir()
    records = []
    for path in JOBS_DIR.glob('*.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            records.append(JobRecord(**data))
        except Exception:
            logger.exception('Failed to load job record from %s', path)
    return records


def delete_job_record(job_id: str) -> None:
    path = JOBS_DIR / f'{job_id}.json'
    if path.exists():
        path.unlink(missing_ok=True)
