"""PPT 能力：单页真实渲染 + 内容解读。"""

from server.app.ppt.errors import PptError
from server.app.ppt.service import get_deck, get_slide, outline, render_slide, use_deck

__all__ = [
    "PptError",
    "get_deck",
    "get_slide",
    "outline",
    "render_slide",
    "use_deck",
]
