"""เฝ้าดู dialog แปลกปลอมที่โผล่ขวางระหว่างรัน flow

กันบอทค้างข้ามคืนเพราะมี message box เด้งมาบังแล้วไม่มีใครกดปิด
กติกาตั้งได้ในไฟล์ settings.yaml หัวข้อ watchdog
"""

from __future__ import annotations

import re
import threading
import time

from . import locators, win
from .logging_setup import get_logger

log = get_logger()


class Watchdog:
    def __init__(self, cfg, app, ctx):
        self.cfg = cfg
        self.app = app
        self.ctx = ctx
        self.enabled = bool(cfg.get("watchdog.enabled", True))
        self.interval = float(cfg.get("watchdog.interval", 1.0))
        self.rules = cfg.get("watchdog.rules", []) or []
        self.ignore_res = [re.compile(p) for p in
                           (cfg.get("watchdog.ignore_title_re", []) or [])]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: set[int] = set()
        self.hits: list[dict] = []

    # ------------------------------------------------------------------

    def start(self) -> None:
        if not self.enabled or not self.rules:
            log.debug("watchdog ปิดอยู่หรือไม่มีกติกา")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="watchdog", daemon=True)
        self._thread.start()
        log.debug("เริ่ม watchdog (%d กติกา ทุก %.1fs)", len(self.rules), self.interval)

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=3)
        self._thread = None

    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan()
            except Exception as exc:
                log.debug("watchdog สะดุด: %s", exc)
            self._stop.wait(self.interval)

    def _known(self) -> set[int]:
        """หน้าต่างที่ flow รู้จักอยู่แล้ว - ห้ามไปยุ่ง"""
        return set(self.ctx.windows.values())

    def _scan(self) -> None:
        pid = self.app.pid
        if pid is None:
            return
        known = self._known()
        for hwnd in win.top_windows(pid):
            if hwnd in self._seen or hwnd in known or not win.is_visible(hwnd):
                continue
            title = win.get_text(hwnd)
            if any(r.search(title) for r in self.ignore_res):
                continue
            rule = self._match_rule(hwnd)
            if rule is None:
                continue
            self._seen.add(hwnd)
            self._handle(hwnd, title, rule)

    def _match_rule(self, hwnd: int) -> dict | None:
        for rule in self.rules:
            spec = {k: v for k, v in rule.items()
                    if k in {"class_name", "class_name_re", "title", "title_re",
                             "title_contains", "control_id", "min_width", "min_height"}}
            if not spec:
                continue
            try:
                if locators.matches(hwnd, spec):
                    return rule
            except Exception:
                continue
        return None

    def _handle(self, hwnd: int, title: str, rule: dict) -> None:
        policy = str(rule.get("policy", "log")).lower()
        name = rule.get("name", "ไม่ระบุชื่อ")
        log.warning("watchdog เจอหน้าต่างแปลกปลอม [%s] %s title=%r policy=%s",
                    name, hex(hwnd), title, policy)
        self.hits.append({"hwnd": hwnd, "title": title, "rule": name, "policy": policy})

        try:
            self.ctx.screenshot(hwnd, f"WATCHDOG_{name}")
        except Exception as exc:
            log.debug("watchdog ถ่ายภาพไม่สำเร็จ: %s", exc)

        try:
            log.warning("  โครงสร้าง: \n%s", win.format_tree(win.tree(hwnd)))
        except Exception:
            pass

        if policy == "log":
            return
        if policy == "abort":
            log.error("  watchdog สั่งหยุด - flow จะพังที่ step ถัดไป")
            return
        if policy == "dismiss":
            self._dismiss(hwnd, rule)
            return
        log.warning("  ไม่รู้จัก policy %r จึงแค่บันทึกไว้", policy)

    def _dismiss(self, hwnd: int, rule: dict) -> None:
        pattern = rule.get("button_title_re")
        if pattern:
            for child in win.child_windows(hwnd):
                if win.get_class(child) != "Button" or not win.is_visible(child):
                    continue
                if re.search(pattern, win.get_text(child)):
                    log.warning("  กดปุ่ม %r เพื่อปิด", win.get_text(child))
                    win.click_bm(child)
                    return
        log.warning("  ไม่พบปุ่มที่ตรงกติกา จึงส่ง WM_CLOSE")
        win.close_window(hwnd)
