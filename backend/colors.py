from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple


class ColorParseError(ValueError):
    """User-facing error for invalid color definition files."""


def decode_text_bytes(data: bytes, source: str = '颜色文件') -> str:
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030', 'gbk'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ColorParseError(f'{source} 编码无法识别，请使用 UTF-8 或 GBK/GB18030 文本')


def parse_colors_bytes(data: bytes, source: str = '颜色文件') -> Tuple[str, List[Tuple[str, str]]]:
    return parse_colors_text(decode_text_bytes(data, source=source), source=source)


def parse_colors_file(path: Path) -> Tuple[str, List[Tuple[str, str]]]:
    return parse_colors_bytes(path.read_bytes(), source=str(path))


def parse_colors_text(text: str, source: str = '颜色文本') -> Tuple[str, List[Tuple[str, str]]]:
    garment_name = 'garment'
    colors: List[Tuple[str, str]] = []
    in_colors = False
    saw_colors_header = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        normalized = line.replace('：', ':')
        upper = normalized.upper()

        if upper.startswith('GARMENT'):
            if ':' not in normalized:
                raise ColorParseError(f'{source} 第 {line_number} 行 GARMENT 缺少冒号')
            garment_name = normalized.split(':', 1)[1].strip() or garment_name
            in_colors = False
            continue

        if upper == 'COLORS' or upper.startswith('COLORS:'):
            in_colors = True
            saw_colors_header = True
            continue

        if not in_colors:
            continue

        if ':' not in normalized:
            raise ColorParseError(f'{source} 第 {line_number} 行颜色缺少冒号')

        name, hex_value = normalized.split(':', 1)
        name = name.strip()
        hex_value = hex_value.strip().lstrip('#')

        if not name:
            raise ColorParseError(f'{source} 第 {line_number} 行颜色名为空')
        if len(hex_value) != 6:
            raise ColorParseError(f'{source} 第 {line_number} 行 hex 不是 6 位')
        if not re.fullmatch(r'[0-9a-fA-F]{6}', hex_value):
            raise ColorParseError(f'{source} 第 {line_number} 行 hex 包含非十六进制字符')

        colors.append((name, f'#{hex_value.lower()}'))

    if not saw_colors_header:
        raise ColorParseError(f'{source} 未找到 COLORS 段')
    if not colors:
        raise ColorParseError(f'{source} 中没有找到颜色，请使用“颜色名: #hex”格式')
    return garment_name, colors
