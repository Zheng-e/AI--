import argparse
import json
import random
import re
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests


WORKFLOW_PATH = Path(__file__).with_name("image_flux2 (1).json")
DEFAULT_COLORS_TXT = Path(__file__).with_name("FS03856.txt")
DEFAULT_INPUT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "改色结果"
TARGET_OUTPUT_WIDTH = 1601
TARGET_OUTPUT_HEIGHT = 2086
TARGET_OUTPUT_MEGAPIXELS = (TARGET_OUTPUT_WIDTH * TARGET_OUTPUT_HEIGHT) / 1_000_000
INPUT_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


PROMPT_TEMPLATES = {
    "top": (
        "Recolor all visible {GARMENT_CATEGORY} items in the image for the {GARMENT}. Keep the original model, face, skin, hair, pose, expression, body shape, camera angle, framing, background, environment, lighting direction, lighting intensity, exposure, white balance, global color grading, contrast, saturation, shadows, highlights, reflections, and all non-garment pixels exactly unchanged.\n\n"
        "Change all visible {GARMENT_CATEGORY} items to the exact target color {RGB_VALUE} and exact HEX value {HEX_VALUE}. If multiple {GARMENT_CATEGORY} pieces are visible, recolor every one of them. Do not leave any matching garment piece unmodified. Do not modify pants, shorts, skirt, shoes, accessories, or any other non-target item.\n\n"
        "Preserve the original garment structure exactly. Keep the neckline, collar, seams, stitching, hems, cuffs, folds, wrinkles, fabric weave, edge shapes, and silhouette unchanged. Do not add, remove, or redesign any construction details. Do not invent new stitching, do not create extra lines, and do not redraw the garment.\n\n"
        "Match the garment color faithfully to the target RGB value. Do not make it brighter, cleaner, more vivid, more saturated, neon, glossy, or more colorful than the target color. Preserve realistic textile behavior, natural shading, subtle highlights, and material depth without altering the rest of the scene.\n\n"
        "The result must look like a minimal, physically plausible recolor edit on an authentic product photograph, not a repaint or redesign.\n\n"
        "Negative prompt:\n"
        "Do not change the background saturation, contrast, color grading, or white balance. Do not modify pants, shorts, skirt, shoes, accessories, or any non-target clothing. Do not alter seams, stitching, collars, hems, neckline structure, or silhouette. Do not invent new garment details. Do not oversaturate the garment. Do not make the clothing brighter, cleaner, more vivid, more saturated, glossy, or enhanced beyond the target RGB. Do not repaint the whole image. Do not change any non-garment pixels. Do not create AI artifacts, plastic textures, or unnatural redraws."
    ),
    "bottom": (
        "Recolor all visible {GARMENT_CATEGORY} items in the image for the {GARMENT}. Keep the original model, face, skin, hair, pose, expression, body shape, camera angle, framing, background, environment, lighting direction, lighting intensity, exposure, white balance, global color grading, contrast, saturation, shadows, highlights, reflections, and all non-garment pixels exactly unchanged.\n\n"
        "Change all visible {GARMENT_CATEGORY} items to the exact target color {RGB_VALUE} and exact HEX value {HEX_VALUE}. If multiple {GARMENT_CATEGORY} pieces are visible, recolor every one of them. Do not leave any matching garment piece unmodified. Do not modify tops, shirts, jackets, shoes, accessories, or any other non-target item.\n\n"
        "Preserve the original garment structure exactly. Keep the waistband, fly, seams, stitching, hems, pleats, folds, wrinkles, pocket shapes, fabric weave, edge shapes, and silhouette unchanged. Do not add, remove, or redesign any construction details. Do not invent new stitching, do not create extra lines, and do not redraw the garment.\n\n"
        "Match the garment color faithfully to the target RGB value. Do not make it brighter, cleaner, more vivid, more saturated, neon, glossy, or more colorful than the target color. Preserve realistic textile behavior, natural shading, subtle highlights, and material depth without altering the rest of the scene.\n\n"
        "The result must look like a minimal, physically plausible recolor edit on an authentic product photograph, not a repaint or redesign.\n\n"
        "Negative prompt:\n"
        "Do not change the background saturation, contrast, color grading, or white balance. Do not modify tops, shirts, jackets, shoes, accessories, or any non-target clothing. Do not alter seams, stitching, waistline structure, hems, or silhouette. Do not invent new garment details. Do not oversaturate the garment. Do not make the clothing brighter, cleaner, more vivid, more saturated, glossy, or enhanced beyond the target RGB. Do not repaint the whole image. Do not change any non-garment pixels. Do not create AI artifacts, plastic textures, or unnatural redraws."
    ),
    "dress": (
        "Recolor all visible dress items in the image for the {GARMENT}. Keep the original model, face, skin, hair, pose, expression, body shape, camera angle, framing, background, environment, lighting direction, lighting intensity, exposure, white balance, global color grading, contrast, saturation, shadows, highlights, reflections, and all non-garment pixels exactly unchanged.\n\n"
        "Change all visible dresses to the exact target color {RGB_VALUE} and exact HEX value {HEX_VALUE}. If multiple dress parts or layered dress pieces are visible, recolor every one of them. Do not leave any matching dress piece unmodified. Do not modify shoes, accessories, or any other non-target item.\n\n"
        "Preserve the original garment structure exactly. Keep the neckline, straps, seams, stitching, hems, folds, wrinkles, fabric weave, edge shapes, fringe, sequins, and silhouette unchanged. Do not add, remove, or redesign any construction details. Do not invent new stitching, do not create extra lines, and do not redraw the garment.\n\n"
        "Match the garment color faithfully to the target RGB value. Do not make it brighter, cleaner, more vivid, more saturated, neon, glossy, or more colorful than the target color. Preserve realistic textile behavior, natural shading, subtle highlights, and material depth without altering the rest of the scene.\n\n"
        "The result must look like a minimal, physically plausible recolor edit on an authentic product photograph, not a repaint or redesign.\n\n"
        "Negative prompt:\n"
        "Do not change the background saturation, contrast, color grading, or white balance. Do not modify shoes or accessories. Do not alter seams, stitching, neckline structure, hems, straps, fringe, sequins, or silhouette. Do not invent new garment details. Do not oversaturate the garment. Do not make the clothing brighter, cleaner, more vivid, more saturated, glossy, or enhanced beyond the target RGB. Do not repaint the whole image. Do not change any non-garment pixels. Do not create AI artifacts, plastic textures, or unnatural redraws."
    ),
}


CATEGORY_KEYWORDS = [
    ("bottom", ["裤", "短裤", "长裤", "牛仔裤", "半身裙", "裙"]),
    ("dress", ["裙", "dress"]),
    ("top", ["上衣", "t恤", "T恤", "POLO", "背心", "吊带", "文胸", "衬衫", "卫衣", "夹克", "外套"]),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch recolor product folders with a ComfyUI Flux2 workflow.")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188", help="ComfyUI base URL")
    parser.add_argument("--workflow", default=str(WORKFLOW_PATH), help="Path to workflow JSON")
    parser.add_argument("--colors-txt", default=str(DEFAULT_COLORS_TXT), help="Optional default color definition txt")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT), help="Root directory containing product folders")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Root directory for outputs")
    parser.add_argument("--prompt-template", default=None, help="Optional prompt template override")
    parser.add_argument("--print-prompts", action="store_true", help="Print prompt preview before execution")
    parser.add_argument("--seed", type=int, default=0, help="Fixed noise seed; 0 means random per job")
    parser.add_argument("--enable-lora", action="store_true", help="Enable LoRA branch in workflow")
    parser.add_argument("--enable-8-step-lora", action="store_true", help="Enable 8-step LoRA mode")
    parser.add_argument("--steps", type=int, default=20, help="Steps when 8-step LoRA mode is off")
    parser.add_argument("--steps-8", type=int, default=8, help="Steps when 8-step LoRA mode is on")
    parser.add_argument("--guidance", type=float, default=3.5, help="Flux guidance value")
    parser.add_argument("--target-width", type=int, default=TARGET_OUTPUT_WIDTH, help="Target output width for the working resolution")
    parser.add_argument("--target-height", type=int, default=TARGET_OUTPUT_HEIGHT, help="Target output height for the working resolution")
    parser.add_argument("--wait", type=float, default=2.0, help="Seconds to wait between queue polls")
    return parser.parse_args()


def sanitize_name(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:120] or "unnamed"


def parse_colors_file(path: Path) -> Tuple[str, List[Tuple[str, str]]]:
    text = path.read_text(encoding="utf-8-sig")
    garment_name = "garment"
    colors: List[Tuple[str, str]] = []
    in_colors = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("GARMENT"):
            garment_name = line.split(":", 1)[1].strip() if ":" in line else garment_name
            in_colors = False
            continue
        if line.startswith("COLORS"):
            in_colors = True
            continue
        if not in_colors:
            continue
        m = re.match(r"(.+?)\s*[：:]\s*#?([0-9a-fA-F]{6})", line)
        if m:
            colors.append((m.group(1).strip(), f"#{m.group(2).lower()}"))
    if not colors:
        raise ValueError(f"No colors found in {path}")
    return garment_name, colors


def hex_to_rgb(hex_value: str) -> Tuple[int, int, int]:
    h = hex_value.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def load_workflow(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def set_nested_input(workflow: Dict, node_id: str, key: str, value) -> None:
    workflow[node_id]["inputs"][key] = value


def infer_category(garment_name: str) -> str:
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword.lower() in garment_name.lower() for keyword in keywords):
            return category
    return "top"


def build_prompt(rgb: Tuple[int, int, int], hex_value: str, garment_name: str, template: Optional[str]) -> str:
    rgb_text = f"RGB({rgb[0]}, {rgb[1]}, {rgb[2]})"
    category = infer_category(garment_name)
    if template:
        return template.format(
            RGB_VALUE=rgb_text,
            HEX_VALUE=hex_value,
            GARMENT=garment_name,
            GARMENT_CATEGORY=category,
        )
    return PROMPT_TEMPLATES.get(category, PROMPT_TEMPLATES["top"]).format(
        RGB_VALUE=rgb_text,
        HEX_VALUE=hex_value,
        GARMENT=garment_name,
        GARMENT_CATEGORY=category,
    )


def prepare_workflow(
    base_workflow: Dict,
    image_filename: str,
    prompt: str,
    seed: int,
    enable_lora: bool,
    enable_8_step_lora: bool,
    steps: int,
    steps_8: int,
    guidance: float,
    garment_name: str,
    target_width: int,
    target_height: int,
) -> Dict:
    workflow = json.loads(json.dumps(base_workflow))
    set_nested_input(workflow, "46", "image", image_filename)
    set_nested_input(workflow, "68:6", "text", prompt)
    set_nested_input(workflow, "68:25", "noise_seed", seed)
    set_nested_input(workflow, "68:94", "value", enable_8_step_lora)
    set_nested_input(workflow, "68:92", "switch", enable_lora)
    set_nested_input(workflow, "68:93", "switch", enable_8_step_lora)
    set_nested_input(workflow, "68:26", "guidance", guidance)
    set_nested_input(workflow, "68:90", "value", steps_8)
    set_nested_input(workflow, "68:91", "value", steps)
    set_nested_input(workflow, "45", "megapixels", (target_width * target_height) / 1_000_000)
    set_nested_input(workflow, "68:47", "width", target_width)
    set_nested_input(workflow, "68:47", "height", target_height)
    set_nested_input(workflow, "68:72", "image", ["45", 0])
    set_nested_input(workflow, "68:48", "width", ["68:72", 0])
    set_nested_input(workflow, "68:48", "height", ["68:72", 1])
    set_nested_input(workflow, "9", "filename_prefix", f"batch_flux2_{sanitize_name(garment_name)}")
    return workflow


def upload_image(comfy_url: str, image_path: Path) -> str:
    with image_path.open("rb") as f:
        files = {"image": (image_path.name, f, "image/jpeg")}
        data = {"type": "input"}
        resp = requests.post(urljoin(comfy_url, "/upload/image"), files=files, data=data, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    if "name" not in payload:
        raise RuntimeError(f"Unexpected upload response: {payload}")
    return payload["name"]


def queue_prompt(comfy_url: str, workflow: Dict) -> str:
    resp = requests.post(urljoin(comfy_url, "/prompt"), json={"prompt": workflow}, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    prompt_id = payload.get("prompt_id") or payload.get("id")
    if not prompt_id:
        raise RuntimeError(f"Unexpected queue response: {payload}")
    return prompt_id


def get_history(comfy_url: str, prompt_id: str) -> Dict:
    resp = requests.get(urljoin(comfy_url, f"/history/{prompt_id}"), timeout=120)
    resp.raise_for_status()
    return resp.json()


def wait_for_completion(comfy_url: str, prompt_id: str, wait_seconds: float) -> Dict:
    while True:
        history = get_history(comfy_url, prompt_id)
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(wait_seconds)


def extract_output_images(history_entry: Dict) -> List[Dict]:
    outputs = history_entry.get("outputs", {})
    images: List[Dict] = []
    for node_output in outputs.values():
        for img in node_output.get("images", []):
            images.append(img)
    return images


def save_output_image(comfy_url: str, image_info: Dict, output_dir: Path, prefix: str) -> Path:
    params = {
        "filename": image_info["filename"],
        "subfolder": image_info.get("subfolder", ""),
        "type": image_info.get("type", "output"),
    }
    resp = requests.get(urljoin(comfy_url, "/view"), params=params, timeout=120)
    resp.raise_for_status()
    suffix = Path(image_info["filename"]).suffix or ".png"
    safe_name = sanitize_name(prefix)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_name}{suffix}"
    output_path.write_bytes(resp.content)
    return output_path


def list_images(input_dir: Path) -> List[Path]:
    return sorted([p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in INPUT_IMAGE_EXTS])


def parse_product_folder(product_dir: Path, default_colors_txt: Optional[Path]) -> Tuple[str, List[Tuple[str, str]]]:
    txt_candidates = [product_dir / f"{product_dir.name}.txt"]
    if default_colors_txt and default_colors_txt.exists() and default_colors_txt.parent == product_dir:
        txt_candidates.insert(0, default_colors_txt)
    txt_candidates.extend(sorted(p for p in product_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt"))

    seen = set()
    for candidate in txt_candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists() and candidate.is_file():
            return parse_colors_file(candidate)
    raise FileNotFoundError(f"No txt file found in {product_dir}")


def find_product_dirs(base_dir: Path) -> List[Path]:
    dirs = []
    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name in {"改色结果", "__pycache__", ".venv"}:
            continue
        if list_images(entry) or any(p.suffix.lower() == ".txt" for p in entry.iterdir() if p.is_file()):
            dirs.append(entry)
    return dirs


def process_product_folder(
    product_dir: Path,
    base_workflow: Dict,
    comfy_url: str,
    output_root: Path,
    prompt_template: Optional[str],
    seed: int,
    enable_lora: bool,
    enable_8_step_lora: bool,
    steps: int,
    steps_8: int,
    guidance: float,
    print_prompts: bool,
    colors_txt: Optional[Path],
    target_width: int,
    target_height: int,
) -> Dict[str, object]:
    garment_name, colors = parse_product_folder(product_dir, colors_txt)
    images = list_images(product_dir)
    if not images:
        raise ValueError(f"No images found in {product_dir}")

    output_dir = output_root / product_dir.name
    print(f"\n{'=' * 60}")
    print(f"Product: {product_dir.name}")
    print(f"Garment: {garment_name}")
    print(f"Category: {infer_category(garment_name)}")
    print(f"Images: {len(images)} | Colors: {len(colors)}")
    print(f"{'=' * 60}")

    summary = {"ok": 0, "skipped": 0, "failed": []}
    for image_path in images:
        print(f"Uploading {image_path.name}...")
        comfy_image_name = upload_image(comfy_url, image_path)

        for color_name, hex_value in colors:
            rgb = hex_to_rgb(hex_value)
            job_seed = seed if seed != 0 else random.randint(1, 2_000_000_000)
            prompt = build_prompt(rgb, hex_value, garment_name, prompt_template)
            if print_prompts:
                print("\n===== PROMPT PREVIEW START =====")
                print(f"PRODUCT: {product_dir.name}")
                print(f"IMAGE: {image_path.name}")
                print(f"COLOR: {color_name} | {hex_value} | RGB{rgb}")
                print(prompt)
                print("===== PROMPT PREVIEW END =====\n")

            workflow = prepare_workflow(
                base_workflow=base_workflow,
                image_filename=comfy_image_name,
                prompt=prompt,
                seed=job_seed,
                enable_lora=enable_lora,
                enable_8_step_lora=enable_8_step_lora,
                steps=steps,
                steps_8=steps_8,
                guidance=guidance,
                garment_name=garment_name,
                target_width=target_width,
                target_height=target_height,
            )

            print(f"Queueing {product_dir.name}/{image_path.name} -> {color_name} ({hex_value})...")
            prompt_id = queue_prompt(comfy_url, workflow)
            history_entry = wait_for_completion(comfy_url, prompt_id, 2.0)
            output_images = extract_output_images(history_entry)
            if not output_images:
                print(f"No output images found for {image_path.name} / {color_name}")
                summary["failed"].append((product_dir.name, image_path.name, hex_value, "no-output"))
                continue

            for idx, img in enumerate(output_images, start=1):
                prefix = f"{image_path.stem}_{sanitize_name(color_name)}_{hex_value}_{idx}"
                saved = save_output_image(comfy_url, img, output_dir, prefix)
                print(f"Saved: {saved}")
                summary["ok"] += 1
    return summary


def main() -> None:
    args = parse_args()
    comfy_url = args.comfy_url.rstrip("/")
    workflow_path = Path(args.workflow)
    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    colors_txt = Path(args.colors_txt) if args.colors_txt else None

    if not workflow_path.exists():
        raise FileNotFoundError(f"Workflow not found: {workflow_path}")
    if not input_root.exists():
        raise FileNotFoundError(f"Input root not found: {input_root}")

    base_workflow = load_workflow(workflow_path)
    product_dirs = find_product_dirs(input_root)
    if not product_dirs:
        raise ValueError(f"No product folders found in {input_root}")

    print(f"Found {len(product_dirs)} product folder(s): {[d.name for d in product_dirs]}")
    print(f"Output root: {output_root}")
    print(f"Default guidance: {args.guidance}")
    print(f"Default steps: {args.steps} | 8-step LoRA steps: {args.steps_8}")

    total_ok = 0
    total_skipped = 0
    failures = []
    for product_dir in product_dirs:
        try:
            summary = process_product_folder(
                product_dir=product_dir,
                base_workflow=base_workflow,
                comfy_url=comfy_url,
                output_root=output_root,
                prompt_template=args.prompt_template,
                seed=args.seed,
                enable_lora=args.enable_lora,
                enable_8_step_lora=args.enable_8_step_lora,
                steps=args.steps,
                steps_8=args.steps_8,
                guidance=args.guidance,
                print_prompts=args.print_prompts,
                colors_txt=colors_txt,
                target_width=args.target_width,
                target_height=args.target_height,
            )
            total_ok += int(summary["ok"])
            total_skipped += int(summary["skipped"])
            failures.extend(summary["failed"])
        except Exception as exc:
            print(f"[FAIL] {product_dir.name}: {exc}")
            failures.append((product_dir.name, "<folder>", "<unknown>", str(exc)))

    print(f"\nDone. Generated: {total_ok}, skipped existing: {total_skipped}, failed: {len(failures)}")
    if failures:
        print("Failed items:")
        for item in failures:
            print(f"  - {item[0]} | {item[1]} | {item[2]} -> {item[3]}")


if __name__ == "__main__":
    main()
