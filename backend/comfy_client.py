from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List
from urllib.parse import urljoin

import requests


class ComfyClient:
    def __init__(self, comfy_url: str):
        self.comfy_url = comfy_url.rstrip('/')

    def upload_image(self, image_path: Path) -> str:
        with image_path.open('rb') as f:
            files = {'image': (image_path.name, f, 'application/octet-stream')}
            data = {'type': 'input'}
            resp = requests.post(urljoin(self.comfy_url, '/upload/image'), files=files, data=data, timeout=120)
        resp.raise_for_status()
        payload = resp.json()
        return payload['name']

    def queue_prompt(self, workflow: Dict) -> str:
        resp = requests.post(urljoin(self.comfy_url, '/prompt'), json={'prompt': workflow}, timeout=120)
        resp.raise_for_status()
        payload = resp.json()
        return payload.get('prompt_id') or payload.get('id')

    def get_history(self, prompt_id: str) -> Dict:
        resp = requests.get(urljoin(self.comfy_url, f'/history/{prompt_id}'), timeout=120)
        resp.raise_for_status()
        return resp.json()

    def wait_for_completion(self, prompt_id: str, wait_seconds: float = 2.0, timeout: float = 600.0) -> Dict:
        start = time.time()
        while True:
            history = self.get_history(prompt_id)
            if prompt_id in history:
                return history[prompt_id]
            if time.time() - start > timeout:
                raise TimeoutError(f'ComfyUI job timed out: {prompt_id}')
            time.sleep(wait_seconds)

    def view_image(self, filename: str, subfolder: str = '', type_: str = 'output') -> bytes:
        params = {'filename': filename, 'subfolder': subfolder, 'type': type_}
        resp = requests.get(urljoin(self.comfy_url, '/view'), params=params, timeout=120)
        resp.raise_for_status()
        return resp.content

    @staticmethod
    def extract_output_images(history_entry: Dict) -> List[Dict]:
        outputs = history_entry.get('outputs', {})
        images: List[Dict] = []
        for node_output in outputs.values():
            if isinstance(node_output, dict):
                images.extend(node_output.get('images', []))
                if isinstance(node_output.get('image'), dict):
                    images.append(node_output['image'])
        return images

    @staticmethod
    def collect_output_paths(output_dir: Path) -> List[Path]:
        if not output_dir.exists():
            return []
        image_exts = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
        return sorted(
            [p for p in output_dir.rglob('*') if p.is_file() and p.suffix.lower() in image_exts],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
