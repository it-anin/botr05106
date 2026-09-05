<#
.SYNOPSIS
    รัน flow export R05.106 แล้วอัปโหลดเข้า Supabase ต่อทันทีถ้า export สำเร็จ

.DESCRIPTION
    สคริปต์นี้เป็นแค่ "ตัวสั่งงาน" — ไม่มี logic การอัปโหลดอยู่ในนี้เลยแม้แต่บรรทัดเดียว
    โค้ดอัปโหลดตัวจริงอยู่ที่ SaleSupport\upload-products.mjs ที่เดียว พร้อม guard + เทส

    ⚠️ ห้ามก๊อป upload-products.mjs มาไว้ในโปรเจกต์นี้
       upload-customer-history.mjs เคยถูกก๊อปจนมี 3 สำเนาที่โค้ดไม่ตรงกัน
       แล้วตัวที่ Task Scheduler เรียกจริงกลายเป็นตัวเก่า — แก้บั๊กที่ repo แล้วของจริงไม่เปลี่ยน

    exit code: 0 = สำเร็จ · 2 = อัปโหลดข้าม (ไฟล์ไม่ได้ถูกอัปเดต) · 1 = ผิดพลาด

.EXAMPLE
    .\tools\run_and_upload.ps1

.EXAMPLE
    .\tools\run_and_upload.ps1 -DryRunUpload
    # ซ้อมเต็มรอบ: export จริง แต่ไม่เขียน Supabase

.EXAMPLE
    .\tools\run_and_upload.ps1 -SkipExport
    # อัปโหลดซ้ำด้วยไฟล์เดิม ไม่เปิด ProMaxx (ใช้ตอน export ผ่านแล้วแต่อัปโหลดพัง)

.EXAMPLE
    .\tools\run_and_upload.ps1 -Uploader "D:\SaleSupport\upload-products.mjs" -Csv "D:\out\R05.106.CSV"
#>
[CmdletBinding()]
param(
    [string]$Flows = "flows/r05_106_export.yaml",

    # path เริ่มต้นอ้าง $env:USERPROFILE ไม่ hardcode ชื่อผู้ใช้ เพราะจะย้ายไปรันเครื่อง Server
    [string]$Uploader = "$env:USERPROFILE\Desktop\SaleSupport\upload-products.mjs",
    [string]$Csv = "$env:USERPROFILE\Desktop\run-upload-stock\R05.106.CSV",
    [string]$Node = "C:\Program Files\nodejs\node.exe",

    [switch]$DryRunUpload,

    # ข้ามการ export ใช้ไฟล์ที่มีอยู่แล้ว — สำหรับอัปโหลดซ้ำเมื่อ export ผ่านแล้ว
    # แต่อัปโหลดพัง (เช่น Supabase ล่มชั่วคราว) จะได้ไม่ต้องเปิด ProMaxx ใหม่
    [switch]$SkipExport
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$exePath = Join-Path $projectRoot "dist\promaxx-bot\promaxx-bot.exe"

if ($SkipExport) {
    Write-Host "===== 1/2 export R05.106 (ข้าม) ====="
    Write-Host "-SkipExport: ใช้ไฟล์ที่มีอยู่แล้ว ไม่เปิด ProMaxx"
    Write-Host "ไฟล์   : $Csv"
} else {
    $flowArgs = @($Flows -split ',' | ForEach-Object { $_.Trim() })

    # ใช้ .exe ที่ build ไว้แล้วถ้ามี ไม่มีก็ตกไปใช้ python run.py (logic เดียวกับ register_task.ps1)
    if (Test-Path $exePath) {
        $exec = $exePath
        $botArgs = @("run") + $flowArgs
        $workDir = Split-Path -Parent $exePath
    } else {
        $python = "C:\Program Files\Python311\python.exe"
        if (-not (Test-Path $python)) {
            $found = Get-Command python -ErrorAction SilentlyContinue
            if ($null -eq $found) { throw "หา python.exe ไม่เจอ และไม่พบ $exePath (ยังไม่ได้ build .\tools\build_exe.ps1)" }
            $python = $found.Source
        }
        $exec = $python
        $botArgs = @("run.py", "run") + $flowArgs
        $workDir = $projectRoot
    }

    # log ของบอทอยู่ใต้โฟลเดอร์ที่รันจริง (exe เขียนลง dist\promaxx-bot\logs ไม่ใช่ logs ของ project root)
    $botLog = Join-Path $workDir "logs\bot.log"

    Write-Host "===== 1/2 export R05.106 ====="
    Write-Host "คำสั่ง : $exec $($botArgs -join ' ')"
    Write-Host ""

    Push-Location $workDir
    try {
        & $exec @botArgs
        $botRc = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    # export ไม่สำเร็จ = ไฟล์ CSV ไม่ได้ถูกเขียนใหม่ ไม่มีอะไรให้อัปโหลด
    if ($botRc -ne 0) {
        Write-Host ""
        Write-Host "[SKIP UPLOAD] export ไม่สำเร็จ (exit $botRc) - ไม่อัปโหลด ข้อมูลเดิมใน Supabase ยังอยู่ครบ" -ForegroundColor Yellow
        Write-Host "              ดูสาเหตุที่ $botLog"
        exit 1
    }
}

Write-Host ""
Write-Host "===== 2/2 upload เข้า Supabase ====="

if (-not (Test-Path $Node)) {
    throw "ไม่พบ node.exe ที่ $Node (ส่ง -Node ชี้ path เองได้)"
}
if (-not (Test-Path $Uploader)) {
    throw "ไม่พบสคริปต์อัปโหลดที่ $Uploader`n   เครื่องนี้ต้อง clone repo SaleSupport ไว้ (ห้ามก๊อปเฉพาะไฟล์ .mjs)"
}

$uploadArgs = @($Uploader, "--file", $Csv)
if ($DryRunUpload) { $uploadArgs += "--dry-run" }

Write-Host "คำสั่ง : $Node $($uploadArgs -join ' ')"
Write-Host ""

& $Node @uploadArgs
$upRc = $LASTEXITCODE

Write-Host ""
if ($upRc -eq 0) {
    Write-Host "[OK] export + upload สำเร็จ" -ForegroundColor Green
} elseif ($upRc -eq 2) {
    Write-Host "[SKIP] export สำเร็จ แต่ uploader ข้าม (ไฟล์ไม่ได้ถูกอัปเดต) - ข้อมูลเดิมยังอยู่ครบ" -ForegroundColor Yellow
} else {
    Write-Host "[ERROR] อัปโหลดไม่สำเร็จ (exit $upRc) - ดู upload-products.log ข้าง $Uploader" -ForegroundColor Red
    $upRc = 1
}

exit $upRc
