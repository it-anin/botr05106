"""เปิด / เกาะ / ปิด promaxxreport.exe"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import psutil

from . import win
from .logging_setup import get_logger

log = get_logger()


class AppError(Exception):
    pass


class PromaxxApp:
    """จัดการ process ของ promaxxreport.exe และหาหน้าต่างของมัน"""

    def __init__(self, exe: str, work_dir: str, process_name: str,
                 start_timeout: float = 90, close_timeout: float = 20):
        self.exe = str(exe)
        self.work_dir = str(work_dir)
        self.process_name = process_name.lower()
        self.start_timeout = float(start_timeout)
        self.close_timeout = float(close_timeout)
        self.pid: int | None = None

    # ---------------- process ----------------

    def find_running(self) -> list[int]:
        """pid ทั้งหมดของโปรแกรมนี้ที่กำลังเปิดอยู่"""
        pids = []
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if (p.info["name"] or "").lower() != self.process_name:
                    continue
                # ยืนยันด้วย path เต็ม กันชื่อซ้ำจากที่อื่น
                try:
                    if os.path.normcase(p.exe()) != os.path.normcase(self.exe):
                        continue
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
                pids.append(p.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return pids

    def is_running(self) -> bool:
        return bool(self.find_running())

    def start(self) -> int:
        """เปิดโปรแกรมใหม่ แล้วรอจนมีหน้าต่างโผล่"""
        if not Path(self.exe).exists():
            raise AppError(f"ไม่พบไฟล์โปรแกรม: {self.exe}")
        if not Path(self.work_dir).is_dir():
            raise AppError(f"ไม่พบ working directory: {self.work_dir}")

        log.info("เปิดโปรแกรม: %s (cwd=%s)", self.exe, self.work_dir)
        proc = subprocess.Popen([self.exe], cwd=self.work_dir, close_fds=True)
        self.pid = proc.pid

        hwnd = self.wait_first_window()
        log.info(
            "โปรแกรมพร้อม pid=%s หน้าต่างแรก=%s cls=%r title=%r",
            self.pid, hex(hwnd), win.get_class(hwnd), win.get_text(hwnd),
        )
        return self.pid

    def attach(self) -> int:
        pids = self.find_running()
        if not pids:
            raise AppError("โปรแกรมยังไม่ได้เปิดอยู่ จึงเกาะไม่ได้")
        if len(pids) > 1:
            log.warning("พบโปรแกรมเปิดอยู่ %d ตัว จะใช้ pid=%s", len(pids), pids[0])
        self.pid = pids[0]
        log.info("เกาะโปรแกรมที่เปิดอยู่แล้ว pid=%s", self.pid)
        return self.pid

    def stop(self) -> None:
        """ปิดอย่างสุภาพก่อน (WM_CLOSE) ไม่ยอมค่อยฆ่า"""
        pids = self.find_running()
        if not pids:
            return
        for pid in pids:
            for hwnd in win.top_windows(pid):
                if win.is_visible(hwnd):
                    win.close_window(hwnd)
        deadline = time.monotonic() + self.close_timeout
        while time.monotonic() < deadline:
            if not self.find_running():
                log.info("โปรแกรมปิดเรียบร้อย")
                return
            time.sleep(0.3)

        for pid in self.find_running():
            log.warning("โปรแกรมไม่ยอมปิด สั่ง terminate pid=%s", pid)
            try:
                p = psutil.Process(pid)
                p.terminate()
                p.wait(timeout=10)
            except psutil.NoSuchProcess:
                pass
            except psutil.TimeoutExpired:
                log.warning("terminate ไม่สำเร็จ สั่ง kill pid=%s", pid)
                try:
                    psutil.Process(pid).kill()
                except psutil.NoSuchProcess:
                    pass

    def start_or_attach(self, policy: str = "attach") -> int:
        """policy: attach | restart | fail | reuse_or_start"""
        policy = (policy or "attach").lower()
        running = self.find_running()

        if policy == "restart":
            if running:
                log.info("มีโปรแกรมเปิดอยู่ %s -> ปิดก่อนแล้วเปิดใหม่", running)
                self.stop()
            return self.start()

        if policy == "fail" and running:
            raise AppError(f"โปรแกรมเปิดอยู่แล้ว (pid={running}) ตามนโยบาย fail จึงหยุด")

        if running and policy in ("attach", "reuse_or_start", "fail"):
            return self.attach()

        return self.start()

    # ---------------- หน้าต่าง ----------------

    def windows(self, visible_only: bool = True) -> list[int]:
        """หน้าต่าง top-level ทั้งหมดของ process นี้"""
        if self.pid is None:
            return []
        hs = win.top_windows(self.pid)
        if visible_only:
            hs = [h for h in hs if win.is_visible(h)]
        return hs

    def wait_first_window(self, timeout: float | None = None) -> int:
        """รอหน้าต่างที่มองเห็นได้อันแรก (คือหน้าล็อกอิน)"""
        timeout = self.start_timeout if timeout is None else timeout

        def probe():
            # หลัง Popen ตัว pid อาจยังไม่มีหน้าต่าง หรือโปรแกรมอาจ re-launch ตัวเอง
            pids = [self.pid] if self.pid else []
            pids += [p for p in self.find_running() if p not in pids]
            for pid in pids:
                if pid is None:
                    continue
                for h in win.top_windows(pid):
                    if win.is_visible(h) and win.get_rect(h)[2] > 0:
                        cls = win.get_class(h)
                        if cls in win.PB_WINDOW_CLASSES or cls == win.DIALOG_CLASS:
                            self.pid = pid
                            return h
            return None

        return win.wait_until(probe, timeout, 0.3, what="หน้าต่างแรกของโปรแกรม")

    def snapshot(self) -> list[dict]:
        """โครงสร้างหน้าต่างทั้งหมดของ process นี้ ณ ขณะนี้"""
        if self.pid is None:
            return []
        return [win.tree(h) for h in win.top_windows(self.pid)]


def from_settings(cfg) -> PromaxxApp:
    return PromaxxApp(
        exe=cfg.require("app.exe"),
        work_dir=cfg.require("app.work_dir"),
        process_name=cfg.get("app.process_name", "promaxxreport.exe"),
        start_timeout=cfg.get("app.start_timeout", 90),
        close_timeout=cfg.get("app.close_timeout", 20),
    )
