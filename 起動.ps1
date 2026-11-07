$ErrorActionPreference = 'Stop'
$dvdPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $dvdPython)) {
    throw '仮想環境がありません。READMEのセットアップ手順を実行してください。'
}
& $dvdPython -m dvd_player
exit $LASTEXITCODE
