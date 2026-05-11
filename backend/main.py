from __future__ import annotations

import re
import shutil
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .colors import ColorParseError, decode_text_bytes, parse_colors_bytes, parse_colors_text
from .config import (
    DEFAULT_API_ACTIVE_JOBS,
    DEFAULT_API_CONCURRENCY,
    DEFAULT_API_MODEL,
    DEFAULT_GUIDANCE,
    DEFAULT_STEPS,
    DEFAULT_STEPS_8,
    DEFAULT_TARGET_HEIGHT,
    DEFAULT_TARGET_WIDTH,
    SERVER_ID,
    SERVER_NAME,
    STORAGE_DIR,
)
from .jobs import JobStore
from .tasks import TaskRunner
from .workflow import DEFAULT_PROMPT_TEMPLATES, sanitize_prompt_template

app = FastAPI(title='Flux2 Recolor Studio', version='0.4.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)

STORE = JobStore()
RUNNER = TaskRunner(STORE)


@app.on_event('startup')
def on_startup():
    STORE.restore_from_disk()


STATIC_DIR = Path(__file__).resolve().parent.parent / 'frontend'
if STATIC_DIR.exists():
    app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')


@app.get('/', response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / 'index.html').read_text(encoding='utf-8')


@app.get('/api-recolor', response_class=HTMLResponse)
def api_recolor() -> str:
    return (STATIC_DIR / 'api.html').read_text(encoding='utf-8')


@app.get('/dashboard', response_class=HTMLResponse)
def dashboard() -> str:
    return (STATIC_DIR / 'dashboard.html').read_text(encoding='utf-8')


@app.get('/api/defaults')
def defaults() -> dict:
    return {
        'workflow': 'image_flux2_working.json',
        'guidance': DEFAULT_GUIDANCE,
        'steps': DEFAULT_STEPS,
        'steps_8': DEFAULT_STEPS_8,
        'target_width': DEFAULT_TARGET_WIDTH,
        'target_height': DEFAULT_TARGET_HEIGHT,
        'enable_lora': False,
        'enable_8_step_lora': False,
        'default_prompt_templates': DEFAULT_PROMPT_TEMPLATES,
        'default_api_model': DEFAULT_API_MODEL,
        'max_active_jobs': DEFAULT_API_ACTIVE_JOBS,
        'max_api_concurrency': DEFAULT_API_CONCURRENCY,
    }


@app.post('/api/parse-colors')
def parse_colors(colors_txt: UploadFile = File(...)) -> dict:
    try:
        data = colors_txt.file.read()
        garment_name, colors = parse_colors_bytes(data, source=colors_txt.filename or '颜色文件')
    except ColorParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        'garment_name': garment_name,
        'colors': [{'name': name, 'hex': hex_value} for name, hex_value in colors],
    }


@app.post('/api/jobs')
def create_job(
    garment_name: str = Form(''),
    product_id: str = Form(''),
    colors_text: str = Form(''),
    manual_colors_text: str = Form(''),
    colors_txt: UploadFile | None = File(None),
    images: list[UploadFile] | None = File(None),
    image: UploadFile | None = File(None),
    prompt_template: str = Form(''),
    guidance: float = Form(DEFAULT_GUIDANCE),
    steps: int = Form(DEFAULT_STEPS),
    steps_8: int = Form(DEFAULT_STEPS_8),
    enable_lora: bool = Form(False),
    enable_8_step_lora: bool = Form(False),
    target_width: int = Form(DEFAULT_TARGET_WIDTH),
    target_height: int = Form(DEFAULT_TARGET_HEIGHT),
    engine: str = Form('comfyui'),
    api_model: str = Form(''),
) -> dict:
    incoming_images = list(images or [])
    if image is not None and image.filename not in {img.filename for img in incoming_images}:
        incoming_images.insert(0, image)
    if not incoming_images:
        raise HTTPException(status_code=400, detail='请至少上传一张商品图片')

    try:
        final_colors_text = _build_colors_text(colors_txt, colors_text, manual_colors_text)
        parse_colors_text(final_colors_text)
    except ColorParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    upload_root = STORAGE_DIR / 'uploads'
    upload_root.mkdir(parents=True, exist_ok=True)
    safe_pid = safe_name(product_id, '') or f'job_{int(time.time() * 1000)}'
    job_image_dir = upload_root / safe_pid / str(int(time.time() * 1000))
    job_image_dir.mkdir(parents=True, exist_ok=True)

    saved_images = []
    for index, img in enumerate(incoming_images):
        original_name = Path(img.filename).name if img.filename else f'image_{index + 1}.png'
        image_path = job_image_dir / safe_name(original_name, f'image_{index + 1}.png')
        image_path.write_bytes(img.file.read())
        saved_images.append(image_path)

    try:
        job_id = RUNNER.submit(
            product_id=product_id,
            garment_name=garment_name,
            colors_text=final_colors_text,
            image_paths=saved_images,
            prompt_template=sanitize_prompt_template(prompt_template),
            guidance=guidance,
            steps=steps,
            steps_8=steps_8,
            enable_lora=enable_lora,
            enable_8_step_lora=enable_8_step_lora,
            target_width=target_width,
            target_height=target_height,
            engine=engine,
            api_model=api_model,
        )
    except (ColorParseError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'job_id': job_id}


@app.get('/api/jobs')
def list_jobs(engine: str = Query('', description='Optional engine filter')) -> dict:
    jobs = [asdict(job) for job in STORE.list()]
    if engine:
        jobs = [job for job in jobs if (job.get('engine') or 'comfyui') == engine]
    return {'jobs': jobs}


@app.get('/api/jobs/{job_id}')
def get_job(job_id: str) -> dict:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='任务不存在')
    return asdict(job)


@app.post('/api/jobs/{job_id}/cancel')
def cancel_job(job_id: str) -> dict:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='任务不存在')
    ok = RUNNER.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail=f'任务当前状态为 {job.status}，无法取消')
    return {'job_id': job_id, 'status': 'cancelling'}


@app.post('/api/jobs/{job_id}/resume')
def resume_job(job_id: str) -> dict:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='任务不存在')
    ok = RUNNER.resume(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail=f'任务当前状态为 {job.status}，无法恢复')
    return {'job_id': job_id, 'status': 'queued'}


@app.post('/api/jobs/{job_id}/retry')
def retry_job(job_id: str) -> dict:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='任务不存在')
    ok = RUNNER.retry(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail=f'任务当前状态为 {job.status}，无法重试')
    return {'job_id': job_id, 'status': 'queued'}


@app.delete('/api/jobs/{job_id}')
def delete_job(job_id: str) -> dict:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='任务不存在')
    if job.status in ('running', 'queued', 'cancelling'):
        raise HTTPException(status_code=409, detail='运行中或排队中的任务请先取消')
    if job.output_dir:
        shutil.rmtree(job.output_dir, ignore_errors=True)
    STORE.delete(job_id)
    return {'job_id': job_id, 'deleted': True}


@app.post('/api/jobs/batch-delete')
def batch_delete_jobs(body: dict) -> dict:
    job_ids = body.get('job_ids', [])
    if not job_ids:
        raise HTTPException(status_code=400, detail='没有提供任务 ID')
    deleted = []
    skipped = []
    for job_id in job_ids:
        job = STORE.get(job_id)
        if not job:
            continue
        if job.status in ('running', 'queued', 'cancelling'):
            skipped.append(job_id)
            continue
        if job.output_dir:
            shutil.rmtree(job.output_dir, ignore_errors=True)
        STORE.delete(job_id)
        deleted.append(job_id)
    return {'deleted': deleted, 'skipped': skipped}


@app.get('/api/jobs/{job_id}/download')
def download_job(job_id: str):
    zip_path = RUNNER.zip_job_output(job_id)
    return FileResponse(path=str(zip_path), filename=zip_path.name, media_type='application/zip')


@app.get('/api/jobs/{job_id}/files/{filename}')
def get_output_file(job_id: str, filename: str):
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='任务不存在')
    if not job.output_dir:
        raise HTTPException(status_code=404, detail='任务没有输出目录')
    output_dir = Path(job.output_dir).resolve()
    target = (output_dir / Path(filename).name).resolve()
    if output_dir not in target.parents and target != output_dir:
        raise HTTPException(status_code=403, detail='非法文件路径')
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail='文件不存在')
    return FileResponse(str(target))


@app.get('/api/models')
def list_models() -> dict:
    return {'models': [
        {'id': 'gpt-image-2-client', 'label': 'GPT Image 2 Client (最便宜)', 'priority': 1},
        {'id': 'gpt-image-2', 'label': 'GPT Image 2 (官方)', 'priority': 2},
        {'id': 'gemini-3.1-flash-image-preview', 'label': 'Gemini 3.1 Flash', 'priority': 3},
    ]}


@app.get('/api/stats')
def stats() -> dict:
    jobs = STORE.list()
    by_status = dict(Counter(job.status for job in jobs))
    by_engine = dict(Counter(job.engine or 'comfyui' for job in jobs))
    by_model = dict(Counter(job.api_model for job in jobs if job.engine == 'api' and job.api_model))
    products = len(set(job.product_id for job in jobs if job.product_id))
    total_combos = sum(job.total_combos for job in jobs)
    completed_combos = sum(job.completed_count for job in jobs)
    failed_combos = sum(job.failed_count for job in jobs)
    durations = [
        job.updated_at - job.created_at
        for job in jobs
        if job.status == 'completed' and job.created_at > 0 and job.updated_at > job.created_at
    ]
    avg_duration = sum(durations) / len(durations) if durations else 0
    now = datetime.now(timezone.utc)
    daily = {(now - timedelta(days=index)).strftime('%Y-%m-%d'): 0 for index in range(7)}
    for job in jobs:
        if job.created_at > 0:
            day = datetime.fromtimestamp(job.created_at, tz=timezone.utc).strftime('%Y-%m-%d')
            if day in daily:
                daily[day] += 1
    return {
        'total_jobs': len(jobs),
        'by_status': by_status,
        'by_engine': by_engine,
        'by_model': by_model,
        'products': products,
        'total_combos': total_combos,
        'completed_combos': completed_combos,
        'failed_combos': failed_combos,
        'completion_rate': round(completed_combos / total_combos, 4) if total_combos else 0,
        'avg_duration_seconds': round(avg_duration, 1),
        'daily_submissions': daily,
    }


@app.get('/api/health')
def health() -> dict:
    jobs = STORE.list()
    return {
        'ok': True,
        'server_id': SERVER_ID,
        'server_name': SERVER_NAME,
        'running_jobs': sum(1 for job in jobs if job.status == 'running'),
        'queued_jobs': sum(1 for job in jobs if job.status == 'queued'),
        'total_jobs': len(jobs),
        'max_active_jobs': DEFAULT_API_ACTIVE_JOBS,
        'max_api_concurrency': DEFAULT_API_CONCURRENCY,
        'available_keys': RUNNER.key_status(),
    }


@app.get('/api/server-info')
def server_info() -> dict:
    jobs = STORE.list()
    return {
        'server_id': SERVER_ID,
        'server_name': SERVER_NAME,
        'running_jobs': sum(1 for job in jobs if job.status == 'running'),
        'queued_jobs': sum(1 for job in jobs if job.status == 'queued'),
        'total_jobs': len(jobs),
    }


def _build_colors_text(colors_txt: UploadFile | None, colors_text: str, manual_colors_text: str) -> str:
    if colors_txt is not None:
        source = colors_txt.filename or '颜色文件'
        text = decode_text_bytes(colors_txt.file.read(), source=source)
    else:
        text = colors_text or ''
    if not text.strip():
        raise ColorParseError('请上传颜色定义 TXT 文件')
    manual = manual_colors_text.strip()
    if manual:
        text = f'{text.rstrip()}\nCOLORS\n{manual}'
    return text


def safe_name(value: str, fallback: str = 'item') -> str:
    cleaned = re.sub(r'[^\w.\-#]+', '_', value.strip(), flags=re.UNICODE).strip('._')
    return cleaned[:160] or fallback
