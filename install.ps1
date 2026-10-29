# ==============================================================================
# onu-top Automated Cross-Platform Installer (Windows & macOS Apple Silicon/Intel)
# Execution:
#   irm https://raw.githubusercontent.com/wahaj-xe/onu-top/main/install.ps1 | iex
# ==============================================================================

$ErrorActionPreference = "Stop"

$isDarwin = ($PSVersionTable.OS -like "*Darwin*") -or ($IsMacOS -eq $true)

Write-Host ""
Write-Host "+--------------------------------------------------------------+" -ForegroundColor Cyan
if ($isDarwin) {
    Write-Host "|         onu-top Installer (macOS / Apple Silicon)            |" -ForegroundColor Cyan
} else {
    Write-Host "|              onu-top Installer (Huawei ONT Monitor)          |" -ForegroundColor Cyan
}
Write-Host "|         Lightweight btop-style Live Performance Dashboard    |" -ForegroundColor Cyan
Write-Host "+--------------------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------------------------
# 1. Check Prerequisites: Python 3.8+
# ------------------------------------------------------------------------------
Write-Host "[1/4] Checking prerequisites..." -ForegroundColor Cyan
$pythonExe = $null

foreach ($cmd in @("python3", "python", "py")) {
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
    Write-Host ""
    Write-Host "  [!] Python 3 is required to run onu-top, but was not found on your system." -ForegroundColor Yellow
    
    $installChoice = Read-Host "  Would you like this script to automatically install Python now? [Y/n]"
    if ($installChoice -eq "" -or $installChoice -match "^[Yy]") {
        Write-Host "  [+] Starting automated Python 3 installation..." -ForegroundColor Cyan

        if ($isDarwin) {
            # macOS / Apple Silicon
            $brew = Get-Command "brew" -ErrorAction SilentlyContinue
            if ($brew) {
                Write-Host "      Installing Python 3 via Homebrew..." -ForegroundColor Yellow
                & brew install python3
                $pythonExe = "python3"
            } else {
                Write-Host "      Downloading official macOS Universal Python installer from python.org..." -ForegroundColor Yellow
                $pkgUrl = "https://www.python.org/ftp/python/3.12.3/python-3.12.3-macos11.pkg"
                $pkgPath = "/tmp/python-3.12.pkg"
                Invoke-RestMethod -Uri $pkgUrl -OutFile $pkgPath
                Write-Host "      Running installer (admin password may be requested)..." -ForegroundColor Yellow
                & sudo installer -pkg $pkgPath -target /
                Remove-Item -Path $pkgPath -Force -ErrorAction SilentlyContinue
                $pythonExe = "/usr/local/bin/python3"
            }
        } else {
            # Windows
            $wingetInstalled = $false
            $winget = Get-Command "winget" -ErrorAction SilentlyContinue
            if ($winget) {
                Write-Host "      Attempting installation via Windows Package Manager (winget)..." -ForegroundColor Yellow
                try {
                    $p = Start-Process -FilePath "winget" -ArgumentList "install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent" -Wait -PassThru
                    if ($p.ExitCode -eq 0) {
                        $wingetInstalled = $true
                    }
                } catch {}
            }

            if (-not $wingetInstalled) {
                Write-Host "      Downloading official Python installer from python.org..." -ForegroundColor Yellow
                $pyUrl = "https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe"
                $installerPath = Join-Path $env:TEMP "python-3.12-installer.exe"
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                (New-Object System.Net.WebClient).DownloadFile($pyUrl, $installerPath)

                Write-Host "      Running Python setup (quiet mode with PATH integration)..." -ForegroundColor Yellow
                $p = Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 SimpleInstall=1" -Wait -PassThru
                Remove-Item -Path $installerPath -Force -ErrorAction SilentlyContinue
            }

            # Refresh session PATH from Registry
            $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
            $userPathEnv = [Environment]::GetEnvironmentVariable("Path", "User")
            $env:Path = "$machinePath;$userPathEnv"

            # Search for installed python executable
            foreach ($cand in @(
                "python",
                "py",
                (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
                (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
                "C:\Python312\python.exe",
                "C:\Python311\python.exe"
            )) {
                if (Get-Command $cand -ErrorAction SilentlyContinue) {
                    $pythonExe = $cand
                    break
                } elseif (Test-Path $cand) {
                    $pythonExe = $cand
                    break
                }
            }
        }

        if ($pythonExe) {
            Write-Host "  [OK] Python installed successfully!" -ForegroundColor Green
        } else {
            Write-Host "  [!] Python installation completed. If command is not recognized, please restart your terminal." -ForegroundColor Yellow
            $pythonExe = if ($isDarwin) { "python3" } else { "python" }
        }
    } else {
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

if ($isDarwin) {
    $installDir = Join-Path $env:HOME ".local/bin"
} else {
    $installDir = Join-Path $env:LOCALAPPDATA "Programs\onu-top"
}

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

if ($isDarwin) {
    # Unix launcher for macOS
    $shShim = "#!/usr/bin/env sh`r`nDIR=`"`$(cd `"`$(dirname `"`$0`")`" && pwd)`"`r`nexec python3 `"`$DIR/huawei_ont_top.py`" `"`$@`""
    $launcherPath = Join-Path $installDir "onu-top"
    Set-Content -Path $launcherPath -Value $shShim -Encoding UTF8
    & chmod +x $launcherPath
    & chmod +x $targetScript

    # Add ~/.local/bin to ~/.zshrc if not present
    $zshrc = Join-Path $env:HOME ".zshrc"
    if (Test-Path $zshrc) {
        $content = Get-Content $zshrc -Raw
        if ($content -notmatch "\.local/bin") {
            Add-Content -Path $zshrc -Value "`nexport PATH=`"`$HOME/.local/bin:`$PATH`""
        }
    }
    Write-Host "  [OK] Created executable '$launcherPath'." -ForegroundColor Green
} else {
    # Windows Launchers
    $cmdShim = "@echo off`r`npython `"%~dp0huawei_ont_top.py`" %*"
    Set-Content -Path (Join-Path $installDir "onu-top.cmd") -Value $cmdShim -Encoding ASCII
    Set-Content -Path (Join-Path $installDir "onu.cmd") -Value $cmdShim -Encoding ASCII

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
    } catch {}
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
        if ($isDarwin) {
            & (Join-Path $installDir "onu-top")
        } else {
            & (Join-Path $installDir "onu-top.cmd")
        }
    }
} catch {}
