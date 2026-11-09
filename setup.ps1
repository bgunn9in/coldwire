param([Parameter(ValueFromRemainingArguments = $true)][string[]]$InstallerArgs)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { & $launcher.Source -3 -m venv .venv }
    else { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ with venv is required on the operator computer.' }
}
& $pythonPath -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath -m pip install --disable-pip-version-check -r requirements-deploy.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath deploy.py @InstallerArgs
exit $LASTEXITCODE
