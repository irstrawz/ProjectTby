# Launches the game with the project's virtualenv, so you never have to
# remember to activate it first.
#
#   .\run.ps1                  play
#   .\run.ps1 --smoke 600      pass any main.py arguments straight through
#   .\run.ps1 selftest.py      or run a different script in the same env
#
# Works from any directory. A named script is resolved against the project and
# the project becomes the working directory, so
#
#   & "C:\path\to\ProjectTby\run.ps1" tools\build_exe.py
#
# behaves exactly as if it had been run from inside the folder.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# Look for a venv beside the project first, then inside it.
$candidates = @(
    (Join-Path (Split-Path -Parent $root) ".venv\Scripts\python.exe"),
    (Join-Path $root ".venv\Scripts\python.exe")
)
$python = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $python) {
    Write-Host "No virtualenv found. Looked in:" -ForegroundColor Yellow
    $candidates | ForEach-Object { Write-Host "  $_" }
    Write-Host ""
    Write-Host "Create one and install pygame with:"
    Write-Host "  py -m venv `"$(Split-Path -Parent $root)\.venv`""
    Write-Host "  & `"$(Split-Path -Parent $root)\.venv\Scripts\python.exe`" -m pip install pygame"
    exit 1
}

# Default to main.py when no script is named; otherwise pass everything along.
#
# A named script is resolved against the project rather than used as typed.
# Passing it through unchanged only works when the shell already happens to be
# sitting in the project folder — which is the assumption that turns
# "tools\build_exe.py" into a confusing "not recognized" error from anywhere
# else.
$scriptArgs = @($args)
$rest = @()
if ($scriptArgs.Count -gt 0 -and $scriptArgs[0] -like "*.py") {
    $target = $scriptArgs[0]
    if (-not [System.IO.Path]::IsPathRooted($target)) {
        $resolved = Join-Path $root $target
        if (Test-Path $resolved) { $target = $resolved }
    }
    if ($scriptArgs.Count -gt 1) { $rest = $scriptArgs[1..($scriptArgs.Count - 1)] }
} else {
    $target = Join-Path $root "main.py"
    $rest = $scriptArgs
}

# The tools read and write paths relative to the project, so run from there
# whatever directory this was invoked from. Restored afterwards, because moving
# an interactive shell somewhere the user did not ask to go is its own small
# rudeness.
$previous = Get-Location
Set-Location $root
try {
    & $python $target @rest
    $code = $LASTEXITCODE
} finally {
    Set-Location $previous
}
exit $code
