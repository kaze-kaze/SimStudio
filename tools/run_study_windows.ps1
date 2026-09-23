<#
.SYNOPSIS
Runs an imported SimStudio study on Windows after checking the installed code fingerprint.

.DESCRIPTION
The default mode is a dry run. Pass -Execute to explicitly start Mechanical solves.
The Python environment must already have the same SimStudio code version installed;
this script does not install packages or change the PowerShell execution policy.

.PARAMETER StudyPath
Path to a study directory imported from a task or results ZIP.

.PARAMETER Execute
Explicitly enable real Mechanical execution. Without this switch, the study stays in dry-run mode.

.PARAMETER Python
Python executable for the installed SimStudio environment. Defaults to python on PATH.

.EXAMPLE
pwsh -File .\tools\run_study_windows.ps1 C:\Studies\bracket

.EXAMPLE
pwsh -File .\tools\run_study_windows.ps1 C:\Studies\bracket -Python C:\SimStudio\.venv\Scripts\python.exe -Execute
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $StudyPath,

    [switch] $Execute,

    [string] $Python = "python"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

function Stop-WithExitCode {
    param([int] $Code)
    exit $Code
}

$StudyPath = [System.IO.Path]::GetFullPath($StudyPath)
$ManifestPath = Join-Path $StudyPath "study-manifest.json"
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    [Console]::Error.WriteLine("Study manifest not found: $ManifestPath")
    Stop-WithExitCode 2
}

try {
    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
} catch {
    [Console]::Error.WriteLine("Cannot read study manifest: $($_.Exception.Message)")
    Stop-WithExitCode 2
}

if (-not $Manifest.code_fingerprint) {
    [Console]::Error.WriteLine("Study manifest has no code_fingerprint.")
    Stop-WithExitCode 2
}

try {
    $Code = "from ansys_skill.study.storage import code_fingerprint; print(code_fingerprint())"
    $FingerprintText = & $Python -c $Code
    $PythonExitCode = $LASTEXITCODE
    if ($PythonExitCode -ne 0) {
        [Console]::Error.WriteLine(($FingerprintText | Out-String).TrimEnd())
        Stop-WithExitCode $PythonExitCode
    }
    $CurrentFingerprint = ($FingerprintText | Out-String).Trim()
} catch {
    [Console]::Error.WriteLine("Cannot verify installed SimStudio code fingerprint: $($_.Exception.Message)")
    Stop-WithExitCode 2
}

if ($CurrentFingerprint -ne $Manifest.code_fingerprint) {
    [Console]::Error.WriteLine("Installed SimStudio code does not match this study. Install the same code version before running it.")
    Stop-WithExitCode 2
}

$Arguments = @("-m", "ansys_skill.cli", "study", "run", $StudyPath)
if ($Execute.IsPresent) {
    $Arguments += "--execute"
}
$Arguments += @("--resume", "--json")

& $Python @Arguments
$ExitCode = $LASTEXITCODE
exit $ExitCode
