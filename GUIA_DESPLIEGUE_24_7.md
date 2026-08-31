# Guia de Despliegue 24/7 en la Nube — Kuri 1.0.1

Esta guia te explica paso a paso como tener Kuri funcionando **24/7 en la nube de forma 100% gratuita**, sin necesidad de tener tu computadora encendida.

---

## Arquitectura 24/7 Gratuita

1. **Base de Datos**: [Neon.tech](https://neon.tech) (PostgreSQL gratuito en la nube, para que nunca pierdas datos).
2. **Servidor y Bot**: [Render.com](https://render.com) (Web Service gratuito con HTTPS y Webhook de Telegram automatico).
3. **Mantenimiento 24/7 (Keep-Alive)**: [cron-job.org](https://cron-job.org) o [UptimeRobot](https://uptimerobot.com) (hace ping cada 10 minutos para que el servidor nunca se duerma y envie los recordatorios diarios).

---

## Paso 1: Crear la Base de Datos en Neon (2 minutos)

1. Ve a [neon.tech](https://neon.tech) y crea una cuenta gratis con GitHub o Google.
2. Crea un nuevo proyecto llamado `kuri-db`.
3. En el panel principal veras la cadena de conexion (**Connection string**).
4. Copia esa URL completa. Tiene esta forma:
   ```text
   postgresql://neondb_owner:password@ep-xyz.aws.neon.tech/neondb?sslmode=require
   ```
*(Guardala para el Paso 3).*

---

## Paso 2: Subir tu codigo a GitHub

1. Crea un repositorio en [github.com](https://github.com/new) (puede ser privado o publico).
2. Sube los archivos de este proyecto a tu repositorio.

---

## Paso 3: Desplegar en Render (3 minutos)

1. Entra a [render.com](https://render.com) y crea tu cuenta gratuita.
2. Haz clic en el boton **New +** y selecciona **Web Service**.
3. Conecta tu cuenta de GitHub y elige tu repositorio de Kuri.
4. Completa la configuracion inicial:
   - **Name**: `kuri-finanzas` (o el nombre que prefieras).
   - **Region**: Oregon (US West) u Ohio.
   - **Branch**: `main` (o tu rama de produccion).
   - **Runtime**: `Python 3`.
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: `Free`.
5. En la seccion **Environment Variables** (Variables de entorno), agrega las siguientes:

| Clave | Valor |
|---|---|
| `DATABASE_URL` | La URL de Postgres que copiaste de Neon (Paso 1) |
| `TELEGRAM_TOKEN` | Tu token de @BotFather |
| `GEMINI_API_KEY` | Tu API key gratuita de Google AI Studio |
| `BASE_URL` | La URL que te asigna Render (ej: `https://kuri-finanzas.onrender.com`) |
| `DASHBOARD_TOKEN` | Una clave secreta para entrar a tu panel (ej: `mi_clave_secreta_kuri_2026`) |
| `TIMEZONE` | `America/Guayaquil` (o tu zona horaria) |
| `CURRENCY` | `USD` |
| `APP_NAME` | `Kuri` |

6. Haz clic en **Create Web Service**.
7. Render instalara las dependencias y arrancara el servidor. Al detectar `https://` en `BASE_URL`, Kuri registrara el Webhook de Telegram automaticamente.

---

## Paso 4: Configurar Keep-Alive 24/7 (Para que nunca se duerma)

En el plan gratuito de Render, los servidores entran en reposo si pasan 15 minutos sin peticiones. Para mantenerlo despierto las 24 horas y enviar tus recordatorios diarios:

1. Ve a [cron-job.org](https://cron-job.org) y crea una cuenta gratis.
2. Crea dos tareas programadas (**Cronjobs**):

### Tarea A: Keep-Alive (Cada 10 minutos)
- **Title**: `Kuri Ping`
- **URL**: `https://tu-kuri.onrender.com/health`
- **Schedule**: Cada 10 minutos (`Every 10 minutes`).
- **Method**: `GET`

### Tarea B: Recordatorios Diarios (Todos los dias a las 09:00 AM)
- **Title**: `Kuri Recordatorios`
- **URL**: `https://tu-kuri.onrender.com/tareas/recordatorios?t=TU_DASHBOARD_TOKEN`
- **Schedule**: Diario a las 09:00 AM (`Daily at 09:00`).
- **Method**: `GET`

---

## Paso 5: Probar tu Bot y Panel en la Nube

1. **En Telegram**: Entra a tu bot y escribe `/start` o manda un gasto. Respondera de inmediato a traves de la nube.
2. **En tu navegador**: Abre tu panel desde cualquier dispositivo (celular, laptop, tablet):
   ```text
   https://tu-kuri.onrender.com/?t=TU_DASHBOARD_TOKEN
   ```

Listo. Tu bot y dashboard estaran funcionando 24/7 de forma completamente automatica y gratuita.

