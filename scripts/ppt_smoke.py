#!/usr/bin/env python3
"""真实 deck 冒烟：渲染指定页并校验尺寸、耗时、文件大小。

用法（在带 LibreOffice 的镜像里跑）：

    docker run --rm \
      -v ~/.hermes/tmp/xdsh:/opt/data/tmp/xdsh:ro \
      -v ~/.hermes/tmp/pptpage:/opt/data/tmp/pptpage \
      aisecretary:test .venv/bin/python scripts/ppt_smoke.py \
        --deck "/opt/data/tmp/xdsh/9-主题介绍-人工智能驱动的水利科学研究.pptx" \
        --pages 5,6,8

退出码：0 全部达标；1 有页面失败或超预算。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

DEFAULT_BUDGET_MS = 20_000
DEFAULT_MIN_BYTES = 10_000
EXPECTED = {(2000, 1125), (2001, 1125), (2000, 1126), (2001, 1126)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render sample slides and assert size/latency")
    parser.add_argument("--deck", required=True, help="path to the .pptx")
    parser.add_argument("--pages", default="5,6,8", help="comma separated 1-based pages")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--budget-ms", type=int, default=DEFAULT_BUDGET_MS)
    parser.add_argument("--out", default="/opt/data/tmp/pptpage")
    parser.add_argument("--roots", default=None, help="override PPT_ROOTS")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    deck = Path(args.deck).expanduser()

    # config.settings 在 import 时构建，先写入 env 再 import 服务层
    os.environ["PPT_ROOTS"] = args.roots or str(deck.parent)
    os.environ["PPT_OUT_DIR"] = args.out
    os.environ.setdefault("PPT_DPI", str(args.dpi))

    from server.app.ppt import service
    from server.app.ppt.errors import PptError

    try:
        info = service.use_deck(str(deck))
    except PptError as exc:
        print(f"FAIL use_deck: {exc.to_dict()}")
        return 1

    print(
        f"deck: {info['file_name']}  slides={info['slide_count']}  size={info['size_mb']}MB"
    )

    pages = [int(part) for part in args.pages.split(",") if part.strip()]
    failures = 0
    for page in pages:
        started = time.monotonic()
        try:
            result = service.render_slide(page, dpi=args.dpi)
        except PptError as exc:
            print(f"  p{page}: FAIL {exc.to_dict()}")
            failures += 1
            continue
        elapsed = int((time.monotonic() - started) * 1000)
        size = Path(result["path"]).stat().st_size
        dims = (result["width"], result["height"])
        problems = []
        if dims not in EXPECTED:
            problems.append(f"size {dims} not in {sorted(EXPECTED)}")
        if elapsed > args.budget_ms:
            problems.append(f"took {elapsed}ms > {args.budget_ms}ms")
        if size < DEFAULT_MIN_BYTES:
            problems.append(f"png only {size}B")
        status = "OK" if not problems else "FAIL " + "; ".join(problems)
        print(
            f"  p{page}: {dims[0]}x{dims[1]} {size / 1024:.0f}KB "
            f"{elapsed}ms {result['path']} -> {status}"
        )
        failures += 1 if problems else 0

    if failures:
        print(f"FAILED: {failures} page(s)")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
