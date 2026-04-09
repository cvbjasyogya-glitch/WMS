@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv" (
    py -m venv .venv
)

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)

py -m pip install --upgrade pip
py -m pip install -r requirements.txt

py -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name KasirERP ^
  --add-data "kasir_config.example.json;." ^
  app.py

echo.
echo Build selesai.
echo EXE ada di: dist\KasirERP\KasirERP.exe
echo Copy kasir_config.example.json menjadi kasir_config.json di samping file EXE jika ingin override config runtime.
echo.
pause
