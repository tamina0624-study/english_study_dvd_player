$ErrorActionPreference = 'Stop'
$dvdToolsPath = Join-Path $PSScriptRoot '.tools'
$dvdArchivePath = Join-Path $dvdToolsPath 'ffmpeg-full.7z'
$dvdExpectedHash = 'f0e46253c70dfe902bac915dfb4224f0cf1b7c6eeab9da2ccc9a5581f9a71b13'
# Gyan full build 9.0.2. A changed upstream archive must be reviewed before updating this hash.
$dvdUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z'
New-Item -ItemType Directory -Path $dvdToolsPath -Force | Out-Null
Invoke-WebRequest -Uri $dvdUrl -OutFile $dvdArchivePath -UseBasicParsing
if ((Get-FileHash -LiteralPath $dvdArchivePath -Algorithm SHA256).Hash -ne $dvdExpectedHash) {
    throw 'FFmpegのSHA256が一致しません。配布元の更新を確認してください。展開は行いません。'
}
& tar -xf $dvdArchivePath -C $dvdToolsPath
if ($LASTEXITCODE -ne 0) {
    throw '7zの展開に失敗しました。7z対応のWindows tarが必要です。'
}
Write-Output 'FFmpeg full版を導入しました。アプリを再起動してください。'
