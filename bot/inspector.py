"""dump โครงสร้าง control ของหน้าต่าง ProMaxx ออกมาเป็น txt / json / png

ใช้ผลจากที่นี่ไปกรอก locator ในไฟล์ flow YAML
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from . import win
from .app import PromaxxApp
from .logging_setup import get_logger
from .shots import capture_window

log = get_logger()

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _slug(text: str, fallback: str) -> str:
    s = _SAFE.sub("_", (text or "").strip())[:40].strip("_")
    return s or fallback


def snapshot(app: PromaxxApp) -> list[dict]:
    """โครงสร้างหน้าต่าง top-level ทั้งหมดของ process"""
    if app.pid is None:
        return []
    trees = []
    for hwnd in win.top_windows(app.pid):
        if not win.is_visible(hwnd):
            continue
        left, _, right, _ = win.get_rect(hwnd)
        if right - left <= 0:
            continue
        trees.append(win.tree(hwnd))
    return trees


def _fingerprint(trees: list[dict]) -> str:
    """ลายเซ็นย่อของสถานะหน้าจอ ใช้ตรวจว่าหน้าจอเปลี่ยนหรือยัง"""
    parts = []
    for t in trees:
        for n in win.flatten(t):
            if n["visible"]:
                parts.append(f"{n['class_name']}|{n['control_id']}|{n['text']}")
    return "\n".join(parts)


def dump(app: PromaxxApp, out_dir: Path, tag: str = "snapshot",
         with_image: bool = True) -> dict:
    """เขียนไฟล์ .txt / .json / .png คืน dict สรุปสิ่งที่เขียน"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trees = snapshot(app)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = out_dir / f"{tag}_{stamp}"

    lines = [
        f"# ProMaxx Report - control tree",
        f"# เวลา  : {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"# pid   : {app.pid}",
        f"# พบหน้าต่าง top-level ที่มองเห็นได้ {len(trees)} บาน",
        "",
    ]
    for t in trees:
        lines.append("=" * 78)
        lines.append(f"WINDOW cls={t['class_name']!r} title={t['text']!r} hwnd={t['hwnd_hex']}")
        lines.append("=" * 78)
        lines.append(win.format_tree(t))
        lines.append("")
        lines.append(_suggest_locators(t))
        lines.append("")

    txt_path = base.with_suffix(".txt")
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    json_path = base.with_suffix(".json")
    json_path.write_text(
        json.dumps({"pid": app.pid, "captured_at": stamp, "windows": trees},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    images = []
    if with_image:
        for i, t in enumerate(trees):
            name = f"{base.name}_{i}_{_slug(t['text'], t['class_name'])}.png"
            p = capture_window(t["hwnd"], out_dir / name)
            if p:
                images.append(str(p))

    log.info("บันทึก control tree: %s", txt_path)
    log.info("บันทึก JSON       : %s", json_path)
    for p in images:
        log.info("บันทึกภาพ         : %s", p)

    return {"txt": str(txt_path), "json": str(json_path), "images": images,
            "windows": trees}


def _suggest_locators(tree_node: dict) -> str:
    """เสนอ locator YAML สำหรับ control ที่กดหรือกรอกได้ในหน้าต่างนี้"""
    interesting = {"Edit", "Button", "ComboBox", "Static", "ListBox",
                   win.PB_TAB_CLASS, win.PB_DATAWINDOW_CLASS}
    rows = []
    counters: dict[str, int] = {}
    for n in win.flatten(tree_node):
        cls = n["class_name"]
        if cls not in interesting:
            continue
        idx = counters.get(cls, 0)
        counters[cls] = idx + 1
        if not n["visible"]:
            continue
        cid = n["control_id"]
        if cid and cid != -1:
            loc = f'{{ class_name: "{cls}", control_id: {cid} }}'
        elif n["text"]:
            loc = f'{{ class_name: "{cls}", title: "{n["text"]}" }}'
        else:
            loc = f'{{ class_name: "{cls}", index: {idx} }}'
        rows.append(f"  # text={n['text']!r:<30} -> control: {loc}")

    if not rows:
        return "  (ไม่พบ control ที่กด/กรอกได้ในหน้าต่างนี้)"
    return "locator ที่แนะนำสำหรับใส่ใน flow YAML:\n" + "\n".join(rows)


def watch(app: PromaxxApp, out_dir: Path, interval: float = 1.0,
          duration: float = 300.0) -> None:
    """เฝ้าดู ถ้าหน้าจอเปลี่ยนก็ dump ใหม่ - ใช้ตอนไล่บันทึกขั้นตอนกดปุ่มด้วยมือ"""
    log.info("โหมด watch: จะ dump ใหม่ทุกครั้งที่หน้าจอเปลี่ยน (Ctrl+C เพื่อหยุด)")
    last = None
    seq = 0
    deadline = time.monotonic() + duration
    try:
        while time.monotonic() < deadline:
            if not app.is_running():
                log.warning("โปรแกรมถูกปิดไปแล้ว หยุดเฝ้าดู")
                return
            fp = _fingerprint(snapshot(app))
            if fp != last:
                last = fp
                dump(app, out_dir, tag=f"watch{seq:02d}")
                seq += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("หยุดโหมด watch ตามคำสั่งผู้ใช้")
    log.info("โหมด watch จบ dump ไปทั้งหมด %d ครั้ง", seq)
