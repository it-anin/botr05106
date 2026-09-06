<#
.SYNOPSIS
    Build บอทเป็น .exe (PyInstaller, โหมด onedir) แล้วจัดโฟลเดอร์ dist ให้พร้อมใช้งาน

.DESCRIPTION
    ได้ dist\promaxx-bot\promaxx-bot.exe ที่ใช้แทน "python run.py" ได้ทุกคำสั่ง
    flows\, settings.yaml, .env ถูกคัดลอกไปวางข้าง exe ให้แก้ไขได้โดยไม่ต้อง build ใหม่
    (โฟลเดอร์ dist\ ทั้งหมดไม่ได้ commit เข้า git - เป็นไฟล์ผลลัพธ์การ build)

    promaxx-bot.exe เป็น CLI ต้องมี argument เสมอ (run/inspect/stop/actions)
    ดับเบิลคลิกตรง ๆ จะไม่มี argument โปรแกรมจะฟ้อง error แล้วปิดทันที
    จึงสร้าง "ส่งออกรายงาน.bat" คู่กันไว้ ดับเบิลคลิกได้จริงพร้อม pause ท้ายสุด

.EXAMPLE
    .\tools\build_exe.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host "=== ลบ build เก่า ===" -ForegroundColor Cyan
# ลบ "ไฟล์ข้างใน" ไม่ใช่ตัวโฟลเดอร์ - VS Code file watcher (และ indexer ของวินโดวส์)
# ชอบถือ handle ค้างไว้ที่ตัวโฟลเดอร์ ทำให้ Remove-Item ทั้งโฟลเดอร์ล้มด้วย
# WinError 32 ทั้งที่ไม่มีโปรแกรมของเราเปิดอยู่เลย แต่ลบไฟล์ข้างในยังทำได้ปกติ
foreach ($target in @("build", "dist")) {
    if (-not (Test-Path $target)) { continue }
    try {
        Get-ChildItem $target -Recurse -Force | Remove-Item -Recurse -Force -ErrorAction Stop
    } catch {
        throw "ล้างโฟลเดอร์ $target ไม่สำเร็จ - อาจมี promaxx-bot.exe เปิดค้างอยู่`n  $($_.Exception.Message)"
    }
    # ตัวโฟลเดอร์ลบได้ก็ดี ลบไม่ได้ก็ไม่เป็นไร เพราะข้างในว่างแล้ว
    Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "=== รัน PyInstaller ===" -ForegroundColor Cyan
python -m PyInstaller promaxx_bot.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build ไม่สำเร็จ (exit $LASTEXITCODE)" }

$distDir = Join-Path $projectRoot "dist\promaxx-bot"
if (-not (Test-Path "$distDir\promaxx-bot.exe")) {
    throw "build เสร็จแต่หา $distDir\promaxx-bot.exe ไม่เจอ"
}

Write-Host "=== คัดลอกไฟล์ตั้งค่า/flow ไปไว้ข้าง exe ===" -ForegroundColor Cyan
Copy-Item "flows" "$distDir\flows" -Recurse -Force
Copy-Item "settings.yaml" "$distDir\settings.yaml" -Force
Copy-Item "tools" "$distDir\tools" -Recurse -Force

# ── ส่วนอัปโหลด Supabase (Node) ──
# ต้องก๊อปไปด้วย ไม่งั้น `promaxx-bot.exe run ... --then-upload` จะหา uploader ไม่เจอ
# (bot\config.py ตั้ง ROOT = โฟลเดอร์ของ .exe เมื่อ frozen ทุกอย่างจึงต้องอยู่ข้าง exe)
Write-Host "=== คัดลอกส่วนอัปโหลด Supabase ===" -ForegroundColor Cyan
Copy-Item "upload-products.mjs" "$distDir\upload-products.mjs" -Force
Copy-Item "package.json" "$distDir\package.json" -Force
if (Test-Path "node_modules") {
    Copy-Item "node_modules" "$distDir\node_modules" -Recurse -Force
    Write-Host "  คัดลอก node_modules แล้ว"
} else {
    Write-Host "  ⚠️ ไม่พบ node_modules - รัน npm install ก่อน ไม่งั้น --then-upload จะพัง" -ForegroundColor Yellow
}

if (Test-Path ".env") {
    Copy-Item ".env" "$distDir\.env" -Force
    Write-Host "  คัดลอก .env (มีรหัสผ่าน) แล้ว - ตรวจสอบว่า dist\ อยู่ในที่ปลอดภัย" -ForegroundColor Yellow
} elseif (Test-Path ".env.example") {
    Copy-Item ".env.example" "$distDir\.env" -Force
    Write-Host "  ไม่พบ .env ต้นทาง คัดลอก .env.example ไปแทน - ต้องแก้รหัสผ่านเองใน dist\.env" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== เสร็จแล้ว ===" -ForegroundColor Green
Write-Host "  ดับเบิลคลิก exe ได้เลย : $distDir\promaxx-bot.exe"
Write-Host "  หรือสั่งจาก CLI  : $distDir\promaxx-bot.exe run flows/login.yaml --dry-run"
