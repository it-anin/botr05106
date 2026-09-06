"""เรียกตัวอัปโหลด Supabase ต่อท้าย flow ที่ export สำเร็จ

โค้ดอัปโหลดจริงคือ `upload-products.mjs` ที่วางอยู่ข้าง ๆ (โฟลเดอร์เดียวกับ .exe
เมื่อ build แล้ว หรือรากโปรเจกต์เมื่อรันด้วย python) ไฟล์นี้มีหน้าที่แค่หา node
กับ path ให้ถูก แล้วส่ง exit code กลับให้ run.py ตัดสินใจ

ทำไมไม่เขียนตรรกะอัปโหลดเป็น Python เสียเลย: .mjs ชุดนั้นมีเทส 11 ตัว ผ่านการรันจริง
และเคยจับบั๊กที่หายาก (UTF-8 BOM, quoted newline ใน CSV, DELETE ที่ไม่มี WHERE)
มาแล้ว การเขียนใหม่คือเปิดช่องให้บั๊กชุดเดิมกลับมาโดยไม่ได้อะไรเพิ่ม
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bot import logging_setup
from bot.config import ROOT, Settings

# exit code ที่ upload-products.mjs คืนมา (ตรงกับ tools\run_and_upload.ps1)
UPLOAD_OK = 0
UPLOAD_FAILED = 1
UPLOAD_SKIPPED = 2

DEFAULT_NODE = r"C:\Program Files\nodejs\node.exe"
DEFAULT_SCRIPT = "upload-products.mjs"


def resolve_node(cfg: Settings) -> str | None:
    """หา node.exe — settings.yaml ก่อน แล้ว PATH แล้วค่อยตำแหน่งมาตรฐาน"""
    configured = cfg.get("upload.node_exe")
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("node")
    if found:
        return found
    if Path(DEFAULT_NODE).exists():
        return DEFAULT_NODE
    return None


def pick_csv(outputs: list) -> str | None:
    """เลือกไฟล์ .csv ที่ flow เพิ่งสร้าง (ctx.outputs บันทึกไว้ตอน move_file/assert_file)

    ไม่เจอก็คืน None ได้ — uploader จะไปหาเองจาก CSV_CANDIDATES ของมัน
    """
    for item in reversed(outputs or []):
        path = item.get("path") if isinstance(item, dict) else str(item)
        if path and path.lower().endswith(".csv"):
            return path
    return None


def run_upload(cfg: Settings, outputs: list, *, dry_run: bool = False) -> int:
    """รัน upload-products.mjs แล้วคืน exit code ของมันตรง ๆ"""
    log = logging_setup.get_logger()

    script = ROOT / cfg.get("upload.script", DEFAULT_SCRIPT)
    if not script.exists():
        log.error("ไม่พบ %s — build ใหม่ด้วย .\\tools\\build_exe.ps1 "
                  "(สคริปต์ build ก๊อป uploader + node_modules มาไว้ข้าง exe ให้)", script)
        return UPLOAD_FAILED

    node = resolve_node(cfg)
    if not node:
        log.error("หา node.exe ไม่เจอ — ลง Node.js บนเครื่องนี้ "
                  "หรือระบุ upload.node_exe ใน settings.yaml")
        return UPLOAD_FAILED

    cmd = [node, str(script)]
    csv = pick_csv(outputs)
    if csv:
        cmd += ["--file", csv]
    else:
        log.warning("flow ไม่ได้บันทึกไฟล์ .csv ไว้ — ปล่อยให้ uploader หาเองจาก path มาตรฐาน")
    if dry_run:
        cmd.append("--dry-run")

    log.info("เริ่มอัปโหลดเข้า Supabase: %s", " ".join(cmd))
    # ปล่อย stdout/stderr ให้ไหลออกหน้าจอตรง ๆ — uploader พิมพ์สรุปเป็นภาษาไทย
    # และเขียน upload-products.log ของตัวเองไว้แล้ว ไม่ต้องดักมาพิมพ์ซ้ำ
    proc = subprocess.run(cmd)
    rc = proc.returncode

    if rc == UPLOAD_OK:
        log.info("อัปโหลดสำเร็จ")
    elif rc == UPLOAD_SKIPPED:
        log.warning("uploader ข้ามรอบนี้ (ไฟล์ไม่ได้ถูกอัปเดต) — ข้อมูลเดิมใน Supabase ยังอยู่ครบ")
    else:
        log.error("อัปโหลดไม่สำเร็จ (exit %s) — ดูรายละเอียดใน upload-products.log", rc)
    return rc
