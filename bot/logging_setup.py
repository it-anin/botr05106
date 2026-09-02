"""ตั้งค่า logging: ไฟล์หมุนเวียน + console ที่รองรับภาษาไทย + ปกปิดรหัสผ่าน"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "botr"


class SecretFilter(logging.Filter):
    """แทนค่าความลับที่หลุดเข้ามาใน log ด้วย ***"""

    def __init__(self, secrets: list[str]):
        super().__init__()
        # เรียงจากยาวไปสั้น กันกรณีความลับซ้อนกัน
        self.secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.secrets:
            return True
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = msg
        for s in self.secrets:
            redacted = redacted.replace(s, "***")
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def setup(
    log_dir: Path,
    *,
    level: str = "INFO",
    secrets: list[str] | None = None,
    max_bytes: int = 2_000_000,
    backup_count: int = 10,
    filename: str = "bot.log",
) -> logging.Logger:
    # คอนโซล Windows เป็น cp874 จะพังกับสัญลักษณ์บางตัว - บังคับ utf-8 แบบไม่ล้ม
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        log_dir / filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if secrets:
        f = SecretFilter(secrets)
        for h in logger.handlers:
            h.addFilter(f)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
