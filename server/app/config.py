from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_path: Path = Path.home() / ".myagentdata" / "aisecretary" / "transactions.sqlite"

    # --- PPT 能力 ---
    # 逗号分隔的允许根目录。deck 路径 resolve() 后必须落在其中之一。
    ppt_roots: str = "/opt/data/tmp/xdsh"
    # 渲染输出目录（必须以 Hermes 视角的同一绝对路径挂进两个容器）
    ppt_out_dir: Path = Path("/opt/data/tmp/pptpage")
    ppt_dpi: int = 150
    # 单页渲染总预算，秒；必须小于 Hermes MCP 客户端的 timeout(120s)
    ppt_timeout: int = 60
    # 缓存 PNG 的保留天数；<=0 表示不自动清理
    ppt_cache_max_age_days: int = 7
    ppt_max_slides_outline: int = 200

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    def model_post_init(self, __context) -> None:
        # Expand ~ in case the env var uses shell-style home shorthand
        self.database_path = self.database_path.expanduser().resolve()
        self.ppt_out_dir = self.ppt_out_dir.expanduser()

    @property
    def ppt_root_paths(self) -> list[Path]:
        """解析 PPT_ROOTS，每次访问时展开，方便测试覆写 settings.ppt_roots。"""
        roots: list[Path] = []
        for raw in self.ppt_roots.split(","):
            raw = raw.strip()
            if raw:
                roots.append(Path(raw).expanduser().resolve())
        return roots


settings = Settings()
