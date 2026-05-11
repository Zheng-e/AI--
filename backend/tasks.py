from __future__ import annotations

import copy
import logging
import queue
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zipfile import ZipFile

from .api_client import ApiClient
from .api_keys import KeyPool, parse_api_keys_file
from .colors import ColorParseError, parse_colors_bytes, parse_colors_file, parse_colors_text
from .comfy_client import CancelledError, ComfyClient
from .config import (
    API_BASE_URL,
    API_KEYS_FILE,
    COMFY_URL,
    DEFAULT_API_ACTIVE_JOBS,
    DEFAULT_API_CONCURRENCY,
    DEFAULT_API_MODEL,
    DEFAULT_COLORS_TXT,
    DEFAULT_WORKFLOW,
    OUTPUT_DIR,
)
from .jobs import JobStore
from .workflow import build_prompt, load_workflow, sanitize_prompt_template

logger = logging.getLogger(__name__)

SAFETY_ERROR_KEYWORDS = ('sexual', 'safety', 'policy', 'moderation', 'content', '风控', '安全')


def _parse_colors_text(text: str, source: str = '颜色文本') -> Tuple[str, List[Tuple[str, str]]]:
    return parse_colors_text(text, source=source)


def parse_colors_file_bytes(data: bytes) -> Tuple[str, List[Tuple[str, str]]]:
    return parse_colors_bytes(data, source='颜色文件')


def hex_to_rgb(hex_value: str) -> Tuple[int, int, int]:
    h = hex_value.lstrip('#')
    return tuple(int(h[index:index + 2], 16) for index in (0, 2, 4))


def safe_filename(value: str, fallback: str = 'item') -> str:
    cleaned = re.sub(r'[^\w.\-#]+', '_', value.strip(), flags=re.UNICODE).strip('._')
    return cleaned[:140] or fallback


class TaskRunner:
    def __init__(self, store: JobStore):
        self.store = store
        self.client = ComfyClient(COMFY_URL)
        self.workflow_path = DEFAULT_WORKFLOW
        self.colors_txt = DEFAULT_COLORS_TXT
        self.default_output_dir = OUTPUT_DIR

        keys_map = parse_api_keys_file(API_KEYS_FILE)
        key_pools = {model: KeyPool(keys) for model, keys in keys_map.items()}
        self.key_pools = key_pools
        self.api_client = ApiClient(key_pools, base_url=API_BASE_URL)

        self._local_queue: queue.Queue = queue.Queue()
        self._api_job_executor = ThreadPoolExecutor(max_workers=DEFAULT_API_ACTIVE_JOBS, thread_name_prefix='api-job')
        self._api_executor = ThreadPoolExecutor(max_workers=DEFAULT_API_CONCURRENCY, thread_name_prefix='api-call')
        self._cancel_events: Dict[str, threading.Event] = {}
        self._cancel_lock = threading.Lock()
        self._comfy_lock = threading.Lock()

        self._local_worker = threading.Thread(target=self._local_worker_loop, daemon=True)
        self._local_worker.start()

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
        image_paths = image_paths or []
        if not image_paths:
            raise ValueError('请至少上传一张商品图片')

        garment_name_from_txt, parsed_colors = parse_colors_text(colors_text)
        garment = garment_name.strip() or garment_name_from_txt
        engine = 'api' if engine == 'api' else 'comfyui'
        model = api_model.strip() or (DEFAULT_API_MODEL if engine == 'api' else '')
        output_root = self._make_output_dir(product_id)
        combos = self._build_combos(image_paths, parsed_colors)

        job = self.store.create(
            product_id=product_id.strip(),
            status='queued',
            progress=0,
            message='等待调度',
            garment_name=garment,
            colors=[{'name': name, 'hex': hex_value} for name, hex_value in parsed_colors],
            input_name=image_paths[0].name,
            output_dir=str(output_root),
            image_paths=[str(path) for path in image_paths],
            colors_text=colors_text,
            prompt_template=sanitize_prompt_template(prompt_template) or '',
            guidance=guidance,
            steps=steps,
            steps_8=steps_8,
            target_width=target_width,
            target_height=target_height,
            engine=engine,
            api_model=model,
            combos=combos,
        )

        cancel_event = threading.Event()
        with self._cancel_lock:
            self._cancel_events[job.job_id] = cancel_event

        if engine == 'api':
            self._api_job_executor.submit(self._run_api_job, job.job_id, cancel_event)
        else:
            self._local_queue.put((job.job_id, cancel_event))
        return job.job_id

    def cancel(self, job_id: str) -> bool:
        job = self.store.get(job_id)
        if not job or job.status not in ('queued', 'running'):
            return False
        with self._cancel_lock:
            event = self._cancel_events.get(job_id)
        if event:
            event.set()
        self.store.update(job_id, cancelled=True, status='cancelling', message='正在取消')
        return True

    def resume(self, job_id: str) -> bool:
        return self.retry(job_id)

    def retry(self, job_id: str) -> bool:
        job = self.store.get(job_id)
        if not job or job.status in ('queued', 'running', 'cancelling'):
            return False

        if not self._verify_upload_files(job_id):
            return False

        for combo in job.combos:
            if combo.get('status') != 'completed':
                combo.update({
                    'status': 'queued',
                    'error': None,
                    'started_at': None,
                    'finished_at': None,
                    'output_files': [],
                    'actual_engine': None,
                    'fallback_reason': None,
                })
        self.store.update(job_id, status='queued', message='已重新加入队列', cancelled=False, error=None, combos=job.combos)

        cancel_event = threading.Event()
        with self._cancel_lock:
            self._cancel_events[job_id] = cancel_event
        if job.engine == 'api':
            self._api_job_executor.submit(self._run_api_job, job_id, cancel_event)
        else:
            self._local_queue.put((job_id, cancel_event))
        return True

    def key_status(self) -> Dict[str, int]:
        return {model: pool.available_count() for model, pool in self.key_pools.items()}

    def _local_worker_loop(self) -> None:
        while True:
            job_id, cancel_event = self._local_queue.get()
            try:
                if cancel_event.is_set():
                    self.store.update(job_id, status='cancelled', message='已取消')
                    continue
                self._run_local_job(job_id, cancel_event)
            except Exception:
                logger.exception('Local worker error')
            finally:
                self._cleanup_cancel_event(job_id)

    def _run_local_job(self, job_id: str, cancel_event: threading.Event) -> None:
        job = self.store.get(job_id)
        if not job:
            return
        self.store.update(job_id, status='running', message='正在本地改色')
        image_paths = [Path(path) for path in job.image_paths]
        output_root = Path(job.output_dir or self.default_output_dir / job_id)
        output_root.mkdir(parents=True, exist_ok=True)

        for combo in list(job.combos):
            latest = self.store.get(job_id)
            if not latest:
                return
            if cancel_event.is_set() or latest.cancelled:
                self._mark_unfinished_cancelled(job_id)
                self._finish_job(job_id, cancel_event)
                return
            current = self._get_combo(latest, combo['image_index'], combo['color_index'])
            if not current or current.get('status') == 'completed':
                continue
            try:
                self._run_comfyui_combo(
                    job_id,
                    current,
                    image_paths[current['image_index']],
                    latest.garment_name or 'garment',
                    latest.prompt_template or None,
                    output_root,
                    latest.guidance,
                    latest.steps,
                    latest.steps_8,
                    False,
                    False,
                    latest.target_width,
                    latest.target_height,
                    cancel_event,
                    actual_engine='comfyui',
                )
                self.store.update(job_id, message=f'完成 {self._completed_message(job_id)}')
            except CancelledError:
                self._mark_unfinished_cancelled(job_id)
                self._finish_job(job_id, cancel_event)
                return
            except Exception as exc:
                self.store.update_combo(
                    job_id,
                    current['image_index'],
                    current['color_index'],
                    status='failed',
                    error=str(exc),
                    finished_at=time.time(),
                    actual_engine='comfyui',
                )
        self._finish_job(job_id, cancel_event)

    def _run_api_job(self, job_id: str, cancel_event: threading.Event) -> None:
        job = self.store.get(job_id)
        if not job:
            return
        self.store.update(job_id, status='running', message='正在并发调用 API')
        futures: Dict[Future, Dict] = {}

        try:
            pending = [combo for combo in job.combos if combo.get('status') == 'queued']
            image_paths = [Path(path) for path in job.image_paths]
            output_root = Path(job.output_dir or self.default_output_dir / job_id)
            output_root.mkdir(parents=True, exist_ok=True)

            for combo in pending:
                if cancel_event.is_set():
                    break
                future = self._api_executor.submit(
                    self._run_api_combo,
                    job_id,
                    combo,
                    image_paths[combo['image_index']],
                    job.garment_name or 'garment',
                    job.prompt_template or None,
                    job.api_model or DEFAULT_API_MODEL,
                    output_root,
                    cancel_event,
                )
                futures[future] = combo

            for future in as_completed(futures):
                combo = futures[future]
                if cancel_event.is_set() and not future.done():
                    future.cancel()
                    continue
                try:
                    future.result()
                except CancelledError:
                    self.store.update_combo(
                        job_id,
                        combo['image_index'],
                        combo['color_index'],
                        status='cancelled',
                        finished_at=time.time(),
                    )
                except Exception as exc:
                    self.store.update_combo(
                        job_id,
                        combo['image_index'],
                        combo['color_index'],
                        status='failed',
                        error=str(exc),
                        finished_at=time.time(),
                    )
                self.store.update(job_id, message=f'完成 {self._completed_message(job_id)}')

            if cancel_event.is_set():
                self._mark_unfinished_cancelled(job_id)
            self._finish_job(job_id, cancel_event)
        finally:
            self._cleanup_cancel_event(job_id)

    def _run_api_combo(
        self,
        job_id: str,
        combo: Dict,
        image_path: Path,
        garment_name: str,
        prompt_template: Optional[str],
        api_model: str,
        output_root: Path,
        cancel_event: threading.Event,
    ) -> None:
        if cancel_event.is_set():
            raise CancelledError()

        image_index = combo['image_index']
        color_index = combo['color_index']
        self.store.update_combo(
            job_id,
            image_index,
            color_index,
            status='running',
            started_at=time.time(),
            error=None,
            actual_engine='api',
        )

        prompt = build_prompt(garment_name, combo['hex'], hex_to_rgb(combo['hex']), template=prompt_template)
        try:
            result_images = self.api_client.generate(image_path.read_bytes(), prompt, api_model, cancel_event=cancel_event)
        except Exception as exc:
            if self._is_safety_error(exc):
                self.store.update_combo(
                    job_id,
                    image_index,
                    color_index,
                    status='running',
                    error=None,
                    actual_engine='comfyui_fallback',
                    fallback_reason=str(exc),
                )
                job = self.store.get(job_id)
                if not job:
                    return
                self._run_comfyui_combo(
                    job_id,
                    combo,
                    image_path,
                    garment_name,
                    prompt_template,
                    output_root,
                    job.guidance,
                    job.steps,
                    job.steps_8,
                    False,
                    False,
                    job.target_width,
                    job.target_height,
                    cancel_event,
                    actual_engine='comfyui_fallback',
                    fallback_reason=str(exc),
                )
                return
            raise

        output_files = []
        for output_index, result_bytes in enumerate(result_images, start=1):
            save_name = (
                f"{safe_filename(image_path.stem, 'image')}_"
                f"{safe_filename(combo['color_name'], 'color')}_"
                f"{combo['hex']}_{output_index}.png"
            )
            save_path = output_root / save_name
            save_path.write_bytes(result_bytes)
            output_files.append(save_name)

        self.store.update_combo(
            job_id,
            image_index,
            color_index,
            status='completed',
            output_files=output_files,
            finished_at=time.time(),
            actual_engine='api',
        )

    def _run_comfyui_combo(
        self,
        job_id: str,
        combo: Dict,
        image_path: Path,
        garment_name: str,
        prompt_template: Optional[str],
        output_root: Path,
        guidance: float,
        steps: int,
        steps_8: int,
        enable_lora: bool,
        enable_8_step_lora: bool,
        target_width: int,
        target_height: int,
        cancel_event: threading.Event,
        *,
        actual_engine: str,
        fallback_reason: Optional[str] = None,
    ) -> List[str]:
        if cancel_event.is_set():
            raise CancelledError()

        image_index = combo['image_index']
        color_index = combo['color_index']
        self.store.update_combo(
            job_id,
            image_index,
            color_index,
            status='running',
            started_at=time.time(),
            error=None,
            actual_engine=actual_engine,
            fallback_reason=fallback_reason,
        )

        with self._comfy_lock:
            if cancel_event.is_set():
                raise CancelledError()
            base_workflow = load_workflow(self.workflow_path)
            comfy_image_name = self.client.upload_image(image_path)
            prompt = build_prompt(garment_name, combo['hex'], hex_to_rgb(combo['hex']), template=prompt_template)
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
            prompt_id = self.client.queue_prompt(workflow)
            try:
                history_entry = self.client.wait_for_completion(prompt_id, wait_seconds=2.0, timeout=1200.0, cancel_event=cancel_event)
            except CancelledError:
                self.client.interrupt()
                raise

            output_files: List[str] = []
            output_images = self.client.extract_output_images(history_entry)
            if output_images:
                for output_index, image_info in enumerate(output_images, start=1):
                    bytes_data = self.client.view_image(
                        image_info['filename'],
                        image_info.get('subfolder', ''),
                        image_info.get('type', 'output'),
                    )
                    save_name = (
                        f"{safe_filename(image_path.stem, 'image')}_"
                        f"{safe_filename(combo['color_name'], 'color')}_"
                        f"{combo['hex']}_{output_index}.png"
                    )
                    save_path = output_root / save_name
                    save_path.write_bytes(bytes_data)
                    output_files.append(save_name)
            else:
                for path in self._fallback_collect_outputs(output_root, image_path.stem, combo['color_name'], combo['hex']):
                    output_files.append(path.name)

            if not output_files:
                raise RuntimeError(f"No output images for {image_path.name} / {combo['color_name']}")

        self.store.update_combo(
            job_id,
            image_index,
            color_index,
            status='completed',
            output_files=output_files,
            finished_at=time.time(),
            actual_engine=actual_engine,
            fallback_reason=fallback_reason,
        )
        return output_files

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

    def _make_output_dir(self, product_id: str) -> Path:
        base_name = safe_filename(product_id, '') or f'job_{int(time.time() * 1000)}'
        candidate = self.default_output_dir / base_name
        if candidate.exists():
            candidate = self.default_output_dir / f'{base_name}_{int(time.time() * 1000)}'
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    def _build_combos(self, image_paths: List[Path], colors: List[Tuple[str, str]]) -> List[Dict]:
        combos: List[Dict] = []
        for image_index, image_path in enumerate(image_paths):
            for color_index, (color_name, hex_value) in enumerate(colors):
                combos.append({
                    'image_index': image_index,
                    'color_index': color_index,
                    'image_name': image_path.name,
                    'color_name': color_name,
                    'hex': hex_value,
                    'status': 'queued',
                    'output_files': [],
                    'error': None,
                    'actual_engine': None,
                    'fallback_reason': None,
                    'started_at': None,
                    'finished_at': None,
                })
        return combos

    @staticmethod
    def _get_combo(job, image_index: int, color_index: int) -> Optional[Dict]:
        for combo in job.combos:
            if combo.get('image_index') == image_index and combo.get('color_index') == color_index:
                return combo
        return None

    def _finish_job(self, job_id: str, cancel_event: threading.Event) -> None:
        job = self.store.get(job_id)
        if not job:
            return
        if cancel_event.is_set() or job.cancelled_count:
            self.store.update(job_id, status='cancelled', message='已取消')
            return
        if job.failed_count and job.completed_count:
            self.store.update(job_id, status='completed_with_errors', message='部分完成，存在失败组合')
            return
        if job.failed_count:
            self.store.update(job_id, status='failed', message='任务失败', error='所有组合均失败或存在未完成失败')
            return
        self.store.update(job_id, status='completed', progress=100, message='全部完成')

    def _mark_unfinished_cancelled(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if not job:
            return
        for combo in job.combos:
            if combo.get('status') not in ('completed', 'failed', 'cancelled'):
                self.store.update_combo(
                    job_id,
                    combo['image_index'],
                    combo['color_index'],
                    status='cancelled',
                    finished_at=time.time(),
                )

    def _verify_upload_files(self, job_id: str) -> bool:
        job = self.store.get(job_id)
        if not job:
            return False
        missing = [path for path in job.image_paths if not Path(path).exists()]
        if missing:
            self.store.update(job_id, status='failed', message=f'上传图片不存在: {missing[0]}')
            return False
        return True

    def _completed_message(self, job_id: str) -> str:
        job = self.store.get(job_id)
        if not job:
            return '0/0'
        return f'{job.completed_count}/{job.total_combos}，失败 {job.failed_count}'

    @staticmethod
    def _is_safety_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(keyword in text for keyword in SAFETY_ERROR_KEYWORDS)

    def _cleanup_cancel_event(self, job_id: str) -> None:
        with self._cancel_lock:
            self._cancel_events.pop(job_id, None)

    def _fallback_collect_outputs(self, output_root: Path, image_stem: str, color_name: str, hex_value: str) -> List[Path]:
        candidates = self.client.collect_output_paths(output_root)
        if not candidates:
            return []
        safe_color = color_name.replace(' ', '_').lower()
        hex_lower = hex_value.lower()
        matched = [
            path for path in candidates
            if image_stem.lower() in path.name.lower() or safe_color in path.name.lower() or hex_lower in path.name.lower()
        ]
        return matched or candidates[:1]

    def zip_job_output(self, job_id: str) -> Path:
        job = self.store.get(job_id)
        if not job:
            raise FileNotFoundError(job_id)
        out_dir = Path(job.output_dir or self.default_output_dir / job_id)
        zip_path = out_dir.with_suffix('.zip')
        with ZipFile(zip_path, 'w') as archive:
            if out_dir.exists():
                for path in out_dir.rglob('*'):
                    if path.is_file():
                        archive.write(path, path.relative_to(out_dir))
        return zip_path


def job_id_safe(name: str) -> str:
    return ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in name)[:40]
