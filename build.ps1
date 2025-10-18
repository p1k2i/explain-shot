#!/usr/bin/env pwsh
<#
.SYNOPSIS
PyInstaller Build Script for ExplainShot

.DESCRIPTION
This script automates the PyInstaller build process for the ExplainShot application.

.PARAMETER Clean
Remove previous build artifacts before building

.PARAMETER Full
Perform a full rebuild (equivalent to --clean --rebuild)

.PARAMETER Help
Show help information

.EXAMPLE
./build.ps1 -Clean        # Build with cleanup
./build.ps1 -Full         # Full rebuild
./build.ps1               # Normal build

.NOTES
Requires Python virtual environment to be set up in ./venv
#>

param(
    [switch]$Clean,
    [switch]$Full,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

function Show-Help {
    Write-Host @"
ExplainShot PyInstaller Build Script

Usage: .\build.ps1 [options]

Options:
  -Clean      Remove previous build artifacts
  -Full       Clean and rebuild everything
  -Help       Show this help message

Examples:
  .\build.ps1                 # Normal build
  .\build.ps1 -Clean          # Build with cleanup
  .\build.ps1 -Full           # Full rebuild
"@
}

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
}

# Show banner
Write-Section "ExplainShot PyInstaller Build Script"

if ($Help) {
    Show-Help
    exit 0
}

# Check virtual environment
if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "ERROR: Virtual environment not found!" -ForegroundColor Red
    Write-Host "Please create it with: python -m venv venv" -ForegroundColor Yellow
    exit 1
}

# Handle full rebuild
if ($Full) {
    $Clean = $true
}

# Clean previous builds
if ($Clean) {
    Write-Host "Cleaning previous builds..." -ForegroundColor Yellow

    @("dist", "build") | ForEach-Object {
        if (Test-Path $_) {
            Write-Host "  Removing $_ folder..." -ForegroundColor Gray
            Remove-Item -Path $_ -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    Get-Item "*.spec.bak" -ErrorAction SilentlyContinue |
        ForEach-Object {
            Write-Host "  Removing backup spec file: $_" -ForegroundColor Gray
            Remove-Item -Path $_ -Force
        }

    Write-Host "Cleanup complete." -ForegroundColor Green
    Write-Host ""
}

# Check PyInstaller
Write-Host "Checking PyInstaller installation..." -ForegroundColor Yellow

try {
    & venv\Scripts\pip.exe show pyinstaller | Out-Null
} catch {
    Write-Host "PyInstaller not found. Installing..." -ForegroundColor Yellow
    & venv\Scripts\pip.exe install pyinstaller --upgrade

    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to install PyInstaller" -ForegroundColor Red
        exit 1
    }
}

Write-Host "PyInstaller ready." -ForegroundColor Green
Write-Host ""

# Run PyInstaller
Write-Host "Starting build process..." -ForegroundColor Yellow
Write-Host ""

$ErrorActionPreference = "Continue"
& venv\Scripts\pyinstaller.exe explain-shot.spec --distpath dist --workpath build -y 2>&1 | Out-Null

if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1) {
    Write-Host ""
    Write-Host "ERROR: Build failed!" -ForegroundColor Red
    exit 1
}

# Clean up redundant exe file in dist root (PyInstaller creates both dist/ExplainShot.exe and dist/ExplainShot/ExplainShot.exe)
if (Test-Path "dist\ExplainShot.exe") {
    Remove-Item -Path "dist\ExplainShot.exe" -Force
}

# Success message
Write-Section "Build Completed Successfully!"

Write-Host "Executable location: " -NoNewline
Write-Host "dist\ExplainShot\ExplainShot.exe" -ForegroundColor Green
Write-Host ""

Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Test the executable: dist\ExplainShot.exe" -ForegroundColor Gray
Write-Host "  2. For distribution, zip the dist folder" -ForegroundColor Gray
Write-Host "  3. See BUILD_INSTRUCTIONS.md for more details" -ForegroundColor Gray
Write-Host ""

Write-Host "Build successful!" -ForegroundColor Green
