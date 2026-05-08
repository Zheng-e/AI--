from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Dict, List


MODEL_PRIORITY = ['gpt-image-2-client', 'gpt-image-2', 'gemini-3.1-flash-image-preview']


def parse_api_keys_file(path: Path) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    current_model = ''
    if not path.exists():
        return result
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('sk-'):
            if current_model:
                result.setdefault(current_model, []).append(line)
        else:
            current_model = line
    return result


class KeyPool:
    def __init__(self, keys: List[str]) -> None:
        self._keys = list(keys)
        self._index = 0
        self._lock = threading.Lock()
        self._limited: Dict[str, float] = {}

    def acquire(self) -> str:
        with self._lock:
            now = time.time()
            self._limited = {k: t for k, t in self._limited.items() if t > now}
            available = [k for k in self._keys if k not in self._limited]
            if not available:
                raise RuntimeError('All API keys are rate-limited, try again later')
            key = available[self._index % len(available)]
            self._index += 1
            return key

    def mark_limited(self, key: str, seconds: float = 60.0) -> None:
        with self._lock:
            self._limited[key] = time.time() + seconds

    def has_available(self) -> bool:
        with self._lock:
            now = time.time()
            self._limited = {k: t for k, t in self._limited.items() if t > now}
            return any(k not in self._limited for k in self._keys)
