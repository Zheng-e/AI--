# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作时提供指引。

## 项目概述

基于本地 ComfyUI（Flux2 工作流）的 AI 商品改色工具。用户上传商品图片和颜色定义 TXT 文件，系统为每张图片 × 每种颜色生成改色后的效果图。

界面语言为中文。

## 启动方式

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 FastAPI 服务（需要 ComfyUI 运行在 http://127.0.0.1:8188）
python app.py
# 或等效命令：
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Web 界面地址：`http://localhost:8000/`

## 两种运行模式

1. **Web 服务**（`app.py` / `backend/` 包）— FastAPI 应用，浏览器上传图片和颜色文件，任务在后台线程中执行。
2. **CLI 批量脚本**（`batch_comfyui_flux2_recolor.py`）— 独立脚本，扫描商品文件夹目录（每个文件夹包含图片和 `{文件夹名}.txt` 颜色文件），通过 ComfyUI API 顺序处理。

两种模式共享相同的提示词模板和工作流 JSON，但各自独立实现（未抽取公共模块）。

## 架构

```
app.py                    → 入口，导入 backend.main:app
backend/
  main.py                 → FastAPI 路由：/api/jobs, /api/defaults, /api/parse-colors, /api/health
  config.py               → 路径配置（storage/, outputs/）、ComfyUI 地址、默认参数
  jobs.py                 → 线程安全的内存 JobStore（JobRecord 数据类）
  tasks.py                → TaskRunner：提交任务到后台线程、解析颜色文件、编排 ComfyUI 调用
  comfy_client.py         → ComfyUI HTTP 客户端（上传、排队、轮询历史、获取输出）
  workflow.py             → 加载工作流 JSON、根据品类（top/bottom/dress）构建提示词
frontend/
  index.html, app.js, style.css → 单页应用，作为静态文件提供
image_flux2_working.json  → ComfyUI 工作流定义（节点图）
batch_comfyui_flux2_recolor.py → 独立 CLI 批处理脚本
storage/                  → 运行时数据：uploads/, outputs/, temp/
```

## 关键概念

**颜色定义 TXT 格式：**
```
GARMENT: 商品名称
COLORS
颜色名: #hexvalue
```

**商品品类推断：** `workflow.py:infer_category()` 根据中文关键词将商品名映射为 `top`（上衣）、`bottom`（下装）或 `dress`（连衣裙）。每个品类有专门的提示词模板，保留品类特有的结构细节（如下装保留腰头，上衣保留领口）。

**提示词模板变量：** `{GARMENT}`、`{GARMENT_CATEGORY}`、`{RGB_VALUE}`、`{HEX_VALUE}`

**ComfyUI 工作流关键节点 ID**（在 `_prepare_workflow` 中使用）：
- `46` — 输入图片
- `68:6` — 改色提示词文本
- `68:25` — 噪声种子
- `68:26` — guidance scale
- `68:90` / `68:91` — 8步和正常步数
- `68:92` / `68:93` / `68:94` — LoRA 开关
- `68:47` — 目标宽高
- `68:72` — 缩放后的图片尺寸
- `45` — 图片缩放用的百万像素值
- `9` — 输出文件名前缀

**任务生命周期：** queued → running → completed/failed。每张图片 × 每种颜色组合对应一个 ComfyUI 队列项，进度以百分比跟踪。
