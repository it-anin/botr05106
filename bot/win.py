"""ชั้นล่างสุด: อ่านโครงสร้างหน้าต่าง Win32 และส่ง message ตรงถึง control

ทุกฟังก์ชันในไฟล์นี้ทำงานได้แม้หน้าจอถูกล็อก เพราะไม่แตะเมาส์/คีย์บอร์ดจริง

หมายเหตุสำคัญ: GetWindowText อ่านข้อความของ control ข้าม process ไม่ได้
(คืนค่าว่างเสมอ) จึงต้องใช้ WM_GETTEXT ผ่าน SendMessageTimeout แทน
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Callable

import win32api
import win32con
import win32gui
import win32process

# --- window class ของ PowerBuilder 12.5 (ยืนยันจาก PBVM125.DLL และของจริง) ---
PB_WINDOW_CLASSES = ("FNWND3125", "FNWNS3125")
PB_USEROBJECT_CLASS = "FNUDO3125"
PB_DATAWINDOW_CLASS = "pbdw125"
PB_DW_STATIC_CLASS = "pbdwst125"
PB_TAB_CLASS_PREFIX = "PBTabControl32"   # ของจริงคือ PBTabControl32_100
PB_TOOLBAR_CLASSES = ("FNFIXEDBAR125", "FNFLOATBAR125")
DIALOG_CLASS = "#32770"

BM_CLICK = 0x00F5
EM_SETSEL = 0x00B1
CB_SETCURSEL = 0x014E
CB_GETCOUNT = 0x0146
CB_GETLBTEXT = 0x0148
CB_GETLBTEXTLEN = 0x0149
CBN_SELCHANGE = 1

VK_MAP = {
    "ENTER": win32con.VK_RETURN,
    "RETURN": win32con.VK_RETURN,
    "TAB": win32con.VK_TAB,
    "ESC": win32con.VK_ESCAPE,
    "ESCAPE": win32con.VK_ESCAPE,
    "SPACE": win32con.VK_SPACE,
    "BACKSPACE": win32con.VK_BACK,
    "DELETE": win32con.VK_DELETE,
    "INSERT": win32con.VK_INSERT,
    "HOME": win32con.VK_HOME,
    "END": win32con.VK_END,
    "UP": win32con.VK_UP,
    "DOWN": win32con.VK_DOWN,
    "LEFT": win32con.VK_LEFT,
    "RIGHT": win32con.VK_RIGHT,
    "PGUP": win32con.VK_PRIOR,
    "PGDN": win32con.VK_NEXT,
    **{f"F{i}": getattr(win32con, f"VK_F{i}") for i in range(1, 13)},
}


class WinError(Exception):
    pass


class TimeoutExpired(WinError):
    pass


# --------------------------------------------------------------------------
# ctypes: SendMessageTimeout รองรับ buffer และไม่ค้างถ้าโปรแกรมไม่ตอบ
# --------------------------------------------------------------------------

_u32 = ctypes.WinDLL("user32", use_last_error=True)
_LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long

_u32.SendMessageTimeoutW.restype = _LRESULT
_u32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_void_p,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
]

SMTO_ABORTIFHUNG = 0x0002
DEFAULT_SEND_TIMEOUT_MS = 5000


def _send(hwnd: int, msg: int, wparam: int = 0, lparam=None,
          timeout_ms: int = DEFAULT_SEND_TIMEOUT_MS) -> int | None:
    """SendMessage ที่ไม่มีวันค้าง คืน None ถ้าโปรแกรมไม่ตอบภายในเวลา"""
    out = ctypes.c_size_t(0)
    ok = _u32.SendMessageTimeoutW(
        hwnd, msg, wparam, lparam, SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(out)
    )
    if not ok:
        return None
    return int(out.value)


# --------------------------------------------------------------------------
# อ่านข้อมูลหน้าต่าง
# --------------------------------------------------------------------------


def get_class(hwnd: int) -> str:
    try:
        return win32gui.GetClassName(hwnd)
    except Exception:
        return ""


def get_text(hwnd: int, timeout_ms: int = 2000) -> str:
    """อ่านข้อความด้วย WM_GETTEXT - ใช้ได้กับ control ข้าม process

    หมายเหตุ: ช่องรหัสผ่าน (ES_PASSWORD) วินโดวส์บล็อกไม่ให้อ่านข้ามโปรเซส
    จึงคืนค่าว่างเสมอ ซึ่งเป็นพฤติกรรมที่ถูกต้องแล้ว
    """
    n = _send(hwnd, win32con.WM_GETTEXTLENGTH, 0, None, timeout_ms)
    if not n:
        return ""
    buf = ctypes.create_unicode_buffer(int(n) + 1)
    if _send(hwnd, win32con.WM_GETTEXT, int(n) + 1,
             ctypes.cast(buf, ctypes.c_void_p), timeout_ms) is None:
        return ""
    return buf.value


def get_ctrl_id(hwnd: int) -> int:
    try:
        return win32gui.GetDlgCtrlID(hwnd)
    except Exception:
        return 0


def get_rect(hwnd: int) -> tuple[int, int, int, int]:
    """กรอบหน้าต่างในพิกัดจอ"""
    try:
        return win32gui.GetWindowRect(hwnd)
    except Exception:
        return (0, 0, 0, 0)


def get_client_size(hwnd: int) -> tuple[int, int]:
    try:
        _, _, r, b = win32gui.GetClientRect(hwnd)
        return r, b
    except Exception:
        return (0, 0)


def is_visible(hwnd: int) -> bool:
    try:
        return bool(win32gui.IsWindowVisible(hwnd))
    except Exception:
        return False


def is_enabled(hwnd: int) -> bool:
    try:
        return bool(win32gui.IsWindowEnabled(hwnd))
    except Exception:
        return False


def exists(hwnd: int) -> bool:
    try:
        return bool(win32gui.IsWindow(hwnd))
    except Exception:
        return False


def get_pid(hwnd: int) -> int:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except Exception:
        return 0


def top_windows(pid: int | None = None) -> list[int]:
    """หน้าต่างระดับบนสุดทั้งหมด (กรองตาม pid ได้)"""
    found: list[int] = []

    def cb(hwnd: int, _):
        if pid is None or get_pid(hwnd) == pid:
            found.append(hwnd)
        return True

    win32gui.EnumWindows(cb, None)
    return found


def child_windows(hwnd: int, *, direct_only: bool = False) -> list[int]:
    """ลูกทั้งหมด (ทุกชั้น) หรือเฉพาะลูกตรง"""
    kids: list[int] = []

    def cb(child: int, _):
        kids.append(child)
        return True

    try:
        win32gui.EnumChildWindows(hwnd, cb, None)
    except Exception:
        return []
    if direct_only:
        return [k for k in kids if win32gui.GetParent(k) == hwnd]
    return kids


def info(hwnd: int) -> dict:
    l, t, r, b = get_rect(hwnd)
    return {
        "hwnd": hwnd,
        "hwnd_hex": hex(hwnd),
        "class_name": get_class(hwnd),
        "text": get_text(hwnd),
        "control_id": get_ctrl_id(hwnd),
        "rect": {"left": l, "top": t, "right": r, "bottom": b,
                 "width": r - l, "height": b - t},
        "visible": is_visible(hwnd),
        "enabled": is_enabled(hwnd),
    }


def tree(hwnd: int, depth: int = 0, max_depth: int = 12) -> dict:
    node = info(hwnd)
    node["depth"] = depth
    node["children"] = [
        tree(k, depth + 1, max_depth)
        for k in (child_windows(hwnd, direct_only=True) if depth < max_depth else [])
    ]
    return node


def flatten(node: dict) -> list[dict]:
    out = [node]
    for c in node.get("children", []):
        out.extend(flatten(c))
    return out


def format_tree(node: dict) -> str:
    lines = []
    for n in flatten(node):
        pad = "  " * n.get("depth", 0)
        flags = ("V" if n["visible"] else "-") + ("E" if n["enabled"] else "d")
        rect = n["rect"]
        lines.append(
            f"{pad}[{flags}] cls={n['class_name']!r} id={n['control_id']} "
            f"text={n['text']!r} hwnd={n['hwnd_hex']} "
            f"pos=({rect['left']},{rect['top']}) size={rect['width']}x{rect['height']}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# รอเงื่อนไข
# --------------------------------------------------------------------------


def wait_until(predicate: Callable[[], object], timeout: float,
               interval: float = 0.25, what: str = "เงื่อนไข"):
    """วนเรียก predicate จนได้ค่า truthy คืนค่านั้น ไม่งั้นโยน TimeoutExpired"""
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise TimeoutExpired(f"หมดเวลา {timeout:.0f} วินาที ระหว่างรอ: {what}")
        time.sleep(interval)


def wait_gone(hwnd: int, timeout: float, interval: float = 0.25):
    return wait_until(
        lambda: (not exists(hwnd)) or (not is_visible(hwnd)),
        timeout, interval, what=f"หน้าต่าง {hex(hwnd)} ปิด",
    )


# --------------------------------------------------------------------------
# สั่งงานผ่าน message (ทำงานแม้จอล็อก)
# --------------------------------------------------------------------------


def post(hwnd: int, msg: int, wparam: int = 0, lparam: int = 0,
         ignore_dead: bool = False) -> None:
    """PostMessage แบบไม่รอผล

    ignore_dead=True สำหรับกรณีที่การกดทำให้หน้าต่างปิดไปกลางคัน
    (เช่นปุ่ม Sign in ทำงานตั้งแต่ WM_LBUTTONDOWN)
    """
    try:
        win32api.PostMessage(hwnd, msg, wparam, lparam)
    except Exception as exc:
        if ignore_dead and not exists(hwnd):
            return
        raise WinError(f"ส่ง message ไปยัง {hex(hwnd)} ไม่สำเร็จ: {exc}") from exc


def set_text(hwnd: int, text: str) -> bool:
    """WM_SETTEXT ข้าม process"""
    buf = ctypes.create_unicode_buffer(text)
    res = _send(hwnd, win32con.WM_SETTEXT, 0, ctypes.cast(buf, ctypes.c_void_p))
    return res is not None


def notify_parent(hwnd: int, code: int) -> None:
    """แจ้ง parent ว่า control เปลี่ยนค่า (PB บางจอรอ EN_CHANGE)"""
    parent = win32gui.GetParent(hwnd)
    if not parent:
        return
    ctrl_id = get_ctrl_id(hwnd)
    wparam = (code << 16) | (ctrl_id & 0xFFFF)
    _send(parent, win32con.WM_COMMAND, wparam, ctypes.c_void_p(hwnd), 2000)


def _lparam_xy(x: int, y: int) -> int:
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def click_client(hwnd: int, x: int, y: int, *, hold: float = 0.06) -> None:
    """คลิกซ้ายที่พิกัด (x, y) ซึ่งวัดจากมุมบนซ้ายของ client area ของ hwnd"""
    lp = _lparam_xy(x, y)
    post(hwnd, win32con.WM_MOUSEMOVE, 0, lp)
    post(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
    time.sleep(hold)
    # ปุ่มบางตัวทำงานทันทีตอน BUTTONDOWN แล้วหน้าต่างถูกทำลาย - ไม่ถือว่าพลาด
    post(hwnd, win32con.WM_LBUTTONUP, 0, lp, ignore_dead=True)


def click_center(hwnd: int) -> None:
    """คลิกกลาง control"""
    w, h = get_client_size(hwnd)
    click_client(hwnd, max(w // 2, 1), max(h // 2, 1))


def click_bm(hwnd: int) -> None:
    """BM_CLICK - เชื่อถือได้กับ CommandButton ของ PowerBuilder"""
    post(hwnd, BM_CLICK, 0, 0, ignore_dead=True)


def send_chars(hwnd: int, text: str, delay: float = 0.02) -> None:
    """ยิง WM_CHAR ทีละตัว - ใช้กับช่องที่ PB ตรวจค่าราย keystroke"""
    for ch in text:
        post(hwnd, win32con.WM_CHAR, ord(ch), 0)
        time.sleep(delay)


def clear_text(hwnd: int) -> None:
    """เลือกทั้งหมดแล้วลบ ด้วย message ล้วน"""
    _send(hwnd, EM_SETSEL, 0, ctypes.c_void_p(-1), 2000)
    post(hwnd, win32con.WM_CHAR, win32con.VK_BACK, 0)


def vk_of(key: str) -> int:
    name = str(key).strip().upper()
    if name in VK_MAP:
        return VK_MAP[name]
    if len(name) == 1:
        return win32api.VkKeyScan(name) & 0xFF
    raise WinError(f"ไม่รู้จักปุ่ม {key!r}")


def send_key(hwnd: int, key: str, hold: float = 0.04) -> None:
    """ส่งปุ่มเดียว (ENTER/TAB/F5/...) ตรงถึง control"""
    vk = vk_of(key)
    post(hwnd, win32con.WM_KEYDOWN, vk, 0)
    time.sleep(hold)
    post(hwnd, win32con.WM_KEYUP, vk, 0, ignore_dead=True)


def close_window(hwnd: int) -> None:
    post(hwnd, win32con.WM_CLOSE, 0, 0, ignore_dead=True)


# --------------------------------------------------------------------------
# ComboBox
# --------------------------------------------------------------------------


def combo_items(hwnd: int) -> list[str]:
    count = _send(hwnd, CB_GETCOUNT, 0, None, 2000) or 0
    items = []
    for i in range(int(count)):
        n = _send(hwnd, CB_GETLBTEXTLEN, i, None, 2000) or 0
        buf = ctypes.create_unicode_buffer(int(n) + 1)
        _send(hwnd, CB_GETLBTEXT, i, ctypes.cast(buf, ctypes.c_void_p), 2000)
        items.append(buf.value)
    return items


def combo_select(hwnd: int, index: int) -> None:
    _send(hwnd, CB_SETCURSEL, index, None)
    notify_parent(hwnd, CBN_SELCHANGE)
