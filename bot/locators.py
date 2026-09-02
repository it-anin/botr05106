"""ค้นหาหน้าต่างและ control จาก "สเปก" ที่เขียนไว้ในไฟล์ flow YAML

สเปกเป็น mapping รองรับคีย์ต่อไปนี้ (ใส่หลายคีย์ = ต้องตรงทุกข้อ)

    class_name      ชื่อคลาสแบบตรงตัว   เช่น "pbdw125"
    class_name_re   ชื่อคลาสแบบ regex    เช่น "FNWND3125|FNWNS3125"
    title           ข้อความแบบตรงตัว
    title_re        ข้อความแบบ regex
    title_contains  ข้อความบางส่วน
    control_id      เลข id ของ control (เสถียรที่สุด)
    index           เลือกตัวที่เท่าไหร่จากผลที่ตรงทั้งหมด (เริ่มที่ 0)
    visible         true (ค่าเริ่มต้น) / false / "any"
    enabled         true / false / "any" (ค่าเริ่มต้น "any")
    min_width       กว้างอย่างน้อยกี่ pixel
    min_height      สูงอย่างน้อยกี่ pixel
    has_child       สเปกย่อย ต้องมีลูกหลานที่ตรงสเปกนี้อย่างน้อยหนึ่งตัว
"""

from __future__ import annotations

import re
from typing import Any

from . import win


class LocatorError(Exception):
    pass


_KNOWN_KEYS = {
    "class_name", "class_name_re", "title", "title_re", "title_contains",
    "control_id", "index", "visible", "enabled", "min_width", "min_height",
    "has_child",
}


def validate_spec(spec: Any, where: str = "locator") -> dict:
    if not isinstance(spec, dict):
        raise LocatorError(f"{where} ต้องเป็น mapping ไม่ใช่ {type(spec).__name__}")
    unknown = set(spec) - _KNOWN_KEYS
    if unknown:
        raise LocatorError(
            f"{where} มีคีย์ที่ไม่รู้จัก: {sorted(unknown)} "
            f"(คีย์ที่ใช้ได้: {sorted(_KNOWN_KEYS)})"
        )
    if "has_child" in spec:
        validate_spec(spec["has_child"], f"{where}.has_child")
    return spec


def _tri(value: Any, default: Any) -> Any:
    """แปลงค่า true/false/'any' - คืน None แปลว่าไม่ต้องตรวจ"""
    if value is None:
        value = default
    if isinstance(value, str) and value.lower() == "any":
        return None
    return bool(value)


def matches(hwnd: int, spec: dict) -> bool:
    if not win.exists(hwnd):
        return False

    want_visible = _tri(spec.get("visible"), True)
    if want_visible is not None and win.is_visible(hwnd) != want_visible:
        return False

    want_enabled = _tri(spec.get("enabled"), "any")
    if want_enabled is not None and win.is_enabled(hwnd) != want_enabled:
        return False

    cls = win.get_class(hwnd)
    if "class_name" in spec and cls != spec["class_name"]:
        return False
    if "class_name_re" in spec and not re.search(spec["class_name_re"], cls):
        return False

    if "control_id" in spec and win.get_ctrl_id(hwnd) != int(spec["control_id"]):
        return False

    if {"title", "title_re", "title_contains"} & set(spec):
        text = win.get_text(hwnd)
        if "title" in spec and text != spec["title"]:
            return False
        if "title_re" in spec and not re.search(spec["title_re"], text):
            return False
        if "title_contains" in spec and spec["title_contains"] not in text:
            return False

    if "min_width" in spec or "min_height" in spec:
        left, top, right, bottom = win.get_rect(hwnd)
        if right - left < int(spec.get("min_width", 0)):
            return False
        if bottom - top < int(spec.get("min_height", 0)):
            return False

    if "has_child" in spec:
        child_spec = spec["has_child"]
        if not any(matches(k, child_spec) for k in win.child_windows(hwnd)):
            return False

    return True


def _pick(candidates: list[int], spec: dict, where: str) -> int:
    if not candidates:
        raise LocatorError(f"ไม่พบ {where} ที่ตรงสเปก {spec}")
    idx = int(spec.get("index", 0))
    try:
        return candidates[idx]
    except IndexError:
        raise LocatorError(
            f"สเปก {spec} ระบุ index={idx} แต่พบที่ตรงเพียง {len(candidates)} ตัว"
        ) from None


def find_windows(pid: int, spec: dict) -> list[int]:
    """หน้าต่าง top-level ของ process ที่ตรงสเปก"""
    validate_spec(spec, "window")
    return [h for h in win.top_windows(pid) if matches(h, spec)]


def find_window(pid: int, spec: dict) -> int:
    return _pick(find_windows(pid, spec), spec, "หน้าต่าง")


def find_controls(parent: int, spec: dict) -> list[int]:
    """control ที่เป็นลูกหลานของ parent และตรงสเปก"""
    validate_spec(spec, "control")
    return [h for h in win.child_windows(parent) if matches(h, spec)]


def find_control(parent: int, spec: dict) -> int:
    return _pick(find_controls(parent, spec), spec, "control")


def describe(parent: int, limit: int = 60) -> str:
    """รายการ control ที่มีอยู่จริง - ใช้ประกอบข้อความ error ให้แก้ YAML ได้ทันที"""
    rows = []
    for h in win.child_windows(parent)[:limit]:
        flags = ("V" if win.is_visible(h) else "-") + ("E" if win.is_enabled(h) else "d")
        left, top, right, bottom = win.get_rect(h)
        rows.append(
            f"    [{flags}] class_name={win.get_class(h)!r} "
            f"control_id={win.get_ctrl_id(h)} title={win.get_text(h)!r} "
            f"size={right - left}x{bottom - top}"
        )
    if not rows:
        return "    (ไม่มี control ลูกเลย)"
    return "\n".join(rows)


def describe_windows(pid: int, limit: int = 30) -> str:
    """รายการหน้าต่างที่มีตัวตนจริง - ตัดพวกขนาด 0x0 ที่ PB สร้างค้างไว้ออก"""
    rows = []
    hidden = 0
    for h in win.top_windows(pid):
        left, top, right, bottom = win.get_rect(h)
        width, height = right - left, bottom - top
        if not win.is_visible(h) or width <= 0 or height <= 0:
            hidden += 1
            continue
        rows.append(
            f"    [V] class_name={win.get_class(h)!r} "
            f"title={win.get_text(h)!r} size={width}x{height}"
        )
        if len(rows) >= limit:
            break
    if hidden:
        rows.append(f"    (ซ่อนอยู่/ไม่มีขนาดอีก {hidden} บาน - ไม่แสดง)")
    if not rows:
        return "    (ไม่มีหน้าต่างเลย)"
    return "\n".join(rows)
