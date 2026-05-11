from __future__ import annotations

import base64
import logging
import re
import time
import threading
from typing import Dict, List, Optional

import requests

from .api_keys import KeyPool, MODEL_PRIORITY

logger = logging.getLogger(__name__)

# Models that use the OpenAI /v1/images/edits endpoint (multipart form)
_OPENAI_EDIT_MODELS = {'gpt-image-2-client', 'gpt-image-2'}

# Models that use the native Gemini endpoint
_GEMINI_NATIVE_MODELS = {'gemini-3.1-flash-image-preview'}

# Timeout for API calls (seconds)
_API_TIMEOUT = 120


class ApiClient:
    def __init__(self, key_pools: Dict[str, KeyPool], base_url: str = 'https://147ai.com') -> None:
        self._key_pools = key_pools
        self._base_url = base_url.rstrip('/')

    def generate(self, image_bytes: bytes, prompt: str, model: str, *,
                 cancel_event: Optional[threading.Event] = None,
                 **kwargs) -> List[bytes]:
        if cancel_event and cancel_event.is_set():
            from .comfy_client import CancelledError
            raise CancelledError()

        if model in _OPENAI_EDIT_MODELS:
            return self._call_openai_edit(image_bytes, prompt, model, cancel_event=cancel_event, **kwargs)
        elif model in _GEMINI_NATIVE_MODELS:
            return self._call_gemini_native(image_bytes, prompt, model, cancel_event=cancel_event, **kwargs)
        else:
            raise ValueError(f'Unknown API model: {model}')

    def _get_key(self, model: str) -> str:
        pool = self._key_pools.get(model)
        if not pool:
            raise RuntimeError(f'No API keys configured for model: {model}')
        return pool.acquire()

    def _mark_limited(self, model: str, key: str, seconds: float = 60.0) -> None:
        pool = self._key_pools.get(model)
        if pool:
            pool.mark_limited(key, seconds)

    def _call_openai_edit(self, image_bytes: bytes, prompt: str, model: str, *,
                          cancel_event: Optional[threading.Event] = None,
                          size: Optional[str] = None,
                          quality: Optional[str] = None,
                          input_fidelity: Optional[str] = None) -> List[bytes]:
        url = f'{self._base_url}/v1/images/edits'
        max_retries = 3

        for attempt in range(max_retries):
            if cancel_event and cancel_event.is_set():
                from .comfy_client import CancelledError
                raise CancelledError()

            key = self._get_key(model)
            data = {
                'model': model,
                'prompt': prompt,
            }
            if size:
                data['size'] = size
            if quality:
                data['quality'] = quality
            if input_fidelity:
                data['input_fidelity'] = input_fidelity

            files = {
                'image': ('image.png', image_bytes, 'image/png'),
            }

            try:
                resp = requests.post(
                    url, data=data, files=files,
                    headers={'Authorization': key},
                    timeout=_API_TIMEOUT,
                )
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get('Retry-After', '60'))
                    self._mark_limited(model, key, retry_after)
                    logger.warning(f'Rate limited on {model}, retry {attempt + 1}/{max_retries}')
                    continue
                if resp.status_code in (502, 503, 504):
                    logger.warning(f'Server error {resp.status_code} on {model}, retry {attempt + 1}')
                    time.sleep(2)
                    continue
                if resp.status_code >= 400:
                    raise RuntimeError(f'API request failed ({resp.status_code}): {resp.text[:1000]}')
                resp.raise_for_status()

                result = resp.json()
                images = []
                for item in result.get('data', []):
                    b64 = item.get('b64_json', '')
                    if b64:
                        images.append(base64.b64decode(b64))
                if not images:
                    raise RuntimeError(f'API returned no images: {result}')
                return images

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    logger.warning(f'Request error on {model}: {e}, retrying')
                    time.sleep(1)
                    continue
                raise

        raise RuntimeError(f'All {max_retries} attempts failed for {model}')

    def _call_gemini_native(self, image_bytes: bytes, prompt: str, model: str, *,
                            cancel_event: Optional[threading.Event] = None) -> List[bytes]:
        url = f'{self._base_url}/v1beta/models/{model}:generateContent'
        max_retries = 3
        b64_image = base64.b64encode(image_bytes).decode('ascii')

        for attempt in range(max_retries):
            if cancel_event and cancel_event.is_set():
                from .comfy_client import CancelledError
                raise CancelledError()

            key = self._get_key(model)
            payload = {
                'contents': [{
                    'role': 'user',
                    'parts': [
                        {'inlineData': {'mimeType': 'image/png', 'data': b64_image}},
                        {'text': prompt},
                    ],
                }],
                'generationConfig': {
                    'responseModalities': ['IMAGE'],
                },
            }

            try:
                resp = requests.post(
                    url, json=payload,
                    headers={
                        'Authorization': key,
                        'Content-Type': 'application/json',
                    },
                    timeout=_API_TIMEOUT,
                )
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get('Retry-After', '60'))
                    self._mark_limited(model, key, retry_after)
                    logger.warning(f'Rate limited on {model}, retry {attempt + 1}/{max_retries}')
                    continue
                if resp.status_code in (502, 503, 504):
                    logger.warning(f'Server error {resp.status_code} on {model}, retry {attempt + 1}')
                    time.sleep(2)
                    continue
                if resp.status_code >= 400:
                    raise RuntimeError(f'API request failed ({resp.status_code}): {resp.text[:1000]}')
                resp.raise_for_status()

                result = resp.json()
                images = []
                for candidate in result.get('candidates', []):
                    for part in candidate.get('content', {}).get('parts', []):
                        inline = part.get('inlineData', {})
                        data = inline.get('data', '')
                        if data:
                            images.append(base64.b64decode(data))
                if not images:
                    raise RuntimeError(f'API returned no images: {result}')
                return images

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    logger.warning(f'Request error on {model}: {e}, retrying')
                    time.sleep(1)
                    continue
                raise

        raise RuntimeError(f'All {max_retries} attempts failed for {model}')
