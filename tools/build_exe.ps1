<#
.SYNOPSIS
    Build บอทเป็น .exe (PyInstaller, โหมด onedir) แล้วจัดโฟลเดอร์ dist ให้พร้อมใช้งาน

.DESCRIPTION
    ได้ dist\promaxx-bot\promaxx-bot.exe ที่ใช้แทน "python run.py" ได้ทุกคำสั่ง
    flows\, settings.yaml, .env ถูกคัดลอกไปวางข้าง exe ให้แก้ไขได้โดยไม่ต้อง build ใหม่
    (โฟลเดอร์ dist\ ทั้งหมดไม่ได้ commit เข้า git - เป็นไฟล์ผลลัพธ์การ build)

.EXAMPLE
    .\tools\build_exe.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host "=== ลบ build เก่า ===" -ForegroundColor Cyan
Remove-Item -Recurse -Force "build", "dist" -ErrorAction SilentlyContinue

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

if (Test-Path ".env") {
    Copy-Item ".env" "$distDir\.env" -Force
    Write-Host "  คัดลอก .env (มีรหัสผ่าน) แล้ว - ตรวจสอบว่า dist\ อยู่ในที่ปลอดภัย" -ForegroundColor Yellow
} elseif (Test-Path ".env.example") {
    Copy-Item ".env.example" "$distDir\.env" -Force
    Write-Host "  ไม่พบ .env ต้นทาง คัดลอก .env.example ไปแทน - ต้องแก้รหัสผ่านเองใน dist\.env" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== เสร็จแล้ว ===" -ForegroundColor Green
Write-Host "  ไฟล์ที่ได้: $distDir\promaxx-bot.exe"
Write-Host "  ทดสอบด้วย: $distDir\promaxx-bot.exe run flows/login.yaml --dry-run"
