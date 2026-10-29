# ==============================================================================
# onu-top Automated Windows Installer
# Execution:
#   irm https://raw.githubusercontent.com/wahaj-xe/onu-top/main/install.ps1 | iex
# ==============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "+--------------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "|              onu-top Installer (Huawei ONT Monitor)          |" -ForegroundColor Cyan
Write-Host "|         Lightweight btop-style Live Performance Dashboard    |" -ForegroundColor Cyan
Write-Host "+--------------------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------------------------
# 1. Check Prerequisites: Python 3.8+
# ------------------------------------------------------------------------------
Write-Host "[1/4] Checking prerequisites..." -ForegroundColor Cyan
$pythonExe = $null

foreach ($cmd in @("python", "py", "python3")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        try {
            $verOutput = & $cmd --version 2>&1
            if ($verOutput -match "Python\s+(\d+)\.(\d+)") {
                $major = [int]$matches[1]
                $minor = [int]$matches[2]
                if ($major -ge 3 -and $minor -ge 8) {
                    $pythonExe = $cmd
                    Write-Host "  [OK] Python found: $verOutput ($($found.Source))" -ForegroundColor Green
                    break
                }
            }
        } catch {}
    }
}

if (-not $pythonExe) {
    Write-Host "  [X] Python 3.8+ was not found on your system." -ForegroundColor Red
    Write-Host ""

    # Attempt automatic winget install if available
    $winget = Get-Command "winget" -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "  Attempting automated Python installation via Windows Package Manager (winget)..." -ForegroundColor Yellow
        try {
            & winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
            $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
            $userPathEnv = [Environment]::GetEnvironmentVariable("Path", "User")
            $env:Path = "$machinePath;$userPathEnv"
            if (Get-Command "python" -ErrorAction SilentlyContinue) {
                $pythonExe = "python"
                Write-Host "  [OK] Python installed successfully via winget!" -ForegroundColor Green
            }
        } catch {
            Write-Host "  Automated winget installation failed: $_" -ForegroundColor Red
        }
    }

    if (-not $pythonExe) {
        Write-Host "------------------------------------------------------------" -ForegroundColor Yellow
        Write-Host "  PREREQUISITE REQUIRED:" -ForegroundColor Yellow
        Write-Host "  Please install Python 3.9 or higher to run onu-top:" -ForegroundColor Yellow
        Write-Host "    1. Download from: https://www.python.org/downloads/" -ForegroundColor White
        Write-Host "    2. IMPORTANT: Check 'Add Python to PATH' in installer!" -ForegroundColor Yellow
        Write-Host "    3. Re-run this installer once Python is installed." -ForegroundColor White
        Write-Host "------------------------------------------------------------" -ForegroundColor Yellow
        return
    }
}

# ------------------------------------------------------------------------------
# 2. Setup Target Installation Directory
# ------------------------------------------------------------------------------
Write-Host "[2/4] Setting up installation directory..." -ForegroundColor Cyan
$installDir = Join-Path $env:LOCALAPPDATA "Programs\onu-top"
if (-not (Test-Path $installDir)) {
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
}
Write-Host "  Directory: $installDir" -ForegroundColor Gray

# Download or copy huawei_ont_top.py
$targetScript = Join-Path $installDir "huawei_ont_top.py"
$localScript = if ($PSScriptRoot) { Join-Path $PSScriptRoot "huawei_ont_top.py" } else { $null }

if ($localScript -and (Test-Path $localScript)) {
    Write-Host "  Copying huawei_ont_top.py from local path..." -ForegroundColor Gray
    Copy-Item -Path $localScript -Destination $targetScript -Force
} else {
    Write-Host "  Downloading latest release from GitHub..." -ForegroundColor Gray
    $repoUrl = "https://raw.githubusercontent.com/wahaj-xe/onu-top/main/huawei_ont_top.py"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-RestMethod -Uri $repoUrl -OutFile $targetScript
}

if (-not (Test-Path $targetScript)) {
    Write-Host "  [X] Failed to install huawei_ont_top.py" -ForegroundColor Red
    return
}
Write-Host "  [OK] huawei_ont_top.py installed." -ForegroundColor Green

# ------------------------------------------------------------------------------
# 3. Create Terminal Shims and Configure PATH
# ------------------------------------------------------------------------------
Write-Host "[3/4] Configuring command shortcuts and PATH..." -ForegroundColor Cyan

# Batch launcher for cmd.exe, PowerShell, Run dialog
$cmdShim = "@echo off`r`npython `"%~dp0huawei_ont_top.py`" %*"
Set-Content -Path (Join-Path $installDir "onu-top.cmd") -Value $cmdShim -Encoding ASCII
Set-Content -Path (Join-Path $installDir "onu.cmd") -Value $cmdShim -Encoding ASCII

# PowerShell script launcher
$psShim = '& python "$PSScriptRoot\huawei_ont_top.py" @args'
Set-Content -Path (Join-Path $installDir "onu-top.ps1") -Value $psShim -Encoding UTF8

# Add to User PATH if not present
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$pathParts = $userPath -split ';' | Where-Object { $_ -ne '' }
if ($pathParts -notcontains $installDir) {
    $newUserPath = ($pathParts + $installDir) -join ';'
    [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
    $env:Path = "$env:Path;$installDir"
    Write-Host "  [OK] Added '$installDir' to your User PATH." -ForegroundColor Green
} else {
    Write-Host "  [OK] PATH is already configured." -ForegroundColor Gray
}

# Create Desktop Shortcut
try {
    $desktopDir = [Environment]::GetFolderPath("Desktop")
    if ($desktopDir -and (Test-Path $desktopDir)) {
        $wsh = New-Object -ComObject WScript.Shell
        $shortcut = $wsh.CreateShortcut((Join-Path $desktopDir "onu-top.lnk"))
        $shortcut.TargetPath = (Join-Path $installDir "onu-top.cmd")
        $shortcut.WorkingDirectory = $installDir
        $shortcut.Description = "Huawei ONT btop-style Live Health and Performance Monitor"
        $shortcut.Save()
        Write-Host "  [OK] Created Desktop shortcut 'onu-top'." -ForegroundColor Green
    }
} catch {
    # Non-critical if COM shortcut creation fails
}

# ------------------------------------------------------------------------------
# 4. Completion and Verification
# ------------------------------------------------------------------------------
Write-Host "[4/4] Finalizing..." -ForegroundColor Cyan
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  SUCCESS: onu-top is installed and ready to use!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  To run it, open any terminal and type:" -ForegroundColor White
Write-Host "      onu-top" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Important Prerequisites Reminder:" -ForegroundColor Cyan
Write-Host "   * Ensure Telnet access is enabled on your Huawei ONT" -ForegroundColor Gray
Write-Host "     (Web GUI: Security / Maintenance -> Device Access Control)" -ForegroundColor Gray
Write-Host "   * Have your ONT IP (e.g. 192.168.18.1), Telnet user, and password ready." -ForegroundColor Gray
Write-Host ""

# Optional immediate launch if running interactively
try {
    $run = Read-Host "Would you like to launch onu-top now? [Y/n]"
    if ($run -eq '' -or $run -match '^[Yy]') {
        & (Join-Path $installDir "onu-top.cmd")
    }
} catch {}
