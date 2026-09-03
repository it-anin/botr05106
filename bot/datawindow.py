"""ทำงานกับ DataWindow ของ PowerBuilder (class pbdw125)

DataWindow วาดทุกอย่างเอง - ช่องกรอก ปุ่ม ตาราง ล้วนไม่ใช่ control จริง
จึงหา handle รายช่องไม่ได้ วิธีที่ใช้ได้จริงคือ

  1. คลิกด้วย message ลงบนพิกัดของช่องนั้นใน DataWindow
  2. PowerBuilder จะเลื่อน "in-place editor" (control class Edit ที่ซ่อนอยู่)
     มาวางทับช่องนั้นแล้วทำให้มองเห็น
  3. เขียนค่าลง Edit ตัวนั้นด้วย WM_SETTEXT แล้วกด TAB/ENTER เพื่อ commit

ยืนยันแล้วกับหน้าล็อกอินของ ProMaxx Report: ทั้งกระบวนการใช้ message ล้วน
จึงทำงานได้แม้หน้าจอถูกล็อก
"""

from __future__ import annotations

from typing import Any

from . import win
from .logging_setup import get_logger

log = get_logger()


class DataWindowError(Exception):
    pass


_AT_KEYS = {"x", "y", "x_pct", "y_pct"}


def resolve_point(dw_hwnd: int, at: dict) -> tuple[int, int]:
    """แปลงสเปกตำแหน่งเป็นพิกัด client ของ DataWindow

    รองรับพิกเซลตรง ๆ (x, y) และสัดส่วนของขนาด DataWindow (x_pct, y_pct)
    ใช้สัดส่วนจะทนต่อการเปลี่ยนขนาดหน้าต่างมากกว่า
    """
    if not isinstance(at, dict):
        raise DataWindowError(f"'at' ต้องเป็น mapping ไม่ใช่ {type(at).__name__}")
    unknown = set(at) - _AT_KEYS
    if unknown:
        raise DataWindowError(f"'at' มีคีย์ที่ไม่รู้จัก: {sorted(unknown)}")

    width, height = win.get_client_size(dw_hwnd)
    if width <= 0 or height <= 0:
        raise DataWindowError(f"DataWindow {hex(dw_hwnd)} ไม่มีขนาด (ถูกซ่อนอยู่?)")

    if "x" in at:
        x = int(at["x"])
    elif "x_pct" in at:
        x = int(round(float(at["x_pct"]) * width))
    else:
        x = width // 2

    if "y" in at:
        y = int(at["y"])
    elif "y_pct" in at:
        y = int(round(float(at["y_pct"]) * height))
    else:
        y = height // 2

    if not (0 <= x < width and 0 <= y < height):
        raise DataWindowError(
            f"ตำแหน่ง ({x},{y}) อยู่นอก DataWindow ที่มีขนาด {width}x{height}"
        )
    return x, y


def edits(dw_hwnd: int) -> list[int]:
    """in-place editor ทุกตัวของ DataWindow นี้"""
    return [h for h in win.child_windows(dw_hwnd)
            if win.get_class(h) == "Edit"]


def live_edit(dw_hwnd: int, control_id: int | None = None) -> int | None:
    """in-place editor ที่กำลังใช้งานอยู่ (ตัวที่มองเห็นได้และมีขนาดจริง)"""
    for h in edits(dw_hwnd):
        if not win.is_visible(h):
            continue
        left, top, right, bottom = win.get_rect(h)
        if right - left <= 0 or bottom - top <= 0:
            continue
        if control_id is not None and win.get_ctrl_id(h) != int(control_id):
            continue
        return h
    return None


def click(dw_hwnd: int, at: dict) -> tuple[int, int]:
    """คลิกด้วย message ที่ตำแหน่งในสเปก คืนพิกัด client ที่คลิกจริง"""
    x, y = resolve_point(dw_hwnd, at)
    log.debug("คลิก DataWindow %s ที่ client (%d,%d)", hex(dw_hwnd), x, y)
    win.click_client(dw_hwnd, x, y)
    return x, y


def focus_cell(dw_hwnd: int, at: dict, *, expect_edit: int | None = None,
               timeout: float = 5.0, interval: float = 0.15) -> int:
    """คลิกช่องหนึ่งแล้วรอจน in-place editor โผล่ คืน handle ของ editor นั้น"""
    x, y = click(dw_hwnd, at)
    try:
        return win.wait_until(
            lambda: live_edit(dw_hwnd, expect_edit),
            timeout, interval,
            what=(f"ช่องกรอกของ DataWindow ที่ตำแหน่ง ({x},{y})"
                  + (f" control_id={expect_edit}" if expect_edit is not None else "")),
        )
    except win.TimeoutExpired as exc:
        raise DataWindowError(
            f"{exc}\n"
            f"  คลิกที่ client ({x},{y}) ของ DataWindow {hex(dw_hwnd)} "
            f"ขนาด {win.get_client_size(dw_hwnd)} แล้วไม่มีช่องกรอกโผล่\n"
            f"  ช่องกรอกที่มีอยู่: "
            + ", ".join(
                f"id={win.get_ctrl_id(h)} vis={win.is_visible(h)} rect={win.get_rect(h)}"
                for h in edits(dw_hwnd)
            )
            + "\n  แก้ค่า at ในไฟล์ flow ให้ตรงตำแหน่งช่องจริง "
              "(ดูภาพใน logs/inspect ประกอบ)"
        ) from exc


def write_cell(edit_hwnd: int, value: str, *, method: str = "settext",
               clear_first: bool = True) -> None:
    """เขียนค่าลง in-place editor

    method:
      settext - WM_SETTEXT ทีเดียว (เร็ว ใช้ได้กับหน้าล็อกอิน ProMaxx)
      chars   - WM_CHAR ทีละตัว สำหรับช่องที่ PB ตรวจค่าราย keystroke
    """
    method = (method or "settext").lower()
    if method == "settext":
        if not win.set_text(edit_hwnd, value):
            raise DataWindowError(
                f"WM_SETTEXT ไปยัง {hex(edit_hwnd)} ไม่สำเร็จ "
                f"(โปรแกรมไม่ตอบสนอง) ลองใช้ method: chars"
            )
    elif method == "chars":
        if clear_first:
            win.clear_text(edit_hwnd)
        win.send_chars(edit_hwnd, value)
    else:
        raise DataWindowError(f"ไม่รู้จัก method {method!r} (ใช้ settext หรือ chars)")


def read_cell(edit_hwnd: int) -> str:
    """อ่านค่าใน in-place editor (ช่องรหัสผ่านจะคืนค่าว่างเสมอตามที่วินโดวส์บังคับ)"""
    return win.get_text(edit_hwnd)


def is_password_edit(edit_hwnd: int) -> bool:
    """ตรวจว่าเป็นช่องรหัสผ่านไหม (อ่านค่ากลับไม่ได้เป็นเรื่องปกติ)"""
    import win32con
    import win32gui

    ES_PASSWORD = 0x0020
    try:
        style = win32gui.GetWindowLong(edit_hwnd, win32con.GWL_STYLE)
        return bool(style & ES_PASSWORD)
    except Exception:
        return False
