import pytest
from fastapi.testclient import TestClient

from backend.main import STORE, app


@pytest.fixture
def client():
    STORE._jobs.clear()
    return TestClient(app)


PNG_DATA = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
    b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
    b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
    b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get('/api/health')
        assert resp.status_code == 200
        assert resp.json()['ok'] is True


class TestDefaultsEndpoint:
    def test_defaults(self, client):
        resp = client.get('/api/defaults')
        assert resp.status_code == 200
        data = resp.json()
        assert 'guidance' in data
        assert 'default_api_model' in data
        assert 'max_api_concurrency' in data


class TestParseColorsEndpoint:
    def test_parse_valid_colors(self, client):
        colors_content = 'GARMENT: T恤\nCOLORS\n红色: #ff0000\n蓝色: #0000ff'
        resp = client.post(
            '/api/parse-colors',
            files={'colors_txt': ('colors.txt', colors_content.encode('utf-8'), 'text/plain')},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['garment_name'] == 'T恤'
        assert len(data['colors']) == 2
        assert data['colors'][0]['name'] == '红色'

    def test_parse_gbk_colors(self, client):
        colors_content = 'GARMENT: 紧身背心\nCOLORS\n湖蓝色: #36acb6'
        resp = client.post(
            '/api/parse-colors',
            files={'colors_txt': ('colors.txt', colors_content.encode('gbk'), 'text/plain')},
        )
        assert resp.status_code == 200
        assert resp.json()['garment_name'] == '紧身背心'

    def test_parse_no_colors_returns_clear_400(self, client):
        resp = client.post(
            '/api/parse-colors',
            files={'colors_txt': ('colors.txt', 'GARMENT: T恤\n'.encode('utf-8'), 'text/plain')},
        )
        assert resp.status_code == 400
        assert '未找到 COLORS 段' in resp.json()['detail']


class TestCreateJobEndpoint:
    def test_create_job_no_images(self, client):
        resp = client.post('/api/jobs', data={'colors_text': 'COLORS\n红色: #ff0000'})
        assert resp.status_code == 400

    def test_create_job_with_legacy_colors_text(self, client, monkeypatch):
        monkeypatch.setattr('backend.main.RUNNER.submit', lambda **kwargs: 'test-job-id')
        resp = client.post(
            '/api/jobs',
            data={'colors_text': 'COLORS\n红色: #ff0000', 'garment_name': 'T恤'},
            files=[('images', ('test.png', PNG_DATA, 'image/png'))],
        )
        assert resp.status_code == 200
        assert resp.json()['job_id'] == 'test-job-id'

    def test_create_job_with_colors_txt_file(self, client, monkeypatch):
        monkeypatch.setattr('backend.main.RUNNER.submit', lambda **kwargs: 'test-job-id')
        resp = client.post(
            '/api/jobs',
            data={'garment_name': '短裤'},
            files=[
                ('colors_txt', ('colors.txt', 'COLORS\n灰色: #888888'.encode('gbk'), 'text/plain')),
                ('images', ('test.png', PNG_DATA, 'image/png')),
            ],
        )
        assert resp.status_code == 200


class TestListJobsEndpoint:
    def test_list_empty(self, client):
        resp = client.get('/api/jobs')
        assert resp.status_code == 200
        assert resp.json()['jobs'] == []

    def test_filter_by_engine(self, client):
        STORE.create(status='queued', engine='comfyui')
        STORE.create(status='queued', engine='api')
        resp = client.get('/api/jobs?engine=api')
        assert len(resp.json()['jobs']) == 1
        assert resp.json()['jobs'][0]['engine'] == 'api'


class TestOutputFilesEndpoint:
    def test_serves_output_file(self, client, tmp_path):
        out_dir = tmp_path / 'out'
        out_dir.mkdir()
        image = out_dir / 'result.png'
        image.write_bytes(PNG_DATA)
        job = STORE.create(status='completed', output_dir=str(out_dir))
        resp = client.get(f'/api/jobs/{job.job_id}/files/result.png')
        assert resp.status_code == 200

    def test_rejects_path_traversal(self, client, tmp_path):
        out_dir = tmp_path / 'out'
        out_dir.mkdir()
        job = STORE.create(status='completed', output_dir=str(out_dir))
        resp = client.get(f'/api/jobs/{job.job_id}/files/..%2Fsecret.png')
        assert resp.status_code == 404


class TestIndexEndpoint:
    def test_index_serves_html(self, client):
        resp = client.get('/')
        assert resp.status_code == 200
        assert '本地改色' in resp.text

    def test_api_page_serves_html(self, client):
        resp = client.get('/api-recolor')
        assert resp.status_code == 200
        assert 'API 并行改色' in resp.text
