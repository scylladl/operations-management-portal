<#
    Creates the portal database if it does not exist and runs every numbered .sql script in this folder, in order.
    Re-running it updates procedures, views and reference data and keeps the accounts and actions.
    It reads NorthGridOps through synonyms and never writes to it.

    Usage:  powershell -ExecutionPolicy Bypass -File database\deploy.ps1 [-Server localhost] [-Database NorthGridPortal]
                                                                       [-SourceDatabase NorthGridOps]
#>
param(
    [string]$Server = "localhost",
    [string]$Database = "NorthGridPortal",
    [string]$SourceDatabase = "NorthGridOps"
)

$ErrorActionPreference = "Stop"
$scripts = Get-ChildItem -Path $PSScriptRoot -Filter "*.sql" | Where-Object { $_.Name -match '^\d{2}_' } | Sort-Object Name

function Invoke-Batches($connection, [string]$text) {
    # A GO line ends a batch, as in SSMS and sqlcmd
    foreach ($batch in [regex]::Split($text, '^\s*GO\s*$', [System.Text.RegularExpressions.RegexOptions]::Multiline)) {
        if ([string]::IsNullOrWhiteSpace($batch)) { continue }
        $command = $connection.CreateCommand()
        $command.CommandText = $batch
        $command.CommandTimeout = 300
        [void]$command.ExecuteNonQuery()
    }
}

$base = "Server=$Server;Integrated Security=True;Encrypt=True;TrustServerCertificate=True"
$master = New-Object System.Data.SqlClient.SqlConnection "$base;Database=master"
$master.Open()
try {
    # Readers do not block writers: the queues stay readable while a decision is being saved.
    Invoke-Batches $master "IF DB_ID(N'$Database') IS NULL
BEGIN
    CREATE DATABASE [$Database];
    ALTER DATABASE [$Database] SET READ_COMMITTED_SNAPSHOT ON;
END"
}
finally { $master.Close() }

$connection = New-Object System.Data.SqlClient.SqlConnection "$base;Database=$Database"
$connection.Open()
try {
    foreach ($script in $scripts) {
        Write-Host "Running $($script.Name)"
        $text = (Get-Content -Path $script.FullName -Raw -Encoding UTF8).Replace('$(SourceDatabase)', $SourceDatabase)
        Invoke-Batches $connection $text
    }
    Write-Host "Done: $($scripts.Count) script(s) on $Server/$Database"
}
finally { $connection.Close() }
