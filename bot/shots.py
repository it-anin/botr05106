"""ถ่ายภาพหน้าต่างด้วย PrintWindow

ใช้ PrintWindow แทนการ grab หน้าจอ เพราะทำงานได้แม้หน้าต่างถูกบัง
(pywinauto.capture_as_image ใช้ ImageGrab ซึ่งได้ภาพดำเมื่อจอถูกล็อก)
"""

from __future__ import annotations

from ctypes import windll
from pathlib import Path

import win32con
import win32gui
import win32ui
from PIL import Image

from .logging_setup import get_logger

log = get_logger()

PW_RENDERFULLCONTENT = 0x00000002


def capture_window(hwnd: int, path: str | Path) -> Path | None:
    """บันทึกภาพหน้าต่างเป็น PNG คืน path ที่บันทึก หรือ None ถ้าทำไม่ได้"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception as exc:
        log.debug("ถ่ายภาพไม่ได้ หา rect ไม่เจอ: %s", exc)
        return None

    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None

    hwnd_dc = mfc_dc = save_dc = bmp = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bmp)

        ok = windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        if not ok:
            # PB บางหน้าต่างไม่รองรับ flag ใหม่ ลองแบบเดิม
            ok = windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 0)

        bmpinfo = bmp.GetInfo()
        bmpstr = bmp.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRX", 0, 1
        )
        img.save(path)
        if not ok:
            log.debug("PrintWindow คืนค่า 0 ภาพอาจไม่สมบูรณ์: %s", path.name)
        return path
    except Exception as exc:
        log.debug("ถ่ายภาพหน้าต่าง %s ไม่สำเร็จ: %s", hex(hwnd), exc)
        return None
    finally:
        try:
            if bmp is not None:
                win32gui.DeleteObject(bmp.GetHandle())
        except Exception:
            pass
        for dc in (save_dc, mfc_dc):
            try:
                if dc is not None:
                    dc.DeleteDC()
            except Exception:
                pass
        try:
            if hwnd_dc:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass
