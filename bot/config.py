"""โหลด settings.yaml + .env และขยายตัวแปร ${VAR} ในไฟล์ YAML"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    pass


def load_env() -> None:
    """อ่าน .env เข้า os.environ (ไม่ทับค่าที่ตั้งไว้แล้วใน environment)

    พร้อมเติมตัวแปรวันเวลาไว้ใช้ตั้งชื่อไฟล์ใน flow เช่น ${BOT_DATE}
    ตั้งชื่อขึ้นต้นด้วย BOT_ กันชนกับตัวแปรจริงของระบบ
    """
    load_dotenv(ROOT / ".env", override=False)
    now = datetime.now()
    os.environ["BOT_DATE"] = now.strftime("%Y%m%d")
    os.environ["BOT_TIME"] = now.strftime("%H%M%S")
    os.environ["BOT_DATETIME"] = now.strftime("%Y%m%d_%H%M%S")


def expand_vars(obj: Any, *, strict: bool = True) -> Any:
    """แทน ${VAR} ด้วยค่าจาก environment แบบ recursive ทั้ง dict / list / str"""
    if isinstance(obj, dict):
        return {k: expand_vars(v, strict=strict) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_vars(v, strict=strict) for v in obj]
    if isinstance(obj, str):

        def sub(m: re.Match) -> str:
            name = m.group(1)
            val = os.environ.get(name)
            if val is None:
                if strict:
                    raise ConfigError(
                        f"ไม่พบตัวแปร ${{{name}}} ใน environment หรือไฟล์ .env"
                    )
                return m.group(0)
            return val

        return _VAR_RE.sub(sub, obj)
    return obj


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"ไม่พบไฟล์ {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} ต้องเป็น mapping ที่ระดับบนสุด")
    return data


class Settings:
    """ห่อ settings.yaml ให้เรียกแบบ dotted path ได้: cfg.get('app.exe')"""

    def __init__(self, data: dict, path: Path):
        self.data = data
        self.path = path

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Settings":
        load_env()
        p = Path(path) if path else ROOT / "settings.yaml"
        # settings.yaml ไม่ควรมีความลับ จึงไม่บังคับว่าตัวแปรต้องมีจริง
        return cls(expand_vars(_read_yaml(p), strict=False), p)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def require(self, dotted: str) -> Any:
        val = self.get(dotted, None)
        if val is None:
            raise ConfigError(f"settings.yaml ขาดค่า '{dotted}'")
        return val

    def resolve_path(self, dotted: str, default: str) -> Path:
        """คืน path ที่อ้างอิงจากรากโปรเจกต์เสมอ และสร้างโฟลเดอร์ให้ด้วย"""
        raw = self.get(dotted, default)
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    def secret_values(self) -> list[str]:
        """ค่าที่ต้องปกปิดใน log"""
        out = []
        for name in self.get("logging.mask_env", []) or []:
            val = os.environ.get(name)
            if val:
                out.append(val)
        return out


def load_flow(path: Path | str) -> dict:
    """อ่านไฟล์ flow YAML แล้วขยาย ${VAR} แบบ strict (รหัสผ่านต้องมีจริง)"""
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    data = _read_yaml(p)
    data = expand_vars(data, strict=True)
    data.setdefault("name", p.stem)
    data["_path"] = str(p)
    return data
