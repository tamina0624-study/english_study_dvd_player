$ErrorActionPreference = 'Stop'
$dvdToolsPath = Join-Path $PSScriptRoot '.tools'
$dvdArchivePath = Join-Path $dvdToolsPath 'SubtitleEdit-5.4.0.zip'
$dvdDestination = Join-Path $dvdToolsPath 'SubtitleEdit-5.4.0'
$dvdExpectedHash = '88015b354332a3028d83ce4b992ec5325d03411df190769c8a87fcd459c6b920'
$dvdUrl = 'https://github.com/SubtitleEdit/subtitleedit/releases/download/v5.4.0/SubtitleEdit-Windows-x64.zip'
New-Item -ItemType Directory -Path $dvdToolsPath -Force | Out-Null
Invoke-WebRequest -Uri $dvdUrl -OutFile $dvdArchivePath -UseBasicParsing
if ((Get-FileHash -LiteralPath $dvdArchivePath -Algorithm SHA256).Hash -ne $dvdExpectedHash) {
    throw 'Subtitle EditのSHA256が一致しません。展開を中止しました。'
}
Expand-Archive -LiteralPath $dvdArchivePath -DestinationPath $dvdDestination -Force
Write-Output 'Subtitle Editをプロジェクト内へ導入しました。プレイヤーを再起動してください。'
