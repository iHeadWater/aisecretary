"""单页真实渲染：soffice PageRange 导单页 PDF → pdftoppm 出 PNG。

进程模型：每次渲染起一个 soffice 子进程，放在独立 session 里，超时直接 kill 整个
进程组，避免残留 ``soffice.bin`` 把内存和 profile 锁住。
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
from server.app.ppt.errors import PptError

SOFFICE = "soffice"
PDFTOPPM = "pdftoppm"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_ATTEMPTS = 2


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


def _convert_page(deck: Path, page: int, work: Path, timeout: float) -> Path:
    """用 PageRange 只导出第 page 页，避免整本转换把内存打爆。"""
    pdf_dir = work / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    profile = work / "lo-profile"

    env = os.environ.copy()
    env["HOME"] = str(work)
    env.setdefault("SAL_USE_VCLPLUGIN", "svp")

    target = (
        'pdf:impress_pdf_Export:'
        '{"PageRange":{"type":"string","value":"%d"}}' % page
    )
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
        str(deck),
    ]
    code, _stdout, stderr = _run(cmd, timeout, env=env)

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if code != 0 or len(pdfs) != 1 or pdfs[0].stat().st_size == 0:
        raise _RenderAttemptError(
            f"soffice 没有产出有效 PDF（exit={code}）{stderr.strip()[-400:]}"
        )
    return pdfs[0]


def _pdf_to_png(pdf: Path, dpi: int, work: Path, timeout: float) -> Path:
    prefix = work / "page"
    cmd = [
        PDFTOPPM,
        "-png",
        "-r",
        str(dpi),
        "-f",
        "1",
        "-l",
        "1",
        str(pdf),
        str(prefix),
    ]
    code, _stdout, stderr = _run(cmd, timeout)
    pngs = sorted(work.glob("page*.png"))
    if code != 0 or not pngs:
        raise _RenderAttemptError(
            f"pdftoppm 没有产出 PNG（exit={code}）{stderr.strip()[-400:]}"
        )
    return pngs[0]


def prune_cache(out_dir: Path, max_age_days: int | None = None) -> int:
    """删除超过保留期的缓存 PNG，返回删除数量。<=0 表示不清理。"""
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
    return removed


def render_slide_png(deck: Path, page: int, dpi: int, slide_count: int) -> dict[str, Any]:
    out_dir = settings.ppt_out_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o755)
    # 顺手清理过期缓存，避免 ~/.hermes/tmp/pptpage 无限增长
    prune_cache(out_dir)

    destination = out_dir / f"{_safe_stem(deck)}-{deck_key(deck)}-p{page}-{dpi}.png"
    started = time.monotonic()

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

    if not tools_available():
        raise PptError(
            "render_unavailable",
            "容器内缺少 soffice 或 pdftoppm，无法渲染（请使用带 LibreOffice 的镜像）",
        )

    deadline = started + settings.ppt_timeout
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if time.monotonic() >= deadline:
            raise PptError(
                "render_timeout", f"渲染超时（>{settings.ppt_timeout}s）：第 {page} 页"
            )
        try:
            # 临时目录放在输出目录内：OS 层面同分区，os.replace 才是原子的
            with tempfile.TemporaryDirectory(prefix=".render-", dir=out_dir) as tmp:
                work = Path(tmp)
                pdf = _convert_page(deck, page, work, deadline - time.monotonic())
                png = _pdf_to_png(pdf, dpi, work, deadline - time.monotonic())
                width, height = png_size(png)
                png.chmod(0o644)
                os.replace(png, destination)
            break
        except subprocess.TimeoutExpired as exc:
            raise PptError(
                "render_timeout", f"渲染超时（>{settings.ppt_timeout}s）：第 {page} 页"
            ) from exc
        except _RenderAttemptError as exc:
            last_error = str(exc)
            if attempt == MAX_ATTEMPTS:
                raise PptError("render_failed", f"渲染失败：{last_error}") from exc
        except OSError as exc:
            raise PptError("render_failed", f"渲染输出写入失败：{exc}") from exc

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return {
        "path": str(destination),
        "page": page,
        "slide_count": slide_count,
        "dpi": dpi,
        "width": width,
        "height": height,
        "cached": False,
        "ms": elapsed_ms,
    }
