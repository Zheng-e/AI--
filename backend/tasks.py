from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zipfile import ZipFile

from .config import (
    COMFY_URL,
    DEFAULT_COLORS_TXT,
    DEFAULT_WORKFLOW,
    OUTPUT_DIR,
    STORAGE_DIR,
)
from .comfy_client import ComfyClient
from .jobs import JobStore
from .workflow import build_prompt, load_workflow, sanitize_prompt_template


def _parse_colors_text(text: str, source: str = '') -> Tuple[str, List[Tuple[str, str]]]:
    garment_name = 'garment'
    colors: List[Tuple[str, str]] = []
    in_colors = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('GARMENT'):
            garment_name = line.split(':', 1)[1].strip() if ':' in line else garment_name
            in_colors = False
            continue
        if line.startswith('COLORS'):
            in_colors = True
            continue
        if not in_colors:
            continue
        line = line.replace('：', ':')
        if ':' in line:
            name, hex_value = line.split(':', 1)
            hex_value = hex_value.strip().lstrip('#')
            if len(hex_value) == 6:
                colors.append((name.strip(), f'#{hex_value.lower()}'))
    if not colors:
        raise ValueError(f'No colors found in {source or "input"}')
    return garment_name, colors


def parse_colors_file_bytes(data: bytes) -> Tuple[str, List[Tuple[str, str]]]:
    text = data.decode('utf-8-sig')
    return _parse_colors_text(text)


def parse_colors_file(path: Path) -> Tuple[str, List[Tuple[str, str]]]:
    text = path.read_text(encoding='utf-8-sig')
    return _parse_colors_text(text, source=str(path))


def hex_to_rgb(hex_value: str) -> Tuple[int, int, int]:
    h = hex_value.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


class TaskRunner:
    def __init__(self, store: JobStore):
        self.store = store
        self.client = ComfyClient(COMFY_URL)
        self.workflow_path = DEFAULT_WORKFLOW
        self.colors_txt = DEFAULT_COLORS_TXT
        self.default_output_dir = OUTPUT_DIR
        self._lock = threading.Lock()

    def submit(
        self,
        garment_name: str,
        colors_text: str,
        image_paths: List[Path],
        prompt_template: Optional[str],
        guidance: float,
        steps: int,
        steps_8: int,
        enable_lora: bool,
        enable_8_step_lora: bool,
        target_width: int,
        target_height: int,
    ) -> str:
        first_image = image_paths[0]
        job = self.store.create(
            status='queued',
            progress=0,
            message='queued',
            garment_name=garment_name,
            input_name=first_image.name,
            output_dir=str(self.default_output_dir / job.job_id),
            created_at=time.time(),
            updated_at=time.time(),
        )
        thread = threading.Thread(
            target=self._run_job,
            args=(job.job_id, garment_name, colors_text, image_paths, prompt_template, guidance, steps, steps_8, enable_lora, enable_8_step_lora, target_width, target_height),
            daemon=True,
        )
        thread.start()
        return job.job_id

    def _run_job(
        self,
        job_id: str,
        garment_name: str,
        colors_text: str,
        image_paths: List[Path],
        prompt_template: Optional[str],
        guidance: float,
        steps: int,
        steps_8: int,
        enable_lora: bool,
        enable_8_step_lora: bool,
        target_width: int,
        target_height: int,
    ) -> None:
        try:
            self.store.update(job_id, status='running', message='parsing colors', progress=3, updated_at=time.time())
            garment_name_from_txt, colors = self._parse_colors_text(colors_text)
            if garment_name:
                garment_name_from_txt = garment_name
            prompt_template = sanitize_prompt_template(prompt_template)
            output_root = self.default_output_dir / job_id
            output_root.mkdir(parents=True, exist_ok=True)
            base_workflow = load_workflow(self.workflow_path)

            total_images = max(1, len(image_paths))
            total_colors = max(1, len(colors))
            total_jobs = total_images * total_colors
            done_jobs = 0
            generated_files: List[Path] = []

            for image_path in image_paths:
                self.store.update(job_id, message=f'uploading {image_path.name}', progress=max(8, int((done_jobs / total_jobs) * 100)), updated_at=time.time())
                comfy_image_name = self.client.upload_image(image_path)

                for color_name, hex_value in colors:
                    rgb = hex_to_rgb(hex_value)
                    prompt = build_prompt(garment_name_from_txt, hex_value, rgb, template=prompt_template)
                    workflow = self._prepare_workflow(
                        base_workflow=base_workflow,
                        image_filename=comfy_image_name,
                        prompt=prompt,
                        guidance=guidance,
                        steps=steps,
                        steps_8=steps_8,
                        enable_lora=enable_lora,
                        enable_8_step_lora=enable_8_step_lora,
                        target_width=target_width,
                        target_height=target_height,
                        garment_name=garment_name_from_txt,
                        job_id=job_id,
                    )
                    self.store.update(job_id, message=f'generating {image_path.name} / {color_name}', progress=int((done_jobs / total_jobs) * 100), updated_at=time.time())
                    prompt_id = self.client.queue_prompt(workflow)
                    history_entry = self.client.wait_for_completion(prompt_id, wait_seconds=2.0, timeout=1200.0)
                    output_images = self.client.extract_output_images(history_entry)
                    if output_images:
                        for image_idx, image_info in enumerate(output_images, start=1):
                            bytes_data = self.client.view_image(
                                image_info['filename'],
                                image_info.get('subfolder', ''),
                                image_info.get('type', 'output'),
                            )
                            safe_color = color_name.replace(' ', '_')
                            save_name = f'{image_path.stem}_{safe_color}_{hex_value}_{image_idx}.png'
                            save_path = output_root / save_name
                            save_path.write_bytes(bytes_data)
                            generated_files.append(save_path)
                    else:
                        save_paths = self._fallback_collect_outputs(output_root, image_path.stem, color_name, hex_value)
                        generated_files.extend(save_paths)
                        if not save_paths:
                            raise RuntimeError(f'No output images for {image_path.name} / {color_name}')

                    done_jobs += 1
                    self.store.update(job_id, progress=int((done_jobs / total_jobs) * 100), message=f'completed {image_path.name} / {color_name}', updated_at=time.time())

            if not generated_files:
                raise RuntimeError('No output images generated')
            self.store.update(job_id, status='completed', progress=100, message='completed', updated_at=time.time())
        except Exception as exc:
            self.store.update(job_id, status='failed', message='failed', error=str(exc), updated_at=time.time())

    def _prepare_workflow(
        self,
        base_workflow: Dict,
        image_filename: str,
        prompt: str,
        guidance: float,
        steps: int,
        steps_8: int,
        enable_lora: bool,
        enable_8_step_lora: bool,
        target_width: int,
        target_height: int,
        garment_name: str,
        job_id: str,
    ) -> Dict:
        workflow = copy.deepcopy(base_workflow)
        workflow['46']['inputs']['image'] = image_filename
        workflow['68:6']['inputs']['text'] = prompt
        workflow['68:26']['inputs']['guidance'] = guidance
        workflow['68:90']['inputs']['value'] = steps_8
        workflow['68:91']['inputs']['value'] = steps
        workflow['68:94']['inputs']['value'] = enable_8_step_lora
        workflow['68:92']['inputs']['switch'] = enable_lora
        workflow['68:93']['inputs']['switch'] = enable_8_step_lora
        workflow['45']['inputs']['megapixels'] = (target_width * target_height) / 1_000_000
        workflow['68:47']['inputs']['width'] = target_width
        workflow['68:47']['inputs']['height'] = target_height
        workflow['68:72']['inputs']['image'] = ['45', 0]
        workflow['68:48']['inputs']['width'] = ['68:72', 0]
        workflow['68:48']['inputs']['height'] = ['68:72', 1]
        workflow['9']['inputs']['filename_prefix'] = f'job_{job_id_safe(garment_name)}_{job_id[:8]}'
        return workflow

    def _parse_colors_text(self, colors_text: str) -> Tuple[str, List[Tuple[str, str]]]:
        tmp_dir = STORAGE_DIR / 'temp'
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / f'temp_colors_{threading.current_thread().ident}_{int(time.time() * 1000)}.txt'
        try:
            tmp.write_text(colors_text, encoding='utf-8')
            return parse_colors_file(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def _fallback_collect_outputs(self, output_root: Path, image_stem: str, color_name: str, hex_value: str) -> List[Path]:
        candidates = self.client.collect_output_paths(output_root)
        if not candidates:
            return []
        safe_color = color_name.replace(' ', '_').lower()
        hex_lower = hex_value.lower()
        matched = [p for p in candidates if image_stem.lower() in p.name.lower() or safe_color in p.name.lower() or hex_lower in p.name.lower()]
        return matched or candidates[:1]

    def zip_job_output(self, job_id: str) -> Path:
        job = self.store.get(job_id)
        if not job:
            raise FileNotFoundError(job_id)
        out_dir = self.default_output_dir / job_id
        if not out_dir.exists() and job.output_dir:
            candidate = Path(job.output_dir)
            if candidate.exists():
                out_dir = candidate
        zip_path = out_dir.with_suffix('.zip')
        with ZipFile(zip_path, 'w') as zf:
            if out_dir.exists():
                for p in out_dir.rglob('*'):
                    if p.is_file():
                        zf.write(p, p.relative_to(out_dir))
        return zip_path


def job_id_safe(name: str) -> str:
    return ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in name)[:40]
