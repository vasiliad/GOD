# GOD2 Auto-Verify Script
# Запускается Task Scheduler каждые 30 минут

$LogFile     = "$PSScriptRoot\verify_log.txt"
$AuditScript = "C:\GOD2\scripts\audit_phase.py"
$Timestamp   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

"[$Timestamp] Auto-verify started" | Add-Content $LogFile

try {
    # Правило #12: Heartbeat
    $Timestamp | Set-Content "$PSScriptRoot\heartbeat.timestamp"

    # 1. Стандартная проверка файлов (task_state.json → files[])
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
    & "$PSScriptRoot\task_manager.ps1" verify 2>&1 | Tee-Object -Append -FilePath $LogFile

    # 2. Правило Phase Contract: аудит заполненности полей (Правило #7 + #9)
    # Проверяет fill-rate критических колонок — не только наличие файла!
    if (Test-Path $AuditScript) {
        "[$Timestamp] Running Phase Contract audit..." | Add-Content $LogFile
        $auditResult = & python $AuditScript --phase all 2>&1
        $auditResult | Tee-Object -Append -FilePath $LogFile

        if ($LASTEXITCODE -ne 0) {
            "[$Timestamp] WARNING: Phase Contract audit FAILED — критические поля не заполнены!" | Add-Content $LogFile
        } else {
            "[$Timestamp] Phase Contract audit OK" | Add-Content $LogFile
        }
    }

    "[$Timestamp] Auto-verify completed OK" | Add-Content $LogFile
} catch {
    "[$Timestamp] ERROR: $_" | Add-Content $LogFile
}
