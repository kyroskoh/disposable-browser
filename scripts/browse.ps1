# One disposable browser for a human on Windows (Docker Desktop), no controller needed.
# Close the Chromium window (or Ctrl+C) and the whole session is deleted.
param([int]$Port = 6080, [string]$Image = "disposable-browser/browser:dev")

$bytes = New-Object byte[] 4
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$pw = -join ($bytes | ForEach-Object { $_.ToString("x2") })
$url = "http://127.0.0.1:$Port/vnc.html?autoconnect=1&resize=remote&password=$pw"
Write-Host "Opening $url"
Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 4; Start-Process $u } -ArgumentList $url | Out-Null
docker run --rm -it --read-only --tmpfs "/tmp:rw,nosuid,nodev,mode=1777" --shm-size=1g `
  -p "127.0.0.1:${Port}:6080" -e "VNC_PASSWORD=$pw" -e ENABLE_CDP=0 $Image
