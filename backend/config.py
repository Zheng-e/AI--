import os
import socket
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / 'storage'
UPLOAD_DIR = STORAGE_DIR / 'uploads'
OUTPUT_DIR = STORAGE_DIR / 'outputs'
TEMP_DIR = STORAGE_DIR / 'temp'
WORKFLOW_DIR = BASE_DIR
DEFAULT_WORKFLOW = WORKFLOW_DIR / 'image_flux2_working.json'
DEFAULT_COLORS_TXT = WORKFLOW_DIR / 'FS03899' / 'FS03899.txt'
COMFY_URL = os.environ.get('COMFY_URL', 'http://127.0.0.1:8188')
DEFAULT_TARGET_WIDTH = int(os.environ.get('TARGET_WIDTH', '1601'))
DEFAULT_TARGET_HEIGHT = int(os.environ.get('TARGET_HEIGHT', '2086'))
DEFAULT_GUIDANCE = float(os.environ.get('GUIDANCE', '3.5'))
DEFAULT_STEPS = int(os.environ.get('STEPS', '20'))
DEFAULT_STEPS_8 = int(os.environ.get('STEPS_8', '8'))
SERVER_ID = os.environ.get('SERVER_ID', socket.gethostname())
SERVER_NAME = os.environ.get('SERVER_NAME', 'Server')

# Cloud API config
API_BASE_URL = os.environ.get('API_BASE_URL', 'https://147ai.com')
API_KEYS_FILE = BASE_DIR / 'api.txt'
DEFAULT_API_MODEL = 'gpt-image-2-client'
DEFAULT_API_CONCURRENCY = int(os.environ.get('API_CONCURRENCY', '3'))
