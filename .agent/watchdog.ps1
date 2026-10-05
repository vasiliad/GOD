# GOD2 — Watchdog for code_behaviors.py
# Автоматически перезапускает при падении, поднимает LM Studio если упал
# Запуск: .\watchdog.ps1

$ScriptPath  = "c:\GOD2\scripts\code_behaviors.py"
$PythonExe   = "python"
$LogFile     = "c:\GOD2\.agent\watchdog.log"
$MaxRestarts = 20        # максимум перезапусков подряд
$SleepSec    = 15        # пауза перед перезапуском

$restarts = 0

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Ensure-LMStudio {
    $status = & lms status 2>&1
    if ($status -match "OFF") {
        Log "LM Studio выключен — запускаем..."
        & lms server start
        Start-Sleep -Seconds 12
        Log "LM Studio запущен."
    } else {
        Log "LM Studio работает."
    }
}

Log "=== Watchdog запущен ==="
Log "Скрипт: $ScriptPath"
Log "Максимум перезапусков: $MaxRestarts"

while ($restarts -lt $MaxRestarts) {
    Ensure-LMStudio

    Log "Запуск code_behaviors.py (попытка #$($restarts + 1))..."
    $proc = Start-Process $PythonExe -ArgumentList $ScriptPath -PassThru -NoNewWindow -Wait

    $exitCode = $proc.ExitCode

    if ($exitCode -eq 0) {
        Log "=== Прогон завершён успешно (exit 0). Watchdog остановлен. ==="
        break
    } else {
        $restarts++
        Log "ОШИБКА: процесс завершился с кодом $exitCode. Перезапуск через ${SleepSec}с... ($restarts/$MaxRestarts)"
        Start-Sleep -Seconds $SleepSec
    }
}

if ($restarts -ge $MaxRestarts) {
    Log "!!! Достигнут лимит перезапусков ($MaxRestarts). Нужна ручная проверка !!!"
}
