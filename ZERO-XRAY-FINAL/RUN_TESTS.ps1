$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$PythonExecutable = Join-Path $ProjectRoot "server\.venv\Scripts\python.exe"

if (-not (Test-Path $PythonExecutable)) {
    Write-Host "شغّل setup.bat مرة واحدة أولًا لإنشاء بيئة Python." -ForegroundColor Red
    exit 1
}

Write-Host "1/3 اختبار الخادم..." -ForegroundColor Cyan
Set-Location (Join-Path $ProjectRoot "server")
$env:PYTHONPATH = "."
& $PythonExecutable -m pytest tests -q

Write-Host "2/3 فحص الواجهة..." -ForegroundColor Cyan
Set-Location (Join-Path $ProjectRoot "client")
& npm run lint

Write-Host "3/3 بناء نسخة الإنتاج..." -ForegroundColor Cyan
& npm run build

Write-Host "اكتملت جميع الاختبارات بنجاح." -ForegroundColor Green
