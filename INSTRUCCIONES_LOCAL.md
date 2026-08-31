# Guia de Instalacion y Uso Local — Kuri 1.0

## 1. Requisitos Previos
- **Python 3.11 o superior** (asegurate de marcar "Add Python to PATH" al instalar).
- **Token de Telegram**: obtenido gratis creando un bot con [@BotFather](https://t.me/Botfather).
- **API Key de Google Gemini**: gratuita en [Google AI Studio](https://aistudio.google.com/apikey).

---

## 2. Instalacion Paso a Paso en Windows

### Paso 1: Abrir la terminal
Abre **PowerShell** o **CMD** en esta carpeta.

### Paso 2: Crear y activar el entorno virtual
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
*(Si usas CMD en lugar de PowerShell, ejecuta: `.venv\Scripts\activate.bat`)*

### Paso 3: Instalar dependencias
```powershell
pip install -r requirements.txt
```

### Paso 4: Configurar variables de entorno (`.env`)
Copia el archivo `.env.example` y renombralo a `.env`:
```powershell
Copy-Item .env.example .env
```
Abre `.env` con un editor de texto y completa:
1. `TELEGRAM_TOKEN`: Tu token de @BotFather.
2. `GEMINI_API_KEY`: Tu clave de Google AI Studio.
3. `DASHBOARD_TOKEN`: Una clave secreta para acceder a tu panel web (ej: `clave_secreta_kuri_2026`).

---

## 3. Como Ejecutar

### Opcion Rapida (Archivos .bat):
- Haz doble clic en `iniciar_bot.bat` para iniciar el bot de Telegram.
- Haz doble clic en `iniciar_dashboard.bat` para iniciar el panel web.

### Opcion Manual (Terminal):
1. **Terminal 1 — Bot de Telegram**:
   ```powershell
   .\.venv\Scripts\python.exe run_bot.py
   ```
2. **Terminal 2 — Dashboard Web**:
   ```powershell
   .\.venv\Scripts\python.exe run_web.py
   ```

---

## 4. Acceso al Dashboard Web
Abre tu navegador en:
```
http://localhost:8000/?t=TU_DASHBOARD_TOKEN
```
*(Reemplaza `TU_DASHBOARD_TOKEN` por el token que configuraste en tu `.env`)*

---

## 5. Primeros Pasos
1. Abre tu bot en Telegram y envia `/start`.
2. Configura tus datos con `/setup` (ingresos, gastos fijos, tarjetas).
3. Prueba registrando gastos por texto (`almuerzo 12.50`), nota de voz o subiendo recibos/facturas tanto en Telegram como desde el panel web.

