import pytest

from backend.colors import ColorParseError
from backend.tasks import (
    _parse_colors_text,
    hex_to_rgb,
    job_id_safe,
    parse_colors_file,
    parse_colors_file_bytes,
)


class TestHexToRgb:
    def test_red(self):
        assert hex_to_rgb('#ff0000') == (255, 0, 0)

    def test_without_hash(self):
        assert hex_to_rgb('00ff00') == (0, 255, 0)


class TestParseColorsText:
    def test_basic_parsing(self):
        text = 'GARMENT: T恤\nCOLORS\n红色: #ff0000\n蓝色: #0000ff'
        name, colors = _parse_colors_text(text)
        assert name == 'T恤'
        assert colors == [('红色', '#ff0000'), ('蓝色', '#0000ff')]

    def test_chinese_colon(self):
        text = 'COLORS\n绿色：#00ff00'
        _, colors = _parse_colors_text(text)
        assert colors == [('绿色', '#00ff00')]

    def test_no_garment_defaults(self):
        text = 'COLORS\n红色: #ff0000'
        name, _ = _parse_colors_text(text)
        assert name == 'garment'

    def test_missing_colors_header_has_clear_error(self):
        with pytest.raises(ColorParseError, match='未找到 COLORS 段'):
            _parse_colors_text('GARMENT: T恤\n红色: #ff0000')

    def test_missing_colon_has_line_number(self):
        with pytest.raises(ColorParseError, match='第 2 行颜色缺少冒号'):
            _parse_colors_text('COLORS\n红色 #ff0000')

    def test_invalid_hex_has_line_number(self):
        with pytest.raises(ColorParseError, match='第 2 行 hex 不是 6 位'):
            _parse_colors_text('COLORS\n红色: #12')

    def test_hex_case_normalized(self):
        text = 'COLORS\n红色: #FF0000'
        _, colors = _parse_colors_text(text)
        assert colors[0][1] == '#ff0000'


class TestParseColorsFileBytes:
    def test_utf8_bom(self):
        data = 'GARMENT: 衬衫\nCOLORS\n白色: #ffffff'.encode('utf-8-sig')
        name, colors = parse_colors_file_bytes(data)
        assert name == '衬衫'
        assert colors == [('白色', '#ffffff')]

    def test_plain_utf8(self):
        data = 'COLORS\n黑色: #000000'.encode('utf-8')
        _, colors = parse_colors_file_bytes(data)
        assert colors == [('黑色', '#000000')]

    def test_gbk(self):
        data = 'GARMENT: 紧身背心\nCOLORS\n湖蓝色: #36acb6'.encode('gbk')
        name, colors = parse_colors_file_bytes(data)
        assert name == '紧身背心'
        assert colors == [('湖蓝色', '#36acb6')]


class TestParseColorsFile:
    def test_from_file(self, tmp_path):
        path = tmp_path / 'colors.txt'
        path.write_text('GARMENT: 裤子\nCOLORS\n灰色: #888888', encoding='utf-8')
        name, colors = parse_colors_file(path)
        assert name == '裤子'
        assert colors == [('灰色', '#888888')]


class TestJobIdSafe:
    def test_alphanumeric(self):
        assert job_id_safe('abc123') == 'abc123'

    def test_special_chars_replaced(self):
        result = job_id_safe('a/b:c*d')
        assert '/' not in result
        assert ':' not in result
        assert '*' not in result

    def test_max_length(self):
        result = job_id_safe('a' * 100)
        assert len(result) <= 40
