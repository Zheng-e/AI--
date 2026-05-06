import argparse
import copy
import random
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.comfy_client import ComfyClient
from backend.tasks import hex_to_rgb, parse_colors_file
from backend.workflow import build_prompt, infer_category, load_workflow


WORKFLOW_PATH = Path(__file__).with_name("image_flux2_working.json")
DEFAULT_COLORS_TXT = Path(__file__).resolve().parent / "FS03920" / "FS03920.txt"
DEFAULT_INPUT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "改色结果"
TARGET_OUTPUT_WIDTH = 1601
TARGET_OUTPUT_HEIGHT = 2086
INPUT_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


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
    parser.add_argument("--target-width", type=int, default=TARGET_OUTPUT_WIDTH, help="Target output width")
    parser.add_argument("--target-height", type=int, default=TARGET_OUTPUT_HEIGHT, help="Target output height")
    parser.add_argument("--wait", type=float, default=2.0, help="Seconds to wait between queue polls")
    return parser.parse_args()


def sanitize_name(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:120] or "unnamed"


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
    workflow = copy.deepcopy(base_workflow)
    workflow["46"]["inputs"]["image"] = image_filename
    workflow["68:6"]["inputs"]["text"] = prompt
    workflow["68:25"]["inputs"]["noise_seed"] = seed
    workflow["68:94"]["inputs"]["value"] = enable_8_step_lora
    workflow["68:92"]["inputs"]["switch"] = enable_lora
    workflow["68:93"]["inputs"]["switch"] = enable_8_step_lora
    workflow["68:26"]["inputs"]["guidance"] = guidance
    workflow["68:90"]["inputs"]["value"] = steps_8
    workflow["68:91"]["inputs"]["value"] = steps
    workflow["45"]["inputs"]["megapixels"] = (target_width * target_height) / 1_000_000
    workflow["68:47"]["inputs"]["width"] = target_width
    workflow["68:47"]["inputs"]["height"] = target_height
    workflow["68:72"]["inputs"]["image"] = ["45", 0]
    workflow["68:48"]["inputs"]["width"] = ["68:72", 0]
    workflow["68:48"]["inputs"]["height"] = ["68:72", 1]
    workflow["9"]["inputs"]["filename_prefix"] = f"batch_flux2_{sanitize_name(garment_name)}"
    return workflow


def list_images(input_dir: Path) -> List[Path]:
    return sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in INPUT_IMAGE_EXTS)


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
        if entry.name in {"改色结果", "__pycache__", ".venv", "storage", "已改色"}:
            continue
        if list_images(entry) or any(p.suffix.lower() == ".txt" for p in entry.iterdir() if p.is_file()):
            dirs.append(entry)
    return dirs


def process_product_folder(
    product_dir: Path,
    base_workflow: Dict,
    client: ComfyClient,
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

    summary: Dict[str, object] = {"ok": 0, "skipped": 0, "failed": []}
    for image_path in images:
        print(f"Uploading {image_path.name}...")
        comfy_image_name = client.upload_image(image_path)

        for color_name, hex_value in colors:
            rgb = hex_to_rgb(hex_value)
            job_seed = seed if seed != 0 else random.randint(1, 2_000_000_000)
            prompt = build_prompt(garment_name, hex_value, rgb, template=prompt_template)
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
            prompt_id = client.queue_prompt(workflow)
            history_entry = client.wait_for_completion(prompt_id, wait_seconds=2.0, timeout=1200.0)
            output_images = ComfyClient.extract_output_images(history_entry)
            if not output_images:
                print(f"No output images found for {image_path.name} / {color_name}")
                summary["failed"].append((product_dir.name, image_path.name, hex_value, "no-output"))
                continue

            for idx, img_info in enumerate(output_images, start=1):
                bytes_data = client.view_image(
                    img_info["filename"],
                    img_info.get("subfolder", ""),
                    img_info.get("type", "output"),
                )
                prefix = f"{image_path.stem}_{sanitize_name(color_name)}_{hex_value}_{idx}"
                safe_name = sanitize_name(prefix)
                suffix = Path(img_info["filename"]).suffix or ".png"
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = output_dir / f"{safe_name}{suffix}"
                output_path.write_bytes(bytes_data)
                print(f"Saved: {output_path}")
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

    client = ComfyClient(comfy_url)

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
                client=client,
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
