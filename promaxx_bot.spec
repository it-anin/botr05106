# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec สำหรับ build เป็น .exe (โหมด onedir)
#
# ทำไมเป็น onedir ไม่ใช่ onefile:
#   onefile ต้อง extract ตัวเองลง temp ทุกครั้งที่รัน ซึ่งช้าลงทุกรอบ
#   งานนี้ถูกรันซ้ำทุกวันผ่าน Task Scheduler onedir จึงเหมาะกว่ามาก
#
# flows/, settings.yaml, .env ไม่ได้ฝังเข้ามาใน exe ตรงนี้ - คัดลอกแยก
# ไว้ข้าง exe โดย tools\build_exe.ps1 เพื่อให้แก้ไขได้โดยไม่ต้อง build ใหม่
# (bot/config.py อ่าน ROOT จากตำแหน่งของ sys.executable ตอนถูก build เป็น exe)

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "win32timezone",  # pywin32 มักขาด hidden import ตัวนี้เวลา build
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # โปรเจกต์นี้ไม่ได้ใช้ของพวกนี้เลย แต่ PyInstaller ไล่เจอผ่าน dependency
    # ตัวอื่นใน site-packages (environment นี้ไม่ใช้ venv แยก) ตัดทิ้งลดขนาด
    # จาก ~125MB เหลือน้อยลงมาก และ build เร็วขึ้น
    excludes=[
        "matplotlib", "numpy", "tkinter", "IPython", "jupyter",
        "jupyter_client", "jupyter_core", "notebook", "zmq", "pandas",
        "scipy", "PyQt5", "PySide2", "PIL.ImageQt",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="promaxx-bot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # เป็น CLI ที่ print log/argparse ต้องเปิด console
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="promaxx-bot",
)
