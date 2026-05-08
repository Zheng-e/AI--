from __future__ import annotations

import re
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import DEFAULT_GUIDANCE, DEFAULT_STEPS, DEFAULT_STEPS_8, DEFAULT_TARGET_HEIGHT, DEFAULT_TARGET_WIDTH, SERVER_ID, SERVER_NAME, STORAGE_DIR
from .jobs import JobStore
from .tasks import TaskRunner, parse_colors_file_bytes
from .workflow import DEFAULT_PROMPT_TEMPLATES, sanitize_prompt_template

app = FastAPI(title='Flux2 Recolor Studio', version='0.3.0')
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
    }


@app.post('/api/parse-colors')
def parse_colors(colors_txt: UploadFile = File(...)) -> dict:
    data = colors_txt.file.read()
    garment_name, colors = parse_colors_file_bytes(data)
    return {
        'garment_name': garment_name,
        'colors': [{'name': name, 'hex': hex_value} for name, hex_value in colors],
    }


@app.post('/api/jobs')
def create_job(
    garment_name: str = Form(''),
    product_id: str = Form(''),
    colors_text: str = Form(...),
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
) -> dict:
    upload_root = STORAGE_DIR / 'uploads'
    upload_root.mkdir(parents=True, exist_ok=True)
    safe_pid = re.sub(r'[^\w.\-]', '_', product_id)[:60] if product_id else f'job_{int(time.time())}'
    job_image_dir = upload_root / safe_pid
    job_image_dir.mkdir(parents=True, exist_ok=True)

    incoming_images = list(images or [])
    if image is not None and image.filename not in {img.filename for img in incoming_images}:
        incoming_images.insert(0, image)
    if not incoming_images:
        raise HTTPException(status_code=400, detail='No image files provided')

    saved_images = []
    for idx, img in enumerate(incoming_images):
        original_name = Path(img.filename).name if img.filename else f'image_{idx + 1}.png'
        safe_name = re.sub(r'[^\w.\-]', '_', original_name)[:200]
        image_path = job_image_dir / safe_name
        image_path.write_bytes(img.file.read())
        saved_images.append(image_path)

    job_id = RUNNER.submit(
        product_id=product_id,
        garment_name=garment_name,
        colors_text=colors_text,
        image_paths=saved_images,
        prompt_template=sanitize_prompt_template(prompt_template),
        guidance=guidance,
        steps=steps,
        steps_8=steps_8,
        enable_lora=enable_lora,
        enable_8_step_lora=enable_8_step_lora,
        target_width=target_width,
        target_height=target_height,
    )
    return {'job_id': job_id}


@app.get('/api/jobs')
def list_jobs() -> dict:
    return {'jobs': [job.__dict__ for job in STORE.list()]}


@app.get('/api/jobs/{job_id}')
def get_job(job_id: str) -> dict:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='job not found')
    return job.__dict__


@app.post('/api/jobs/{job_id}/cancel')
def cancel_job(job_id: str) -> dict:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='job not found')
    ok = RUNNER.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail=f'job is {job.status}, cannot cancel')
    return {'job_id': job_id, 'status': 'cancelling'}


@app.post('/api/jobs/{job_id}/resume')
def resume_job(job_id: str) -> dict:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='job not found')
    ok = RUNNER.resume(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail=f'job is {job.status}, cannot resume')
    return {'job_id': job_id, 'status': 'queued'}


@app.get('/api/jobs/{job_id}/download')
def download_job(job_id: str):
    zip_path = RUNNER.zip_job_output(job_id)
    return FileResponse(path=str(zip_path), filename=zip_path.name, media_type='application/zip')


@app.get('/api/health')
def health() -> dict:
    jobs = STORE.list()
    return {
        'ok': True,
        'server_id': SERVER_ID,
        'server_name': SERVER_NAME,
        'running_jobs': sum(1 for j in jobs if j.status == 'running'),
        'queued_jobs': sum(1 for j in jobs if j.status == 'queued'),
        'total_jobs': len(jobs),
    }


@app.get('/api/server-info')
def server_info() -> dict:
    jobs = STORE.list()
    return {
        'server_id': SERVER_ID,
        'server_name': SERVER_NAME,
        'running_jobs': sum(1 for j in jobs if j.status == 'running'),
        'queued_jobs': sum(1 for j in jobs if j.status == 'queued'),
        'total_jobs': len(jobs),
    }
