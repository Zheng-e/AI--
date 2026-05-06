from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple


CATEGORY_KEYWORDS = [
    ('bottom', ['裤', '短裤', '长裤', '牛仔裤', '半身裙', '裙']),
    ('dress', ['裙', 'dress']),
    ('top', ['上衣', 't恤', 'T恤', 'POLO', '背心', '吊带', '文胸', '衬衫', '卫衣', '夹克', '外套']),
]


DEFAULT_PROMPT_TEMPLATES = {
    'top': (
        'Recolor all visible {GARMENT_CATEGORY} items in the image for the {GARMENT}. Keep the original model, face, skin, hair, pose, expression, body shape, camera angle, framing, background, environment, lighting direction, lighting intensity, exposure, white balance, global color grading, contrast, saturation, shadows, highlights, reflections, and all non-garment pixels exactly unchanged.\n\n'
        'Change all visible {GARMENT_CATEGORY} items to the exact target color {RGB_VALUE} and exact HEX value {HEX_VALUE}. If multiple {GARMENT_CATEGORY} pieces are visible, recolor every one of them. Do not leave any matching garment piece unmodified. Do not modify pants, shorts, skirt, shoes, accessories, or any other non-target item.\n\n'
        'Preserve the original garment structure exactly. Keep the neckline, collar, seams, stitching, hems, cuffs, folds, wrinkles, fabric weave, edge shapes, and silhouette unchanged. Do not add, remove, or redesign any construction details. Do not invent new stitching, do not create extra lines, and do not redraw the garment.\n\n'
        'Match the garment color faithfully to the target RGB value. Do not make it brighter, cleaner, more vivid, more saturated, neon, glossy, or more colorful than the target color. Preserve realistic textile behavior, natural shading, subtle highlights, and material depth without altering the rest of the scene.\n\n'
        'The result must look like a minimal, physically plausible recolor edit on an authentic product photograph, not a repaint or redesign.\n\n'
        'Negative prompt:\n'
        'Do not change the background saturation, contrast, color grading, or white balance. Do not modify pants, shorts, skirt, shoes, accessories, or any non-target clothing. Do not alter seams, stitching, collars, hems, neckline structure, or silhouette. Do not invent new garment details. Do not oversaturate the garment. Do not make the clothing brighter, cleaner, more vivid, more saturated, glossy, or enhanced beyond the target RGB. Do not repaint the whole image. Do not change any non-garment pixels. Do not create AI artifacts, plastic textures, or unnatural redraws.'
    ),
    'bottom': (
        'Recolor all visible {GARMENT_CATEGORY} items in the image for the {GARMENT}. Keep the original model, face, skin, hair, pose, expression, body shape, camera angle, framing, background, environment, lighting direction, lighting intensity, exposure, white balance, global color grading, contrast, saturation, shadows, highlights, reflections, and all non-garment pixels exactly unchanged.\n\n'
        'Change all visible {GARMENT_CATEGORY} items to the exact target color {RGB_VALUE} and exact HEX value {HEX_VALUE}. If multiple {GARMENT_CATEGORY} pieces are visible, recolor every one of them. Do not leave any matching garment piece unmodified. Do not modify tops, shirts, jackets, shoes, accessories, or any other non-target item.\n\n'
        'Preserve the original garment structure exactly. Keep the waistband, fly, seams, stitching, hems, pleats, folds, wrinkles, pocket shapes, fabric weave, edge shapes, and silhouette unchanged. Do not add, remove, or redesign any construction details. Do not invent new stitching, do not create extra lines, and do not redraw the garment.\n\n'
        'Match the garment color faithfully to the target RGB value. Do not make it brighter, cleaner, more vivid, more saturated, neon, glossy, or more colorful than the target color. Preserve realistic textile behavior, natural shading, subtle highlights, and material depth without altering the rest of the scene.\n\n'
        'The result must look like a minimal, physically plausible recolor edit on an authentic product photograph, not a repaint or redesign.\n\n'
        'Negative prompt:\n'
        'Do not change the background saturation, contrast, color grading, or white balance. Do not modify tops, shirts, jackets, shoes, accessories, or any non-target clothing. Do not alter seams, stitching, waistline structure, hems, or silhouette. Do not invent new garment details. Do not oversaturate the garment. Do not make the clothing brighter, cleaner, more vivid, more saturated, glossy, or enhanced beyond the target RGB. Do not repaint the whole image. Do not change any non-garment pixels. Do not create AI artifacts, plastic textures, or unnatural redraws.'
    ),
    'dress': (
        'Recolor all visible dress items in the image for the {GARMENT}. Keep the original model, face, skin, hair, pose, expression, body shape, camera angle, framing, background, environment, lighting direction, lighting intensity, exposure, white balance, global color grading, contrast, saturation, shadows, highlights, reflections, and all non-garment pixels exactly unchanged.\n\n'
        'Change all visible dresses to the exact target color {RGB_VALUE} and exact HEX value {HEX_VALUE}. If multiple dress parts or layered dress pieces are visible, recolor every one of them. Do not leave any matching dress piece unmodified. Do not modify shoes, accessories, or any other non-target item.\n\n'
        'Preserve the original garment structure exactly. Keep the neckline, straps, seams, stitching, hems, folds, wrinkles, fabric weave, edge shapes, fringe, sequins, and silhouette unchanged. Do not add, remove, or redesign any construction details. Do not invent new stitching, do not create extra lines, and do not redraw the garment.\n\n'
        'Match the garment color faithfully to the target RGB value. Do not make it brighter, cleaner, more vivid, more saturated, neon, glossy, or more colorful than the target color. Preserve realistic textile behavior, natural shading, subtle highlights, and material depth without altering the rest of the scene.\n\n'
        'The result must look like a minimal, physically plausible recolor edit on an authentic product photograph, not a repaint or redesign.\n\n'
        'Negative prompt:\n'
        'Do not change the background saturation, contrast, color grading, or white balance. Do not modify shoes or accessories. Do not alter seams, stitching, neckline structure, hems, straps, fringe, sequins, or silhouette. Do not invent new garment details. Do not oversaturate the garment. Do not make the clothing brighter, cleaner, more vivid, more saturated, glossy, or enhanced beyond the target RGB. Do not repaint the whole image. Do not change any non-garment pixels. Do not create AI artifacts, plastic textures, or unnatural redraws.'
    ),
}


def infer_category(garment_name: str) -> str:
    lower = garment_name.lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword.lower() in lower for keyword in keywords):
            return category
    return 'top'


def build_prompt(garment_name: str, hex_value: str, rgb: Tuple[int, int, int], template: str | None = None) -> str:
    category = infer_category(garment_name)
    rgb_value = f'RGB({rgb[0]}, {rgb[1]}, {rgb[2]})'
    prompt_template = template or DEFAULT_PROMPT_TEMPLATES[category]
    if '{HEX_VALUE}' not in prompt_template and '{RGB_VALUE}' not in prompt_template:
        prompt_template = prompt_template + '\n\nUse target color {RGB_VALUE} ({HEX_VALUE}).'
    return prompt_template.format(
        garment=garment_name,
        hex_value=hex_value,
        rgb_value=rgb_value,
        RGB_VALUE=rgb_value,
        HEX_VALUE=hex_value,
        category=category,
        GARMENT=garment_name,
        GARMENT_CATEGORY=category,
    )


def load_workflow(path: Path) -> Dict:
    return json.loads(path.read_text(encoding='utf-8'))


def sanitize_prompt_template(template: str | None) -> str | None:
    if template is None:
        return None
    text = template.strip()
    return text or None
