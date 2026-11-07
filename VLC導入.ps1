$ErrorActionPreference = 'Stop'
# Official portable release; hash checked against VideoLAN's published SHA256.
$dvdVersion = '3.0.24'
$dvdExpectedHash = 'fcf30850371ad10c9373cc4f0f4501e7dee49e3e9ae9f20c72fb2661a1ca6323'
$dvdToolsPath = Join-Path $PSScriptRoot '.tools'
$dvdArchivePath = Join-Path $dvdToolsPath "vlc-$dvdVersion-win64.zip"
$dvdReleaseUrl = "https://download.videolan.org/pub/videolan/vlc/$dvdVersion/win64/vlc-$dvdVersion-win64.zip"
New-Item -ItemType Directory -Path $dvdToolsPath -Force | Out-Null
Invoke-WebRequest -Uri $dvdReleaseUrl -OutFile $dvdArchivePath -UseBasicParsing
$dvdActualHash = (Get-FileHash -LiteralPath $dvdArchivePath -Algorithm SHA256).Hash
if ($dvdActualHash -ne $dvdExpectedHash) {
    throw 'VLCのSHA256が一致しません。展開を中止しました。'
}
Expand-Archive -LiteralPath $dvdArchivePath -DestinationPath $dvdToolsPath -Force
Write-Output "VLC $dvdVersion をプロジェクト内へ導入しました。アプリを再起動してください。"
