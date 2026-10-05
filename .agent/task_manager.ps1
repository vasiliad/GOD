# PowerShell Task Manager for GOD2
# Usage: .\task_manager.ps1 [status|done|verify|dispatch]

param(
    [Parameter(Position=0)]
    [string]$Command = "status",
    [string]$TaskId = ""
)

$StateFile = "$PSScriptRoot\task_state.json"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$SignalsDir = "$PSScriptRoot\signals"
$InboxDir = "$PSScriptRoot\inbox"

# Ensure dirs exist
@($SignalsDir, $InboxDir) | ForEach-Object { if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null } }

function Read-State {
    Get-Content $StateFile -Raw | ConvertFrom-Json
}

function Write-State($state) {
    $state | ConvertTo-Json -Depth 10 | Set-Content $StateFile -Encoding UTF8
}

function Show-Status {
    $state = Read-State
    Write-Host "`n=== GOD2 Task Status ===" -ForegroundColor Cyan
    Write-Host "Project: $($state.project) v$($state.version)`n" -ForegroundColor Gray

    $hbFile = Join-Path $PSScriptRoot "heartbeat.timestamp"
    if (Test-Path $hbFile) {
        $hbTime = (Get-Item $hbFile).LastWriteTime
        $diffMin = (New-TimeSpan -Start $hbTime -End (Get-Date)).TotalMinutes
        if ($diffMin -gt 40) {
            Write-Host "!!! ВНИМАНИЕ !!! Планировщик (Task Scheduler) мертв! Последний пульс: $([math]::Round($diffMin)) минут назад." -ForegroundColor Red
        } else {
            Write-Host "Auto-Verify Heartbeat: OK ($([math]::Round($diffMin)) min ago)" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "!!! ВНИМАНИЕ !!! Файл пульса не найден. Планировщик не работает!" -ForegroundColor Red
    }

    $groups = @{
        "READY"   = @(); "WAITING" = @(); "DONE" = @()
    }

    foreach ($task in $state.tasks) {
        $signalFile = "$SignalsDir\$($task.id).done"
        if ($task.done -or (Test-Path $signalFile)) {
            $groups["DONE"] += $task
        } elseif ($task.status -eq "ready") {
            $groups["READY"] += $task
        } else {
            $groups["WAITING"] += $task
        }
    }

    Write-Host "--- READY TO START ---" -ForegroundColor Green
    $groups["READY"] | ForEach-Object { Write-Host "  [$($_.id)] $($_.name)" -ForegroundColor Green }

    Write-Host "`n--- WAITING (deps) ---" -ForegroundColor Yellow
    $groups["WAITING"] | ForEach-Object {
        Write-Host "  [$($_.id)] $($_.name)" -ForegroundColor Yellow
        Write-Host "       deps: $($_.deps -join ', ')" -ForegroundColor DarkGray
    }

    Write-Host "`n--- DONE ---" -ForegroundColor DarkGray
    $groups["DONE"] | ForEach-Object { Write-Host "  [x] $($_.id) $($_.name)" -ForegroundColor DarkGray }

    Write-Host ""
}

function Invoke-Verify {
    $state = Read-State
    $anyUpdated = $false

    Write-Host "`n=== Verifying GOD2 tasks ===" -ForegroundColor Cyan

    foreach ($task in $state.tasks) {
        if ($task.done) { continue }

        $allFilesPresent = $true
        $missingFiles = @()

        foreach ($file in $task.files) {
            $fullPath = Join-Path $ProjectRoot $file
            $items = Get-Item $fullPath -ErrorAction SilentlyContinue
            if ($items) {
                # Could be multiple files if wildcard is used
                $validFound = $false
                foreach ($item in $items) {
                    if ($item.Length -ge 15) {
                        $validFound = $true
                        break
                    }
                }
                
                if (-not $validFound) {
                    $allFilesPresent = $false
                    $missingFiles += "$file (found but sizes < 15 bytes)"
                }
            } else {
                $allFilesPresent = $false
                $missingFiles += $file
            }
        }

        if ($allFilesPresent -and $task.files.Count -gt 0) {
            $task.done = $true
            $task.status = "done"
            # Create signal file
            $signalFile = "$SignalsDir\$($task.id).done"
            "done at $(Get-Date -Format 'yyyy-MM-dd HH:mm')" | Set-Content $signalFile
            Write-Host "  [DONE] $($task.id): $($task.name)" -ForegroundColor Green
            $anyUpdated = $true

            # Unlock dependents
            foreach ($other in $state.tasks) {
                if (-not $other.done -and $other.status -eq "waiting") {
                    $depsReady = $true
                    foreach ($dep in $other.deps) {
                        $depTask = $state.tasks | Where-Object { $_.id -eq $dep }
                        if ($depTask -and -not $depTask.done) { $depsReady = $false }
                    }
                    if ($depsReady) {
                        $other.status = "ready"
                        Write-Host "  [UNLOCKED] $($other.id): $($other.name)" -ForegroundColor Yellow
                    }
                }
            }
        } else {
            Write-Host "  [PENDING] $($task.id): $($task.name)" -ForegroundColor DarkYellow
            if ($missingFiles.Count -gt 0) {
                $missingFiles | ForEach-Object { Write-Host "             missing: $_" -ForegroundColor DarkGray }
            }
        }
    }

    if ($anyUpdated) { Write-State $state }
    Write-Host "`nVerify complete.`n" -ForegroundColor Cyan
}

function Set-Done($id) {
    if (-not $id) { Write-Host "Usage: .\task_manager.ps1 done <task-id>" -ForegroundColor Red; return }
    $state = Read-State
    $task = $state.tasks | Where-Object { $_.id -eq $id }
    if (-not $task) { Write-Host "Task '$id' not found." -ForegroundColor Red; return }
    $task.done = $true
    $task.status = "done"
    "$id done at $(Get-Date -Format 'yyyy-MM-dd HH:mm')" | Set-Content "$SignalsDir\$id.done"
    Write-State $state
    Write-Host "Task '$id' marked as done." -ForegroundColor Green
}

function Show-Dispatch {
    $state = Read-State
    Write-Host "`n=== Workflows для запуска ===" -ForegroundColor Cyan
    $state.tasks | Where-Object { $_.status -eq "ready" -and -not $_.done } | ForEach-Object {
        Write-Host "  $($_.workflow)  →  $($_.name)" -ForegroundColor Green
    }
    Write-Host ""
}

function Read-Inbox {
    Write-Host "`n=== Inbox сообщения ===" -ForegroundColor Cyan
    $msgs = Get-ChildItem $InboxDir -Filter "*.json" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    if ($msgs.Count -eq 0) { Write-Host "  (пусто)" -ForegroundColor DarkGray }
    foreach ($msg in $msgs) {
        $m = Get-Content $msg.FullName -Raw | ConvertFrom-Json
        $color = switch ($m.type) { "done" {"Green"} "blocked" {"Red"} "error" {"Red"} default {"Yellow"} }
        Write-Host "  [$($m.type.ToUpper())] $($m.agent): $($m.message)" -ForegroundColor $color
    }
    Write-Host ""
}

switch ($Command) {
    "status"   { Show-Status }
    "verify"   { Invoke-Verify }
    "done"     { Set-Done $TaskId }
    "dispatch" { Show-Dispatch }
    "inbox"    { Read-Inbox }
    default    { Write-Host "Commands: status | verify | done <id> | dispatch | inbox" -ForegroundColor Yellow }
}
