<#
  Buduje przenosny folder S7Trace (Python "embeddable" + zainstalowane pakiety + aplikacja),
  ktory dziala na komputerze bez Pythona i bez internetu.

  Wymaga (tylko na komputerze budujacym): internetu (pobranie kol pakietow z PyPI)
  oraz ZIP-a "Windows embeddable package" z python.org (domyslnie ten z NOTE_VIS).

  Uzycie:
    powershell -ExecutionPolicy Bypass -File build-portable.ps1
    ... -EmbedZip C:\sciezka\python-3.12.10-embed-amd64.zip
    ... -WithTests      (dodaje pytest - do sprawdzenia kompilacji, nie do wydania)
    ... -NoZip          (bez pakowania do ZIP)
#>
param(
    [string]$EmbedZip = 'C:\Dev\CLAUDE\NOTE_PSC_VIS\INSTALL\NOTE_VIS_INSTALL\offline\python-3.12.10-embed-amd64.zip',
    [string]$Out = (Join-Path $PSScriptRoot 'dist\S7Trace'),
    [switch]$WithTests,
    [switch]$NoZip
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path -LiteralPath $EmbedZip)) { throw "Nie znaleziono ZIP-a Pythona: $EmbedZip (podaj -EmbedZip)" }
if ($EmbedZip -notmatch 'python-(\d+)\.(\d+)\.(\d+)-embed-amd64\.zip$') { throw 'Oczekiwano python-X.Y.Z-embed-amd64.zip' }
$pyMajorMinor = "$($Matches[1]).$($Matches[2])"
$pyTag = "$($Matches[1])$($Matches[2])"

$hostPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $hostPy)) { $hostPy = 'python' }

Write-Host "== 1/6 Rozpakowanie Pythona $pyMajorMinor do $Out\python"
if (Test-Path $Out) { Remove-Item -LiteralPath $Out -Recurse -Force }
New-Item -ItemType Directory -Force "$Out\python", "$Out\app" | Out-Null
Expand-Archive -LiteralPath $EmbedZip -DestinationPath "$Out\python" -Force

Write-Host '== 2/6 python*._pth: site-packages + katalog aplikacji'
# Tryb "embeddable" ignoruje PYTHONPATH i katalog skryptu - sciezki musza byc w ._pth.
$pth = Get-ChildItem "$Out\python" -Filter 'python*._pth' | Select-Object -First 1
@("python$pyTag.zip", '.', 'Lib\site-packages', '..\app', 'import site') | Set-Content -LiteralPath $pth.FullName -Encoding ascii
New-Item -ItemType Directory -Force "$Out\python\Lib\site-packages" | Out-Null

Write-Host '== 3/6 Instalacja pakietow (kola dla Windows / Python ' $pyMajorMinor ')'
$pipArgs = @('-r', 'requirements-portable.txt')
if ($WithTests) { $pipArgs += 'pytest' }
& $hostPy -m pip install --target "$Out\python\Lib\site-packages" --python-version $pyMajorMinor `
    --platform win_amd64 --implementation cp --only-binary=:all: --no-warn-script-location --disable-pip-version-check `
    @pipArgs
if ($LASTEXITCODE -ne 0) { throw "pip zakonczyl sie bledem ($LASTEXITCODE)" }

Write-Host '== 4/6 Odchudzanie PySide6 (nieuzywane moduly Qt)'
$ps = "$Out\python\Lib\site-packages\PySide6"
$before = (Get-ChildItem $ps -Recurse -File | Measure-Object Length -Sum).Sum
foreach ($d in 'qml', 'translations', 'include', 'typesystems', 'scripts', 'metatypes', 'glue', 'resources') {
    if (Test-Path "$ps\$d") { Remove-Item "$ps\$d" -Recurse -Force }
}
# narzedzia deweloperskie Qt i podpowiedzi typow
Get-ChildItem $ps -File | Where-Object { $_.Name -match '^(designer|assistant|linguist|lupdate|lrelease|qmllint|qmlls|qmlformat|qmlcachegen|qmltyperegistrar|qmlimportscanner|qmltc|balsam|balsamui|qsb|rcc|uic|svgtoqml|qdbus|qdbusviewer|qtdiag|qtpaths)\.exe$' -or $_.Extension -eq '.pyi' -or $_.Name -match '^pyside6(qml|qmlmacros)\.abi3\.dll$' } | Remove-Item -Force
# moduly Qt, ktorych aplikacja nie uzywa (zostaja Core/Gui/Widgets/Svg/OpenGL/Network/PrintSupport/DBus)
$drop = 'Quick|Qml|WebEngine|WebChannel|3D|Pdf|Designer|Test|Help|Sql|Multimedia|Bluetooth|Nfc|Sensors|SerialPort|Location|Positioning|Charts|DataVisualization|RemoteObjects|Scxml|StateMachine|TextToSpeech|VirtualKeyboard|WebSockets|Concurrent|Xml|ShaderTools|Graphs|SpatialAudio|HttpServer|Labs|LanguageServer|Lottie|Protobuf|Grpc|UiTools'
Get-ChildItem $ps -File -Filter '*.dll' | Where-Object { $_.Name -match "^Qt6($drop)" } | Remove-Item -Force
Get-ChildItem $ps -Filter 'Qt*.pyd' | Where-Object { $_.Name -notmatch '^Qt(Core|Gui|Widgets|Svg|OpenGL|OpenGLWidgets|Network|PrintSupport)\.' } | Remove-Item -Force
# python312.dll laduje vcruntime140 z katalogu python\ - ma byc nie starszy niz msvcp140 z PySide6
foreach ($f in 'vcruntime140.dll', 'vcruntime140_1.dll') {
    if (Test-Path "$ps\$f") { Copy-Item "$ps\$f" "$Out\python\$f" -Force }
}
$after = (Get-ChildItem $ps -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("   PySide6: {0:N0} MB -> {1:N0} MB" -f ($before / 1MB), ($after / 1MB))

& $hostPy -c "import pefile" 2>$null
if ($LASTEXITCODE -eq 0) {
    & $hostPy tools\check_deps.py "$Out\python"
    if ($LASTEXITCODE -ne 0) { throw 'Qt w paczce wymaga funkcji niedostepnych na starszych Windowsach (patrz requirements-portable.txt).' }
    & $hostPy tools\imports_list.py "$Out\python" "$Out\imports.csv"
} else {
    Write-Host '   (pominieto check_deps: pip install pefile)'
}

# TimescaleDB: sterownik PostgreSQL ma sie dac zaimportowac w paczce (psycopg z libpq; zapas: pg8000)
$pgOk = $true
try { & "$Out\python\python.exe" -c 'import psycopg' 2>$null; if ($LASTEXITCODE -ne 0) { $pgOk = $false } } catch { $pgOk = $false }
if ($pgOk) { Write-Host '   Sterownik PostgreSQL w paczce: psycopg (pelny)' } else { Write-Host '   Sterownik PostgreSQL w paczce: psycopg sie nie laduje - zostaje pg8000 (zapas)' }

Write-Host '== 5/6 Aplikacja i skrypty startowe'
Copy-Item main.py "$Out\app\main.py"
Copy-Item s7trace "$Out\app\s7trace" -Recurse
Get-ChildItem "$Out\app" -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Copy-Item README.md "$Out\app\README.md"
Copy-Item tools\diagnoza.py "$Out\app\diagnoza.py"
Copy-Item tools\diagnoza_timescale.py "$Out\app\diagnoza_timescale.py"
Copy-Item tools\diagnoza_influx.py "$Out\app\diagnoza_influx.py"
Copy-Item portable\* $Out

Write-Host '== 6/6 Kompilacja .pyc (szybszy pierwszy start)'
& "$Out\python\python.exe" -m compileall -q "$Out\python\Lib\site-packages" "$Out\app" | Out-Null

# manifest (sciezka,rozmiar) - Diagnoza.bat wykrywa pliki usuniete / uszkodzone przy kopiowaniu
$rows = Get-ChildItem "$Out\python", "$Out\app" -Recurse -File | Where-Object { $_.Extension -ne '.pyc' } |
    ForEach-Object { $_.FullName.Substring($Out.Length + 1) + ',' + $_.Length }
Set-Content -LiteralPath "$Out\MANIFEST.csv" -Value $rows -Encoding utf8

$size = (Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("Gotowe: {0}  ({1:N0} MB)" -f $Out, ($size / 1MB))

if (-not $NoZip -and -not $WithTests) {
    $zip = Join-Path (Split-Path $Out) ("S7Trace-portable-{0}.zip" -f (Get-Date -Format 'yyyy-MM-dd'))
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Write-Host "Pakowanie do $zip ..."
    # .NET zamiast Compress-Archive: ten drugi potrafi sie wywrocic na plikach chwilowo
    # skanowanych przez antywirus (python.exe).
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    for ($try = 1; $try -le 3; $try++) {
        try {
            [System.IO.Compression.ZipFile]::CreateFromDirectory($Out, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $true)
            break
        } catch {
            if ($try -eq 3) { throw }
            Write-Host "   ponawiam pakowanie ($($_.Exception.Message))"
            if (Test-Path $zip) { Remove-Item $zip -Force }
            Start-Sleep 3
        }
    }
    Write-Host ("ZIP: {0:N0} MB" -f ((Get-Item $zip).Length / 1MB))
}
