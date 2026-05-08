from __future__ import annotations

import copy
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zipfile import ZipFile

from .config import (
    API_BASE_URL,
    API_KEYS_FILE,
    COMFY_URL,
    DEFAULT_API_CONCURRENCY,
    DEFAULT_API_MODEL,
    DEFAULT_COLORS_TXT,
    DEFAULT_WORKFLOW,
    OUTPUT_DIR,
    STORAGE_DIR,
)
from .api_client import ApiClient
from .api_keys import MODEL_PRIORITY, KeyPool, parse_api_keys_file
from .comfy_client import CancelledError, ComfyClient
from .jobs import JobStore
from .workflow import build_prompt, load_workflow, sanitize_prompt_template

logger = logging.getLogger(__name__)


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
        self._task_queue: queue.Queue = queue.Queue()
        self._cancel_events: Dict[str, threading.Event] = {}
        self._cancel_lock = threading.Lock()
        # API client
        keys_map = parse_api_keys_file(API_KEYS_FILE)
        key_pools = {model: KeyPool(keys) for model, keys in keys_map.items()}
        self.api_client = ApiClient(key_pools, base_url=API_BASE_URL)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def submit(
        self,
        product_id: str = '',
        garment_name: str = '',
        colors_text: str = '',
        image_paths: Optional[List[Path]] = None,
        prompt_template: Optional[str] = None,
        guidance: float = 3.5,
        steps: int = 20,
        steps_8: int = 8,
        enable_lora: bool = False,
        enable_8_step_lora: bool = False,
        target_width: int = 1601,
        target_height: int = 2086,
        engine: str = 'comfyui',
        api_model: str = '',
    ) -> str:
        first_image = image_paths[0]
        output_dir_name = product_id if product_id else 'pending'
        job = self.store.create(
            product_id=product_id,
            status='queued',
            progress=0,
            message='queued',
            garment_name=garment_name,
            input_name=first_image.name,
            output_dir=str(self.default_output_dir / output_dir_name),
            created_at=time.time(),
            updated_at=time.time(),
            image_paths=[str(p) for p in image_paths],
            colors_text=colors_text,
            prompt_template=prompt_template or '',
            guidance=guidance,
            steps=steps,
            steps_8=steps_8,
            target_width=target_width,
            target_height=target_height,
            engine=engine,
            api_model=api_model,
        )
        if not product_id:
            self.store.update(job.job_id, output_dir=str(self.default_output_dir / job.job_id))
        cancel_event = threading.Event()
        with self._cancel_lock:
            self._cancel_events[job.job_id] = cancel_event
        args = (
            job.job_id, product_id, garment_name, colors_text, image_paths,
            prompt_template, guidance, steps, steps_8,
            enable_lora, enable_8_step_lora, target_width, target_height,
            engine, api_model,
        )
        self._task_queue.put((cancel_event, args))
        return job.job_id

    def cancel(self, job_id: str) -> bool:
        job = self.store.get(job_id)
        if not job:
            return False
        if job.status not in ('queued', 'running'):
            return False
        self.store.update(
            job_id,
            cancelled=True,
            status='cancelling',
            message='cancelling...',
            updated_at=time.time(),
        )
        with self._cancel_lock:
            event = self._cancel_events.get(job_id)
        if event:
            event.set()
        return True

    def resume(self, job_id: str) -> bool:
        job = self.store.get(job_id)
        if not job:
            return False
        if job.status not in ('paused', 'failed', 'cancelled'):
            return False
        # verify upload files still exist
        missing = [p for p in job.image_paths if not Path(p).exists()]
        if missing:
            self.store.update(job_id, status='failed', message=f'Upload files missing: {missing[0]}', updated_at=time.time())
            return False
        self.store.update(
            job_id,
            status='queued',
            message='queued for resume',
            cancelled=False,
            error=None,
            updated_at=time.time(),
        )
        cancel_event = threading.Event()
        with self._cancel_lock:
            self._cancel_events[job_id] = cancel_event
        image_paths = [Path(p) for p in job.image_paths]
        args = (
            job_id, job.product_id, job.garment_name, job.colors_text, image_paths,
            job.prompt_template or None, job.guidance, job.steps, job.steps_8,
            False, False, job.target_width, job.target_height,
            job.engine or 'comfyui', job.api_model or '',
        )
        self._task_queue.put((cancel_event, args))
        return True

    def _worker_loop(self) -> None:
        while True:
            try:
                cancel_event, args = self._task_queue.get()
                job_id = args[0]
                if cancel_event.is_set():
                    self.store.update(job_id, status='cancelled', message='cancelled', updated_at=time.time())
                    self._cleanup_cancel_event(job_id)
                    continue
                self._run_job(cancel_event, *args)
                self._cleanup_cancel_event(job_id)
            except Exception:
                logger.exception('Worker loop error')

    def _cleanup_cancel_event(self, job_id: str) -> None:
        with self._cancel_lock:
            self._cancel_events.pop(job_id, None)

    def _run_job(
        self,
        cancel_event: threading.Event,
        job_id: str,
        product_id: str,
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
        engine: str = 'comfyui',
        api_model: str = '',
    ) -> None:
        try:
            self.store.update(job_id, status='running', message='parsing colors', progress=3, updated_at=time.time())
            garment_name_from_txt, colors = self._parse_colors_text(colors_text)
            if garment_name:
                garment_name_from_txt = garment_name
            prompt_template = sanitize_prompt_template(prompt_template)
            output_dir_name = product_id if product_id else job_id
            output_root = self.default_output_dir / output_dir_name
            output_root.mkdir(parents=True, exist_ok=True)

            if engine == 'api':
                self._run_job_api(
                    cancel_event, job_id, garment_name_from_txt, colors,
                    image_paths, prompt_template, output_root,
                    api_model or DEFAULT_API_MODEL,
                )
            else:
                self._run_job_comfyui(
                    cancel_event, job_id, garment_name_from_txt, colors,
                    image_paths, prompt_template, output_root,
                    guidance, steps, steps_8,
                    enable_lora, enable_8_step_lora,
                    target_width, target_height,
                )

            generated_files = list(output_root.iterdir()) if output_root.exists() else []
            if not generated_files:
                raise RuntimeError('No output images generated')
            self.store.update(job_id, status='completed', progress=100, message='completed', updated_at=time.time())
        except CancelledError:
            self.store.update(job_id, status='cancelled', message='cancelled', updated_at=time.time())
        except Exception as exc:
            self.store.update(job_id, status='failed', message='failed', error=str(exc), updated_at=time.time())

    def _run_job_comfyui(
        self,
        cancel_event: threading.Event,
        job_id: str,
        garment_name: str,
        colors: List[Tuple[str, str]],
        image_paths: List[Path],
        prompt_template: Optional[str],
        output_root: Path,
        guidance: float,
        steps: int,
        steps_8: int,
        enable_lora: bool,
        enable_8_step_lora: bool,
        target_width: int,
        target_height: int,
    ) -> None:
        base_workflow = load_workflow(self.workflow_path)
        total_images = max(1, len(image_paths))
        total_colors = max(1, len(colors))
        total_jobs = total_images * total_colors
        done_jobs = 0
        generated_files: List[Path] = []

        job = self.store.get(job_id)
        completed_set = set(tuple(c) for c in (job.completed_combos if job else []))

        for image_idx, image_path in enumerate(image_paths):
            if cancel_event.is_set():
                raise CancelledError()

            all_done_for_image = all((image_idx, ci) in completed_set for ci in range(len(colors)))
            if all_done_for_image:
                done_jobs += len(colors)
                continue

            self.store.update(job_id, message=f'uploading {image_path.name}', progress=max(8, int((done_jobs / total_jobs) * 100)), updated_at=time.time())
            comfy_image_name = self.client.upload_image(image_path)

            for color_idx, (color_name, hex_value) in enumerate(colors):
                if cancel_event.is_set():
                    raise CancelledError()

                if (image_idx, color_idx) in completed_set:
                    done_jobs += 1
                    continue

                rgb = hex_to_rgb(hex_value)
                prompt = build_prompt(garment_name, hex_value, rgb, template=prompt_template)
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
                    garment_name=garment_name,
                    job_id=job_id,
                )
                self.store.update(job_id, message=f'generating {image_path.name} / {color_name}', progress=int((done_jobs / total_jobs) * 100), updated_at=time.time())
                prompt_id = self.client.queue_prompt(workflow)
                try:
                    history_entry = self.client.wait_for_completion(prompt_id, wait_seconds=2.0, timeout=1200.0, cancel_event=cancel_event)
                except CancelledError:
                    self.client.interrupt()
                    raise

                output_images = self.client.extract_output_images(history_entry)
                if output_images:
                    for out_idx, image_info in enumerate(output_images, start=1):
                        bytes_data = self.client.view_image(
                            image_info['filename'],
                            image_info.get('subfolder', ''),
                            image_info.get('type', 'output'),
                        )
                        safe_color = color_name.replace(' ', '_')
                        save_name = f'{image_path.stem}_{safe_color}_{hex_value}_{out_idx}.png'
                        save_path = output_root / save_name
                        save_path.write_bytes(bytes_data)
                        generated_files.append(save_path)
                else:
                    save_paths = self._fallback_collect_outputs(output_root, image_path.stem, color_name, hex_value)
                    generated_files.extend(save_paths)
                    if not save_paths:
                        raise RuntimeError(f'No output images for {image_path.name} / {color_name}')

                done_jobs += 1
                completed_set.add((image_idx, color_idx))
                self.store.update(job_id,
                                  progress=int((done_jobs / total_jobs) * 100),
                                  message=f'completed {image_path.name} / {color_name}',
                                  completed_combos=list(completed_set),
                                  updated_at=time.time())

    def _run_job_api(
        self,
        cancel_event: threading.Event,
        job_id: str,
        garment_name: str,
        colors: List[Tuple[str, str]],
        image_paths: List[Path],
        prompt_template: Optional[str],
        output_root: Path,
        api_model: str,
    ) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        total_images = max(1, len(image_paths))
        total_colors = max(1, len(colors))
        total_jobs = total_images * total_colors
        done_jobs = 0

        job = self.store.get(job_id)
        completed_set = set(tuple(c) for c in (job.completed_combos if job else []))

        # Build list of pending combos
        pending = []
        for image_idx, image_path in enumerate(image_paths):
            for color_idx, (color_name, hex_value) in enumerate(colors):
                if (image_idx, color_idx) not in completed_set:
                    pending.append((image_idx, image_path, color_idx, color_name, hex_value))

        def _process_combo(image_idx, image_path, color_idx, color_name, hex_value):
            if cancel_event.is_set():
                raise CancelledError()
            rgb = hex_to_rgb(hex_value)
            prompt = build_prompt(garment_name, hex_value, rgb, template=prompt_template)
            image_bytes = image_path.read_bytes()
            result_images = self.api_client.generate(
                image_bytes, prompt, api_model, cancel_event=cancel_event,
            )
            saved = []
            for out_idx, img_bytes in enumerate(result_images, start=1):
                safe_color = color_name.replace(' ', '_')
                save_name = f'{image_path.stem}_{safe_color}_{hex_value}_{out_idx}.png'
                save_path = output_root / save_name
                save_path.write_bytes(img_bytes)
                saved.append(save_path)
            return image_idx, color_idx, saved

        with ThreadPoolExecutor(max_workers=DEFAULT_API_CONCURRENCY) as pool:
            futures = {
                pool.submit(_process_combo, *combo): combo
                for combo in pending
            }
            for future in as_completed(futures):
                image_idx, color_idx, saved = future.result()
                done_jobs += 1
                completed_set.add((image_idx, color_idx))
                combo = futures[future]
                self.store.update(job_id,
                                  progress=int((done_jobs / total_jobs) * 100),
                                  message=f'completed {combo[1].name} / {combo[3]}',
                                  completed_combos=list(completed_set),
                                  updated_at=time.time())

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
