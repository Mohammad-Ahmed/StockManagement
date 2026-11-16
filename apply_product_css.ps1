$path = ".\public\product\index.html"
if (-not (Test-Path $path)) { throw "Missing $path" }
$content = Get-Content $path -Raw
$link = '<link rel="stylesheet" href="/build14.css?v=14">'
if ($content -notmatch [regex]::Escape('/build14.css?v=14')) {
    $content = $content -replace '</head>', "  $link`r`n</head>"
    Set-Content -Path $path -Value $content -Encoding utf8
    Write-Host "Added Build 14 image CSS to product page."
} else {
    Write-Host "Build 14 image CSS is already linked."
}
