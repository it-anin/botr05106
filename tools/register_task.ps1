<#
.SYNOPSIS
    ลงทะเบียน Scheduled Task ให้บอท ProMaxx Report รันอัตโนมัติ

.DESCRIPTION
    ต้องใช้ "Run only when user is logged on" เท่านั้น
    ถ้าเลือก "whether user is logged on or not" งานจะไปรันใน Session 0
    ซึ่งไม่มีเดสก์ท็อป บอทจะหาหน้าต่างของโปรแกรมไม่เจอ 100%

.EXAMPLE
    .\tools\register_task.ps1 -Time 06:30 -Flows "flows/login.yaml"

.EXAMPLE
    .\tools\register_task.ps1 -Time 22:00 -Flows "flows/login.yaml,flows/daily_report.yaml" -TaskName "ProMaxxBot_Night"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Time,

    [Parameter(Mandatory = $true)]
    [string]$Flows,

    [string]$TaskName = "ProMaxxReportBot",

    [int]$TimeLimitMinutes = 60
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$exePath = Join-Path $projectRoot "dist\promaxx-bot\promaxx-bot.exe"

$flowArgs = ($Flows -split ',' | ForEach-Object { $_.Trim() }) -join ' '

# ใช้ .exe ที่ build ไว้แล้วถ้ามี (ไม่ต้องพึ่งว่าเครื่องนี้ลง Python ไว้หรือเปล่า)
# ไม่มีก็ตกไปใช้ python run.py แบบเดิม
if (Test-Path $exePath) {
    $exeDir = Split-Path -Parent $exePath
    $exec = $exePath
    $arguments = "run $flowArgs"
    $workDir = $exeDir
    Write-Host "ใช้ .exe : $exePath"
} else {
    $python = "C:\Program Files\Python311\python.exe"
    if (-not (Test-Path $python)) {
        $found = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $found) { throw "หา python.exe ไม่เจอ และไม่พบ $exePath (ยังไม่ได้ build .\tools\build_exe.ps1)" }
        $python = $found.Source
    }
    $exec = $python
    $arguments = "run.py run $flowArgs"
    $workDir = $projectRoot
    Write-Host "ใช้ python: $python  (ยังไม่ได้ build .exe - รัน .\tools\build_exe.ps1 ถ้าอยากเลิกพึ่ง Python บนเครื่อง)"
}

Write-Host "โปรเจกต์ : $projectRoot"
Write-Host "คำสั่ง   : $exec $arguments"
Write-Host "เวลา     : $Time ทุกวัน"
Write-Host "ชื่องาน  : $TaskName"

$action = New-ScheduledTaskAction -Execute $exec -Argument $arguments -WorkingDirectory $workDir
$trigger = New-ScheduledTaskTrigger -Daily -At $Time

# Interactive = ต้องมี session ของผู้ใช้อยู่จริง ซึ่งเป็นเงื่อนไขบังคับของ GUI automation
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

$settings = New-ScheduledTaskSettings `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes $TimeLimitMinutes) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host ""
Write-Host "ลงทะเบียนเรียบร้อย" -ForegroundColor Green
Write-Host "ทดสอบด้วย : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "ดูผล      : $projectRoot\logs\bot.log"
Write-Host "ลบทิ้ง    : Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
