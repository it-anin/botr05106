"""สถานะที่ส่งต่อระหว่าง step ของ flow"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import locators, win
from .app import PromaxxApp
from .config import Settings
from .logging_setup import get_logger
from .shots import capture_window

log = get_logger()


class StepError(Exception):
    """ข้อผิดพลาดที่อธิบายได้ว่าเกิดที่ step ไหนและควรแก้อะไร"""


@dataclass
class Context:
    cfg: Settings
    app: PromaxxApp
    dry_run: bool = False
    windows: dict[str, int] = field(default_factory=dict)
    # สิ่งที่ตรวจไม่ผ่านตอน dry-run - ไม่หยุด flow แต่ทำให้ exit code ไม่เป็นศูนย์
    dry_run_issues: list[str] = field(default_factory=list)
    # ไฟล์ที่ flow ผลิตออกมาได้ - เขียนลง logs/last_run.json ให้ปลายทางเช็คได้
    outputs: list[dict] = field(default_factory=list)
    flow_name: str = ""
    step_index: int = 0
    step_name: str = ""
    depth: int = 0

    # ------------------------------------------------------------------ util

    @property
    def screenshot_dir(self) -> Path:
        return self.cfg.resolve_path("paths.screenshots", "screenshots")

    @property
    def default_timeout(self) -> float:
        return float(self.cfg.get("runner.default_timeout", 30))

    @property
    def poll_interval(self) -> float:
        return float(self.cfg.get("runner.poll_interval", 0.25))

    def require_pid(self) -> int:
        if self.app.pid is None:
            raise StepError(
                "ยังไม่ได้เปิด/เกาะโปรแกรม - ใส่ step 'launch_app' ไว้เป็นขั้นแรกของ flow"
            )
        return self.app.pid

    # -------------------------------------------------------------- หน้าต่าง

    def resolve_window(self, ref: Any, *, timeout: float | None = None) -> int:
        """แปลง window: ในไฟล์ YAML เป็น hwnd

        ref เป็นได้ 2 แบบ
          - string  : ชื่อที่ตั้งไว้ก่อนหน้าด้วย 'as:'
          - mapping : สเปกค้นหา (จะรอจนเจอตาม timeout)
        ถ้าไม่ระบุเลย จะใช้หน้าต่างหลักของโปรแกรมที่มองเห็นอยู่
        """
        pid = self.require_pid()

        if ref is None:
            candidates = [h for h in win.top_windows(pid) if win.is_visible(h)]
            if not candidates:
                raise StepError("ไม่พบหน้าต่างที่มองเห็นได้ของโปรแกรมเลย")
            return candidates[0]

        if isinstance(ref, str):
            if ref not in self.windows:
                raise StepError(
                    f"ยังไม่มีหน้าต่างชื่อ {ref!r} - ต้องมี step ก่อนหน้าที่ใช้ 'as: {ref}'\n"
                    f"  ชื่อที่มีแล้ว: {sorted(self.windows) or '(ยังไม่มี)'}"
                )
            hwnd = self.windows[ref]
            if not win.exists(hwnd):
                raise StepError(
                    f"หน้าต่างชื่อ {ref!r} ({hex(hwnd)}) ถูกปิดไปแล้ว "
                    f"ต้องหาใหม่ด้วย wait_window"
                )
            return hwnd

        if isinstance(ref, dict):
            timeout = self.default_timeout if timeout is None else timeout
            try:
                return win.wait_until(
                    lambda: (locators.find_windows(pid, ref) or [None])[0],
                    timeout, self.poll_interval,
                    what=f"หน้าต่างที่ตรงสเปก {ref}",
                )
            except win.TimeoutExpired as exc:
                raise StepError(
                    f"{exc}\n  หน้าต่างที่มีอยู่จริงตอนนี้:\n"
                    f"{locators.describe_windows(pid)}"
                ) from exc

        raise StepError(f"'window' ต้องเป็นชื่อหรือ mapping ไม่ใช่ {type(ref).__name__}")

    def resolve_control(self, parent: int, spec: Any,
                        *, timeout: float | None = None, key: str = "control") -> int:
        """แปลง control: ในไฟล์ YAML เป็น hwnd (รอจนเจอตาม timeout)"""
        if not isinstance(spec, dict):
            raise StepError(
                f"'{key}' ต้องเป็น mapping ไม่ใช่ {type(spec).__name__}"
            )
        timeout = self.default_timeout if timeout is None else timeout
        try:
            return win.wait_until(
                lambda: (locators.find_controls(parent, spec) or [None])[0],
                timeout, self.poll_interval,
                what=f"control ที่ตรงสเปก {spec}",
            )
        except win.TimeoutExpired as exc:
            raise StepError(
                f"{exc}\n  control ที่มีอยู่จริงในหน้าต่าง {hex(parent)}:\n"
                f"{locators.describe(parent)}"
            ) from exc

    # ------------------------------------------------------------------ ภาพ

    def screenshot(self, hwnd: int, name: str) -> Path | None:
        stamp = datetime.now().strftime("%H%M%S")
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:50]
        filename = f"{self.flow_name}_{self.step_index:02d}_{safe}_{stamp}.png"
        path = capture_window(hwnd, self.screenshot_dir / filename)
        if path:
            log.info("บันทึกภาพ: %s", path)
        return path

    def describe_step(self) -> str:
        base = f"[{self.flow_name} #{self.step_index}]"
        return f"{base} {self.step_name}" if self.step_name else base
