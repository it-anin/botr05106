"""ทะเบียน action ที่เรียกใช้ได้จากไฟล์ flow YAML

ทุก action รับ (ctx, step) โดย step คือ mapping หนึ่งรายการในลิสต์ steps
คีย์ที่ทุก action ใช้ร่วมกัน: action, name, retry, optional, timeout, pause
"""

from __future__ import annotations

import time
from typing import Any, Callable

from . import datawindow as dw
from . import win
from .context import Context, StepError
from .logging_setup import get_logger

log = get_logger()

REGISTRY: dict[str, Callable[[Context, dict], None]] = {}
ALLOWED_KEYS: dict[str, set[str]] = {}

COMMON_KEYS = {"action", "name", "retry", "optional", "timeout", "pause"}


def action(name: str, keys: tuple[str, ...] = ()):
    def decorate(fn):
        REGISTRY[name] = fn
        ALLOWED_KEYS[name] = set(keys) | COMMON_KEYS
        return fn

    return decorate


DRY_RUN_MAX_WAIT = 5.0


def _timeout(ctx: Context, step: dict) -> float:
    value = float(step.get("timeout", ctx.default_timeout))
    # ตอน dry-run ไม่มีการกดจริง สถานะจึงไม่มีทางเปลี่ยน - ไม่ต้องรอนาน
    return min(value, DRY_RUN_MAX_WAIT) if ctx.dry_run else value


def _target(ctx: Context, step: dict, *, control_key: str = "control") -> tuple[int, int]:
    """คืน (hwnd หน้าต่าง, hwnd control) - ถ้าไม่ระบุ control จะใช้หน้าต่างเอง"""
    window = ctx.resolve_window(step.get("window"), timeout=_timeout(ctx, step))
    spec = step.get(control_key)
    if spec is None:
        return window, window
    return window, ctx.resolve_control(window, spec, timeout=_timeout(ctx, step),
                                       key=control_key)


def _describe(hwnd: int) -> str:
    return (f"{hex(hwnd)} cls={win.get_class(hwnd)!r} "
            f"id={win.get_ctrl_id(hwnd)} title={win.get_text(hwnd)!r}")


# --------------------------------------------------------------- โปรแกรม


@action("launch_app", ("if_running",))
def act_launch_app(ctx: Context, step: dict) -> None:
    """เปิดหรือเกาะโปรแกรม (if_running: attach | restart | fail)"""
    policy = step.get("if_running", "attach")
    if ctx.dry_run and policy == "restart":
        log.info("dry-run: ข้ามการปิดโปรแกรมเดิม จะเกาะตัวที่เปิดอยู่แทน")
        policy = "attach"
    ctx.app.start_or_attach(policy)
    ctx.app.wait_first_window(timeout=_timeout(ctx, step) if "timeout" in step else None)


@action("stop_app")
def act_stop_app(ctx: Context, step: dict) -> None:
    """ปิดโปรแกรม"""
    if ctx.dry_run:
        log.info("dry-run: ข้ามการปิดโปรแกรม")
        return
    ctx.app.stop()


# --------------------------------------------------------------- หน้าต่าง


def _abort_checker(ctx: Context, spec: Any):
    """คืนฟังก์ชันที่โยน StepError ทันทีถ้ามีหน้าต่างที่บ่งบอกความล้มเหลวโผล่ขึ้นมา

    ใช้กับ abort_if: ในไฟล์ flow เช่นดักกล่องข้อความเตือนของ ProMaxx
    เพื่อให้รู้ผลทันทีแทนที่จะรอจนหมด timeout
    """
    if not spec:
        return lambda: None

    from . import locators

    pid = ctx.require_pid()

    def check() -> None:
        for hwnd in locators.find_windows(pid, spec):
            messages = [
                win.get_text(c) for c in win.child_windows(hwnd)
                if win.get_class(c) == "Static" and win.get_text(c).strip()
            ]
            raise StepError(
                f"เจอหน้าต่างที่บอกว่าล้มเหลว: {_describe(hwnd)}\n"
                f"  ข้อความจากโปรแกรม: {' | '.join(messages) or '(ไม่มีข้อความ)'}"
            )

    return check


@action("wait_window", ("window", "as", "abort_if"))
def act_wait_window(ctx: Context, step: dict) -> None:
    """รอหน้าต่างที่ตรงสเปก แล้วตั้งชื่อไว้อ้างอิงด้วย as:"""
    from . import locators

    check_abort = _abort_checker(ctx, step.get("abort_if"))
    ref = step.get("window")
    timeout = _timeout(ctx, step)

    if isinstance(ref, dict):
        pid = ctx.require_pid()
        deadline = time.monotonic() + timeout
        hwnd = None
        while True:
            check_abort()
            found = locators.find_windows(pid, ref)
            if found:
                hwnd = found[0]
                break
            if time.monotonic() >= deadline:
                raise StepError(
                    f"หมดเวลา {timeout:.0f} วินาที ระหว่างรอหน้าต่างที่ตรงสเปก {ref}\n"
                    f"  หน้าต่างที่มีอยู่จริงตอนนี้:\n{locators.describe_windows(pid)}"
                )
            time.sleep(ctx.poll_interval)
    else:
        hwnd = ctx.resolve_window(ref, timeout=timeout)

    log.info("พบหน้าต่าง: %s", _describe(hwnd))
    alias = step.get("as")
    if alias:
        ctx.windows[str(alias)] = hwnd


@action("wait_window_gone", ("window", "abort_if"))
def act_wait_window_gone(ctx: Context, step: dict) -> None:
    """รอจนหน้าต่างปิดหรือถูกซ่อน (ถ้าปิดไปแล้วถือว่าผ่าน)"""
    from . import locators

    if ctx.dry_run:
        log.info("dry-run: ข้ามการรอให้หน้าต่างปิด (ยังไม่ได้กดอะไรจริง)")
        return

    ref = step.get("window")
    timeout = _timeout(ctx, step)
    check_abort = _abort_checker(ctx, step.get("abort_if"))

    if isinstance(ref, str):
        if ref not in ctx.windows:
            raise StepError(f"ยังไม่มีหน้าต่างชื่อ {ref!r} ที่จะรอให้ปิด")
        hwnd = ctx.windows[ref]
        if not win.exists(hwnd):
            log.info("หน้าต่าง %r ปิดไปก่อนหน้านี้แล้ว", ref)
            return
    elif isinstance(ref, dict):
        found = locators.find_windows(ctx.require_pid(), ref)
        if not found:
            log.info("ไม่พบหน้าต่างที่ตรงสเปกตั้งแต่แรก ถือว่าปิดแล้ว")
            return
        hwnd = found[0]
    else:
        hwnd = ctx.resolve_window(ref, timeout=timeout)

    deadline = time.monotonic() + timeout
    while True:
        check_abort()
        if not win.exists(hwnd) or not win.is_visible(hwnd):
            log.info("หน้าต่าง %s ปิดแล้ว", hex(hwnd))
            return
        if time.monotonic() >= deadline:
            raise StepError(
                f"หมดเวลา {timeout:.0f} วินาที ระหว่างรอให้หน้าต่างปิด\n"
                f"  หน้าต่างยังอยู่: {_describe(hwnd)}\n"
                f"  ถ้าเป็นหน้าล็อกอิน แปลว่าอาจกรอกรหัสผิดหรือปุ่มยังไม่ถูกกด"
            )
        time.sleep(ctx.poll_interval)


@action("close_window", ("window",))
def act_close_window(ctx: Context, step: dict) -> None:
    """สั่งปิดหน้าต่างด้วย WM_CLOSE"""
    hwnd = ctx.resolve_window(step.get("window"), timeout=_timeout(ctx, step))
    if ctx.dry_run:
        log.info("dry-run: จะปิดหน้าต่าง %s", _describe(hwnd))
        return
    win.close_window(hwnd)


@action("wait_control", ("window", "control", "state"))
def act_wait_control(ctx: Context, step: dict) -> None:
    """รอให้ control อยู่ในสถานะที่ต้องการ (exists | visible | enabled | gone)"""
    state = str(step.get("state", "visible")).lower()
    window = ctx.resolve_window(step.get("window"), timeout=_timeout(ctx, step))
    spec = step.get("control")
    if spec is None:
        raise StepError("wait_control ต้องระบุ 'control'")
    timeout = _timeout(ctx, step)

    from . import locators

    def probe():
        found = locators.find_controls(window, {**spec, "visible": "any"})
        if state == "gone":
            return True if not found else None
        if not found:
            return None
        hwnd = found[0]
        if state == "exists":
            return hwnd
        if state == "visible":
            return hwnd if win.is_visible(hwnd) else None
        if state == "enabled":
            return hwnd if win.is_enabled(hwnd) else None
        raise StepError(f"ไม่รู้จัก state {state!r} (ใช้ exists/visible/enabled/gone)")

    try:
        win.wait_until(probe, timeout, ctx.poll_interval,
                       what=f"control {spec} อยู่ในสถานะ {state}")
    except win.TimeoutExpired as exc:
        from . import locators as loc
        raise StepError(f"{exc}\n  control ที่มีอยู่จริง:\n{loc.describe(window)}") from exc
    log.info("control %s อยู่ในสถานะ %s แล้ว", spec, state)


# --------------------------------------------------------------- กด/พิมพ์


@action("click", ("window", "control", "method"))
def act_click(ctx: Context, step: dict) -> None:
    """กด control (method: message | bm | center)"""
    _, hwnd = _target(ctx, step)
    method = str(step.get("method", "message")).lower()
    if ctx.dry_run:
        log.info("dry-run: จะกด (%s) %s", method, _describe(hwnd))
        return
    log.info("กด (%s) %s", method, _describe(hwnd))
    if method == "bm":
        win.click_bm(hwnd)
    elif method in ("message", "center"):
        win.click_center(hwnd)
    else:
        raise StepError(f"ไม่รู้จัก method {method!r} (ใช้ message หรือ bm)")


@action("set_text", ("window", "control", "value", "method", "verify"))
def act_set_text(ctx: Context, step: dict) -> None:
    """ใส่ข้อความลง control (method: settext | chars)"""
    _, hwnd = _target(ctx, step)
    value = str(step.get("value", ""))
    method = str(step.get("method", "settext")).lower()
    if ctx.dry_run:
        log.info("dry-run: จะใส่ข้อความยาว %d ตัวลง %s", len(value), _describe(hwnd))
        return
    log.info("ใส่ข้อความยาว %d ตัว (%s) ลง %s", len(value), method, _describe(hwnd))
    dw.write_cell(hwnd, value, method=method)
    _verify_text(hwnd, value, step)


def _verify_text(hwnd: int, expected: str, step: dict) -> None:
    if not step.get("verify", True):
        return
    if dw.is_password_edit(hwnd):
        log.debug("ช่องรหัสผ่าน - ข้ามการอ่านค่ากลับ (วินโดวส์ไม่ให้อ่านข้ามโปรเซส)")
        return
    time.sleep(0.15)
    actual = win.get_text(hwnd)
    if actual != expected:
        raise StepError(
            f"ใส่ข้อความแล้วอ่านกลับไม่ตรง: คาดว่า {expected!r} แต่ได้ {actual!r}\n"
            f"  control: {_describe(hwnd)}\n"
            f"  ลองเปลี่ยนเป็น method: chars ในไฟล์ flow"
        )


@action("send_key", ("window", "control", "key", "repeat"))
def act_send_key(ctx: Context, step: dict) -> None:
    """ส่งปุ่มเดียวไปยัง control (ENTER, TAB, F5, ...)"""
    key = step.get("key")
    if not key:
        raise StepError("send_key ต้องระบุ 'key'")
    _, hwnd = _target(ctx, step)
    repeat = int(step.get("repeat", 1))
    if ctx.dry_run:
        log.info("dry-run: จะส่งปุ่ม %s x%d ไปยัง %s", key, repeat, _describe(hwnd))
        return
    log.info("ส่งปุ่ม %s x%d ไปยัง %s", key, repeat, _describe(hwnd))
    for _ in range(repeat):
        win.send_key(hwnd, key)
        time.sleep(0.08)


@action("send_keys", ("window", "control", "keys"))
def act_send_keys(ctx: Context, step: dict) -> None:
    """ส่งปุ่มหลายตัวเรียงกัน เช่น keys: [TAB, TAB, ENTER]"""
    keys = step.get("keys")
    if not isinstance(keys, list) or not keys:
        raise StepError("send_keys ต้องระบุ 'keys' เป็นลิสต์")
    _, hwnd = _target(ctx, step)
    if ctx.dry_run:
        log.info("dry-run: จะส่งปุ่ม %s ไปยัง %s", keys, _describe(hwnd))
        return
    log.info("ส่งปุ่ม %s ไปยัง %s", keys, _describe(hwnd))
    for k in keys:
        win.send_key(hwnd, str(k))
        time.sleep(0.08)


@action("select_combo", ("window", "control", "value", "index"))
def act_select_combo(ctx: Context, step: dict) -> None:
    """เลือกค่าใน ComboBox ด้วยข้อความหรือลำดับ"""
    _, hwnd = _target(ctx, step)
    items = win.combo_items(hwnd)
    if "index" in step:
        idx = int(step["index"])
    else:
        value = str(step.get("value", ""))
        if value not in items:
            raise StepError(
                f"ไม่พบตัวเลือก {value!r} ใน ComboBox {_describe(hwnd)}\n"
                f"  ตัวเลือกที่มี: {items}"
            )
        idx = items.index(value)
    if ctx.dry_run:
        log.info("dry-run: จะเลือกลำดับ %d (%s) ใน %s",
                 idx, items[idx] if idx < len(items) else "?", _describe(hwnd))
        return
    log.info("เลือกลำดับ %d ใน %s", idx, _describe(hwnd))
    win.combo_select(hwnd, idx)


# --------------------------------------------------------------- DataWindow


def _resolve_dw(ctx: Context, step: dict) -> int:
    window = ctx.resolve_window(step.get("window"), timeout=_timeout(ctx, step))
    spec = step.get("datawindow", {"class_name": win.PB_DATAWINDOW_CLASS})
    return ctx.resolve_control(window, spec, timeout=_timeout(ctx, step),
                               key="datawindow")


@action("dw_click", ("window", "datawindow", "at", "expect_change",
                     "change_region", "change_timeout"))
def act_dw_click(ctx: Context, step: dict) -> None:
    """คลิกที่พิกัดหนึ่งใน DataWindow (at: {x_pct, y_pct} หรือ {x, y})"""
    hwnd = _resolve_dw(ctx, step)
    at = step.get("at")
    if at is None:
        raise StepError("dw_click ต้องระบุ 'at' เช่น at: { x_pct: 0.5, y_pct: 0.78 }")

    if ctx.dry_run:
        x, y = dw.resolve_point(hwnd, at)
        log.info("dry-run: จะคลิก DataWindow %s ที่ client (%d,%d) ขนาด %s%s",
                 hex(hwnd), x, y, win.get_client_size(hwnd),
                 " พร้อมตรวจว่าหน้าจอเปลี่ยนจริง" if step.get("expect_change") else "")
        return

    if step.get("expect_change"):
        x, y = dw.click_and_wait_change(
            hwnd, at,
            region=step.get("change_region"),
            timeout=float(step.get("change_timeout", 5)),
        )
    else:
        x, y = dw.click(hwnd, at)
    log.info("คลิก DataWindow %s ที่ client (%d,%d)", hex(hwnd), x, y)


@action("dw_edit", ("window", "datawindow", "at", "value", "expect_edit",
                    "method", "then_key", "verify"))
def act_dw_edit(ctx: Context, step: dict) -> None:
    """คลิกช่องใน DataWindow แล้วกรอกค่า (ใช้กับหน้าล็อกอิน/ฟอร์มของ PB)"""
    hwnd = _resolve_dw(ctx, step)
    at = step.get("at")
    if at is None:
        raise StepError("dw_edit ต้องระบุ 'at'")
    value = str(step.get("value", ""))
    expect = step.get("expect_edit")

    if ctx.dry_run:
        x, y = dw.resolve_point(hwnd, at)
        log.info(
            "dry-run: จะคลิก DataWindow %s ที่ (%d,%d) แล้วกรอกข้อความยาว %d ตัว "
            "(คาดว่าช่องกรอกคือ control_id=%s)",
            hex(hwnd), x, y, len(value), expect,
        )
        return

    edit = dw.focus_cell(hwnd, at, expect_edit=expect,
                         timeout=float(step.get("timeout", 8)))
    log.info("ช่องกรอกที่ใช้งานอยู่: %s", _describe(edit))
    dw.write_cell(edit, value, method=str(step.get("method", "settext")))
    _verify_text(edit, value, step)

    then_key = step.get("then_key")
    if then_key:
        log.info("ส่งปุ่ม %s เพื่อยืนยันค่า", then_key)
        win.send_key(edit, str(then_key))
        time.sleep(0.3)


# --------------------------------------------------------------- ตรวจ/บันทึก


@action("assert_text", ("window", "control", "equals", "contains", "matches"))
def act_assert_text(ctx: Context, step: dict) -> None:
    """ตรวจข้อความของหน้าต่างหรือ control ว่าอยู่ถูกจอ"""
    import re

    _, hwnd = _target(ctx, step)
    text = win.get_text(hwnd)
    if "equals" in step and text != step["equals"]:
        raise StepError(f"ข้อความไม่ตรง: คาดว่า {step['equals']!r} แต่ได้ {text!r}")
    if "contains" in step and str(step["contains"]) not in text:
        raise StepError(f"ข้อความ {text!r} ไม่มีคำว่า {step['contains']!r}")
    if "matches" in step and not re.search(str(step["matches"]), text):
        raise StepError(f"ข้อความ {text!r} ไม่ตรง regex {step['matches']!r}")
    log.info("ตรวจข้อความผ่าน: %r", text)


@action("screenshot", ("window", "name"))
def act_screenshot(ctx: Context, step: dict) -> None:
    """บันทึกภาพหน้าต่างลงโฟลเดอร์ screenshots"""
    hwnd = ctx.resolve_window(step.get("window"), timeout=_timeout(ctx, step))
    ctx.screenshot(hwnd, str(step.get("name", "shot")))


@action("dump_tree", ("window",))
def act_dump_tree(ctx: Context, step: dict) -> None:
    """เขียนโครงสร้าง control ของหน้าต่างลง log (ใช้ตอนดีบัก)"""
    hwnd = ctx.resolve_window(step.get("window"), timeout=_timeout(ctx, step))
    log.info("โครงสร้าง control ของ %s:\n%s", hex(hwnd), win.format_tree(win.tree(hwnd)))


@action("sleep", ("seconds",))
def act_sleep(ctx: Context, step: dict) -> None:
    """หน่วงเวลา - ใช้ให้น้อยที่สุด ถ้ารออะไรได้ให้ใช้ wait_* แทน"""
    seconds = float(step.get("seconds", 1))
    log.info("หน่วง %.1f วินาที", seconds)
    time.sleep(seconds)


@action("run_flow", ("path",))
def act_run_flow(ctx: Context, step: dict) -> None:
    """เรียก flow อื่นมาทำงานต่อ เช่นเรียก login.yaml ก่อนเริ่มงานจริง"""
    from .runner import run_flow_in_context

    path = step.get("path")
    if not path:
        raise StepError("run_flow ต้องระบุ 'path'")
    run_flow_in_context(ctx, path)
