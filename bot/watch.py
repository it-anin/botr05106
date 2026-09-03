"""ตรวจว่าการกดมีผลจริงด้วยการเทียบภาพก่อน-หลัง

PowerBuilder ไม่ตอบอะไรกลับมาเมื่อคลิกพลาดเป้าหรือปุ่มไม่ทำงาน บอทจะเงียบแล้ว
ทำ step ต่อไปทั้งที่หน้าจอไม่ขยับ ซึ่งอันตรายมากตอนรันแบบไม่มีคนเฝ้า
การเทียบภาพจึงเป็นวิธีเดียวที่รู้ได้ว่าหน้าจอเปลี่ยนจริง

ใช้ร่วมกันทั้ง action click (ปุ่มจริง) และ dw_click (พิกัดใน DataWindow)
"""

from __future__ import annotations

import time

from PIL import ImageChops

from .logging_setup import get_logger
from .shots import capture_image, is_blank

log = get_logger()

REGION_KEYS = {"left", "top", "right", "bottom"}

# เกณฑ์ขั้นต่ำของจำนวน pixel ที่ต้องเปลี่ยนถึงจะนับว่าการกดมีผล
# ตั้งไว้เผื่อ "สัญญาณรบกวน" ที่ไม่ได้เกิดจากการกด เช่นตัวกะพริบ (caret) ในช่องกรอก
# ซึ่งกินพื้นที่ราวร้อย pixel - การเปลี่ยนหน้าจอจริงกินหลักพันถึงหลักล้าน
DEFAULT_MIN_CHANGED_PIXELS = 200


class ChangeNotDetected(Exception):
    """กดไปแล้วแต่หน้าจอไม่เปลี่ยน - แปลว่าการกดไม่มีผล"""


class RegionError(Exception):
    pass


def crop(img, region: dict | None):
    """ตัดเฉพาะพื้นที่ที่สนใจ

    พิกัดนับจากมุมบนซ้ายของ "กรอบหน้าต่าง" ของสิ่งที่ถ่าย (GetWindowRect)
    ไม่ใช่ client area - สำหรับ control ลูกที่ไม่มีขอบสองค่านี้เท่ากัน
    แต่สำหรับหน้าต่างหลักจะต่างกันตามความหนาของขอบหน้าต่าง
    """
    if not region:
        return img
    unknown = set(region) - REGION_KEYS
    if unknown:
        raise RegionError(
            f"'change_region' มีคีย์ที่ไม่รู้จัก: {sorted(unknown)} "
            f"(ใช้ได้: {sorted(REGION_KEYS)})"
        )
    width, height = img.size
    left = max(0, int(region.get("left", 0)))
    top = max(0, int(region.get("top", 0)))
    right = min(width, int(region.get("right", width)))
    bottom = min(height, int(region.get("bottom", height)))
    if right <= left or bottom <= top:
        raise RegionError(
            f"'change_region' {region} ไม่เหลือพื้นที่ให้เทียบ "
            f"(ภาพที่ถ่ายได้ขนาด {width}x{height})"
        )
    return img.crop((left, top, right, bottom))


def diff_stats(before, after) -> tuple[int, tuple | None]:
    """คืน (จำนวน pixel ที่ต่างกัน, กรอบสี่เหลี่ยมที่ครอบบริเวณที่ต่าง)"""
    d = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
    bbox = d.getbbox()
    if bbox is None:
        return 0, None
    return sum(d.convert("L").histogram()[1:]), bbox


def stable_image(hwnd: int, interval: float = 0.15, attempts: int = 6):
    """ถ่ายภาพจนได้สองครั้งติดกันที่เหมือนกัน

    ใช้ทำภาพตั้งต้นก่อนกด ถ้าถ่ายตอนหน้าจอกำลังวาดใหม่ (เช่น scrollbar
    เพิ่งโผล่ทำให้ขนาด control เปลี่ยน) ภาพตั้งต้นจะเพี้ยน แล้วการเทียบ
    ก่อน-หลังจะรายงานว่า "เปลี่ยนแล้ว" ทั้งที่กดไม่โดน
    """
    prev = capture_image(hwnd)
    if prev is None:
        return None
    for _ in range(attempts):
        time.sleep(interval)
        cur = capture_image(hwnd)
        if cur is None:
            return prev
        if cur.size == prev.size and cur.tobytes() == prev.tobytes():
            return cur
        prev = cur
    log.debug("ภาพของ %s ยังไม่นิ่งหลังรอ %.1fs จะใช้ภาพล่าสุดเป็นตัวตั้งต้น",
              hex(hwnd), interval * attempts)
    return prev


class ChangeWatcher:
    """เฝ้าดูว่าภาพของหน้าต่าง/control หนึ่งเปลี่ยนไปหลังจากที่บอทกดอะไรบางอย่าง

    วิธีใช้
        w = ChangeWatcher(hwnd, region={"left": 440})
        if w.arm():          # ถ่ายภาพตั้งต้น
            ...กดปุ่ม...
            w.wait(timeout=30)   # โยน ChangeNotDetected ถ้าหน้าจอไม่ขยับ
    """

    def __init__(self, hwnd: int, *, region: dict | None = None,
                 min_pixels: int = DEFAULT_MIN_CHANGED_PIXELS,
                 label: str | None = None):
        self.hwnd = hwnd
        self.region = region
        self.min_pixels = int(min_pixels)
        self.label = label or f"หน้าต่าง/control {hex(hwnd)}"
        self.before_full = None
        self.before = None

    def arm(self) -> bool:
        """ถ่ายภาพตั้งต้น คืน False ถ้าเฝ้าดูไม่ได้ (เช่นจอถูกล็อกจนได้ภาพดำ)"""
        self.before_full = stable_image(self.hwnd)
        if self.before_full is None or is_blank(self.before_full):
            reason = "ถ่ายภาพไม่ได้" if self.before_full is None else "ได้ภาพสีเดียวล้วน"
            log.warning(
                "ข้ามการตรวจผลการกด (%s ที่ %s) - อาจเป็นเพราะหน้าจอถูกล็อก "
                "จะกดให้แต่ยืนยันผลไม่ได้", reason, self.label,
            )
            return False
        self.before = crop(self.before_full, self.region)
        return True

    def wait(self, timeout: float, interval: float = 0.2,
             context: str = "") -> None:
        """รอจนภาพเปลี่ยนเกินเกณฑ์ ไม่งั้นโยน ChangeNotDetected"""
        if self.before is None:
            return  # arm() บอกแล้วว่าเฝ้าดูไม่ได้

        best_changed, best_bbox = 0, None
        deadline = time.monotonic() + timeout
        while True:
            time.sleep(interval)
            after_full = capture_image(self.hwnd)
            if after_full is not None and not is_blank(after_full):
                if after_full.size != self.before_full.size:
                    log.info("ขนาดของ %s เปลี่ยนจาก %s เป็น %s ถือว่าหน้าจอเปลี่ยนแล้ว",
                             self.label, self.before_full.size, after_full.size)
                    return
                changed, bbox = diff_stats(self.before, crop(after_full, self.region))
                if changed > best_changed:
                    best_changed, best_bbox = changed, bbox
                if changed >= self.min_pixels:
                    log.info("ยืนยันแล้วว่าการกดมีผล %s เปลี่ยน %d pixel ในกรอบ %s",
                             self.label, changed, bbox)
                    return
            if time.monotonic() >= deadline:
                raise ChangeNotDetected(self._message(timeout, best_changed,
                                                      best_bbox, context))

    def _message(self, timeout: float, changed: int, bbox, context: str) -> str:
        parts = [f"{self.label} ไม่เปลี่ยนภายใน {timeout:.0f} วินาที"]
        if context:
            parts.append(f"  {context}")
        if self.region:
            parts.append(f"  ตรวจเฉพาะพื้นที่ {self.region} "
                         f"ของภาพขนาด {self.before_full.size}")
        if changed:
            parts.append(f"  เปลี่ยนมากสุดแค่ {changed} pixel ในกรอบ {bbox} "
                         f"ซึ่งน้อยกว่าเกณฑ์ {self.min_pixels} - เล็กขนาดนี้มักเป็น"
                         f"ตัวกะพริบหรือกรอบโฟกัส ไม่ใช่ผลของการกด")
        parts.append("  แปลว่าการกดไม่มีผล - เปิดภาพใน screenshots/ แล้วตรวจ "
                     "locator หรือพิกัดใหม่ หรือปรับ change_region "
                     "ให้ตรงพื้นที่ที่ควรเปลี่ยน")
        return "\n".join(parts)
