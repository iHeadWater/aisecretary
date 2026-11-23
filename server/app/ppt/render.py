"""单页/多页真实渲染：切片 pptx → PDF → PNG。

进程模型：每次渲染起一个 soffice 子进程，放在独立 session 里，超时直接 kill 整个
进程组，避免残留 ``soffice.bin`` 把内存和 profile 锁住。

为什么先切片：LibreOffice 渲染任意一页都会把整本 deck 载入。实测 158MB / 64 页的
deck，整本导单页峰值 1.3–2.0GB、9–11 秒；裁成只含目标页的 0.8MB 切片后峰值
236MB、0.6 秒，PDF 内容与原 deck 等价（见 :mod:`server.app.ppt.slice`）。

批量策略：一次请求里的连续页合成一个切片、只起一次 soffice、一次 pdftoppm 出多张。
LO 启动成本约 0.45s，按页重复启动是纯浪费；但切片也不能太大 —— 页数越多内存越高
（8 页 318MB、32 页 528MB），所以上限由 ``PPT_BATCH_MAX`` 控制。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from server.app.config import settings
from server.app.ppt import slice as slice_builder
from server.app.ppt.errors import PptError

SOFFICE = "soffice"
PDFTOPPM = "pdftoppm"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_ATTEMPTS = 2
SLICE_DIR = ".slices"


class _RenderAttemptError(Exception):
    """单次渲染尝试失败，允许换新 profile 重试。"""


def tools_available() -> bool:
    return shutil.which(SOFFICE) is not None and shutil.which(PDFTOPPM) is not None


def deck_key(deck: Path) -> str:
    """缓存 key：路径 + mtime + size，deck 被覆盖后自然失效。"""
    stat = deck.stat()
    raw = f"{deck}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _safe_stem(deck: Path) -> str:
    stem = re.sub(r"[^\w.-]+", "-", deck.stem).strip("-._")
    return (stem or "deck")[:60]


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        head = handle.read(24)
    if len(head) < 24 or head[:8] != PNG_MAGIC:
        raise PptError("render_failed", "渲染输出不是有效 PNG")
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def _out_dir() -> Path:
    out_dir = settings.ppt_out_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o755)
    return out_dir


def png_path(deck: Path, page: int, dpi: int) -> Path:
    """某页 PNG 的最终路径（也是缓存 key）。"""
    return _out_dir() / f"{_safe_stem(deck)}-{deck_key(deck)}-p{page}-{dpi}.png"


def _slice_key(pages: list[int]) -> str:
    if len(pages) == 1:
        return f"p{pages[0]}"
    return f"p{pages[0]}-{pages[-1]}"


def _slice_path(deck: Path, pages: list[int]) -> Path:
    return _out_dir() / SLICE_DIR / deck_key(deck) / f"{_slice_key(pages)}.pptx"


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return


def _run(
    cmd: list[str], timeout: float, env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=env,
    )
    try:
        stdout, stderr = process.communicate(timeout=max(1.0, timeout))
    except subprocess.TimeoutExpired:
        _kill_group(process)
        raise
    return process.returncode, stdout or "", stderr or ""


def _convert(
    source: Path, page_range: str | None, work: Path, timeout: float
) -> Path:
    """把 pptx 导出 PDF；``page_range`` 为空表示导出全部页。"""
    pdf_dir = work / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    profile = work / "lo-profile"

    env = os.environ.copy()
    env["HOME"] = str(work)
    env.setdefault("SAL_USE_VCLPLUGIN", "svp")

    target = "pdf:impress_pdf_Export"
    if page_range:
        target += ':{"PageRange":{"type":"string","value":"%s"}}' % page_range

    cmd = [
        SOFFICE,
        "--headless",
        "--norestore",
        "--nolockcheck",
        f"-env:UserInstallation={profile.as_uri()}",
        "--convert-to",
        target,
        "--outdir",
        str(pdf_dir),
        str(source),
    ]
    code, _stdout, stderr = _run(cmd, timeout, env=env)

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if code != 0 or len(pdfs) != 1 or pdfs[0].stat().st_size == 0:
        raise _RenderAttemptError(
            f"soffice 没有产出有效 PDF（exit={code}）{stderr.strip()[-400:]}"
        )
    return pdfs[0]


def _pdf_to_pngs(pdf: Path, dpi: int, count: int, work: Path, timeout: float) -> list[Path]:
    prefix = work / "page"
    cmd = [
        PDFTOPPM,
        "-png",
        "-r",
        str(dpi),
        "-f",
        "1",
        "-l",
        str(count),
        str(pdf),
        str(prefix),
    ]
    code, _stdout, stderr = _run(cmd, timeout)
    pngs = sorted(work.glob("page*.png"))
    if code != 0 or len(pngs) != count:
        raise _RenderAttemptError(
            f"pdftoppm 产出 {len(pngs)}/{count} 张 PNG（exit={code}）{stderr.strip()[-400:]}"
        )
    return pngs


def prune_cache(out_dir: Path, max_age_days: int | None = None) -> int:
    """删除超过保留期的缓存 PNG 与切片，返回删除数量。<=0 表示不清理。"""
    days = settings.ppt_cache_max_age_days if max_age_days is None else max_age_days
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for item in out_dir.glob("*.png"):
        try:
            if item.stat().st_mtime < cutoff:
                item.unlink()
                removed += 1
        except OSError:
            continue
    slices_root = out_dir / SLICE_DIR
    if slices_root.is_dir():
        for deck_dir in slices_root.iterdir():
            for item in deck_dir.glob("*.pptx"):
                try:
                    if item.stat().st_mtime < cutoff:
                        item.unlink()
                        removed += 1
                except OSError:
                    continue
    return removed


def _ensure_slice(deck: Path, pages: list[int]) -> Path:
    destination = _slice_path(deck, pages)
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    return slice_builder.build_slice(deck, pages, destination)


def render_pages_png(
    deck: Path, pages: list[int], dpi: int, slide_count: int
) -> list[dict[str, Any]]:
    """把一组（连续的）页渲染成 PNG，返回与 ``pages`` 等长的结果列表。"""
    if not pages:
        return []

    out_dir = _out_dir()
    # 顺手清理过期缓存，避免输出目录无限增长
    prune_cache(out_dir)

    if not tools_available():
        raise PptError(
            "render_unavailable",
            "容器内缺少 soffice 或 pdftoppm，无法渲染（请使用带 LibreOffice 的镜像）",
        )

    started = time.monotonic()
    deadline = started + settings.ppt_timeout
    last_error = ""
    results: dict[int, dict[str, Any]] = {}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if time.monotonic() >= deadline:
            raise PptError(
                "render_timeout", f"渲染超时（>{settings.ppt_timeout}s）"
            )
        try:
            # 临时目录放在输出目录内：OS 层面同分区，os.replace 才是原子的
            with tempfile.TemporaryDirectory(prefix=".render-", dir=out_dir) as tmp:
                work = Path(tmp)
                source = deck
                page_range: str | None = f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0])
                if settings.ppt_slice_enabled:
                    try:
                        source = _ensure_slice(deck, pages)
                        page_range = None  # 切片里就只有这些页
                    except PptError:
                        # 切片失败不能阻断渲染：回退到整本 deck + PageRange
                        source, page_range = deck, page_range

                pdf = _convert(source, page_range, work, deadline - time.monotonic())
                pngs = _pdf_to_pngs(
                    pdf, dpi, len(pages), work, deadline - time.monotonic()
                )
                # 必须在临时目录销毁前搬到最终位置
                for page, png in zip(pages, pngs):
                    destination = png_path(deck, page, dpi)
                    width, height = png_size(png)
                    png.chmod(0o644)
                    os.replace(png, destination)
                    results[page] = {
                        "path": str(destination),
                        "page": page,
                        "slide_count": slide_count,
                        "dpi": dpi,
                        "width": width,
                        "height": height,
                        "cached": False,
                    }
            break
        except subprocess.TimeoutExpired as exc:
            raise PptError(
                "render_timeout", f"渲染超时（>{settings.ppt_timeout}s）"
            ) from exc
        except _RenderAttemptError as exc:
            last_error = str(exc)
            if attempt == MAX_ATTEMPTS:
                raise PptError("render_failed", f"渲染失败：{last_error}") from exc
        except OSError as exc:
            raise PptError("render_failed", f"渲染输出写入失败：{exc}") from exc

    elapsed_ms = int((time.monotonic() - started) * 1000)
    ordered: list[dict[str, Any]] = []
    for page in pages:
        item = results.get(page)
        if item is None:  # pragma: no cover - 正常路径不会走到
            raise PptError("render_failed", f"第 {page} 页没有产出 PNG")
        item["ms"] = elapsed_ms
        ordered.append(item)
    return ordered


def render_slide_png(deck: Path, page: int, dpi: int, slide_count: int) -> dict[str, Any]:
    """单页渲染（保留给单页入口与测试使用）。"""
    destination = png_path(deck, page, dpi)
    if destination.is_file() and destination.stat().st_size > 0:
        width, height = png_size(destination)
        return {
            "path": str(destination),
            "page": page,
            "slide_count": slide_count,
            "dpi": dpi,
            "width": width,
            "height": height,
            "cached": True,
            "ms": 0,
        }
    return render_pages_png(deck, [page], dpi, slide_count)[0]