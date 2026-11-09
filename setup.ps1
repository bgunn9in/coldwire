param([Parameter(ValueFromRemainingArguments = $true)][string[]]$InstallerArgs)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    $version = $null
    if ($launcher) {
        # An unqualified -3 can prefer a free-threaded build.
        $version = & $launcher.Source -0p 2>$null | ForEach-Object {
            if ($_ -match '^\s*-(?:V:)?(3\.\d+)(?:-(?:32|64))?\s' -and [version]$Matches[1] -ge [version]'3.10') { $Matches[1] }
        } | Sort-Object { [version]$_ } -Descending -Unique | Select-Object -First 1
    }
    if ($version) { & $launcher.Source "-$version" -m venv .venv }
    else { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ with venv is required on the operator computer.' }
}
& $pythonPath -c 'import sys, sysconfig; sys.exit(0 if sys.version_info >= (3,10) and not sysconfig.get_config_var(sys.argv[1]) else 1)' Py_GIL_DISABLED
if ($LASTEXITCODE -ne 0) { throw 'Standard CPython 3.10+ with the GIL is required. An existing .venv is not replaced automatically.' }
& $pythonPath -m pip install --disable-pip-version-check -r requirements-deploy.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath deploy.py @InstallerArgs
exit $LASTEXITCODE
