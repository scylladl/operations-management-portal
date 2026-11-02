<#
    AC-01: creates the portal database, loads the demo and runs the tests.

    Usage:  $env:PORTAL_DEMO_PASSWORD = "<a password of your choice>"
            powershell -ExecutionPolicy Bypass -File build.ps1 [-Server localhost] [-Reset] [-SkipTests]

    -Reset drops the demo database NorthGridPortal first, with every account and request in it. NorthGridOps is
    only read. The tests use their own database, NorthGridPortal_Test, created and dropped by the run.
#>
param(
    [string]$Server = "localhost",
    [switch]$Reset,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Create the virtual environment first: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }
if (-not $env:PORTAL_DEMO_PASSWORD) { throw "Set PORTAL_DEMO_PASSWORD; it becomes the password of every demo account." }

if ($Reset) {
    Write-Host "Dropping NorthGridPortal (demo data)"
    $master = New-Object System.Data.SqlClient.SqlConnection "Server=$Server;Database=master;Integrated Security=True;Encrypt=True;TrustServerCertificate=True"
    $master.Open()
    $command = $master.CreateCommand()
    $command.CommandText = "IF DB_ID(N'NorthGridPortal') IS NOT NULL BEGIN ALTER DATABASE NorthGridPortal SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE NorthGridPortal; END"
    [void]$command.ExecuteNonQuery()
    $master.Close()
}

& powershell -NoProfile -ExecutionPolicy Bypass -File "$root\database\deploy.ps1" -Server $Server
if ($LASTEXITCODE -ne 0) { throw "deploy failed" }

$env:PORTAL_DB_SERVER = $Server
& $python -X utf8 "$root\scripts\seed_demo.py"
if ($LASTEXITCODE -ne 0) { Write-Host "Demo not loaded (see the message above); the database keeps its current data." }

if (-not $SkipTests) {
    $env:PORTAL_TEST_SERVER = $Server
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "tests failed" }
}
