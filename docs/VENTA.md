# Guía para vender e instalar Kuri a un cliente

Kuri está pensado para venderse **una instancia por cliente**: cada persona
tiene su propio bot, su propia base de datos y su propio panel. Nadie comparte
datos con nadie, y ese aislamiento es tu mejor argumento de venta cuando hablas
de plata ajena.

---

## Lo que entregas

| Pieza | Qué es |
|---|---|
| Bot de Telegram | Con el nombre y la @ que elija el cliente |
| Panel web | `https://<algo>.onrender.com/?t=<token>` |
| Configuración cargada | Sueldo, fijos, tarjetas y colchón ya metidos |
| Guía de uso | La sección "Qué hace" del README, o mándale `/ayuda` |

---

## Costo real por cliente

| Servicio | Plan | Costo |
|---|---|---|
| Render Web Service | Free | $0 |
| Neon Postgres | Free (0.5 GB) | $0 |
| Gemini (AI Studio) | Free tier | $0 |
| cron-job.org | Free | $0 |

Cero por cliente. Si un cliente quiere que el bot responda siempre al instante
(sin el arranque en frío del plan gratuito de Render), el plan Starter cuesta
alrededor de US$7/mes: súbelo al precio o cóbralo aparte.

**Límites que sí debes vigilar**
- El tier gratuito de Gemini tiene cupo diario de peticiones. Un usuario normal
  (10–30 gastos al día) entra sin problema; si el cliente manda decenas de fotos
  al día, dale su propia API key o activa facturación.
- Neon Free pausa el proyecto tras inactividad prolongada; el ping diario de
  recordatorios lo mantiene despierto.
- **Cada cliente con su propia `GEMINI_API_KEY`.** No compartas la tuya: el cupo
  es por clave y un cliente pesado deja sin servicio a los demás.

---

## Instalación para un cliente nuevo (20 minutos)

### 1. Crear el bot
En [@BotFather](https://t.me/BotFather): `/newbot`.
- Nombre: el que quiera el cliente (ej. *Mis Gastos*)
- Usuario: `algo_gastos_bot`
- Después, con `/setuserpic` y `/setdescription` le pones foto y descripción.

Guarda el token.

### 2. Base de datos
En [neon.tech](https://neon.tech): **un proyecto por cliente**. Copia la
connection string.

### 3. Gemini
Que el cliente entre a [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
con **su** cuenta de Google y te comparta la key, o créala tú en una cuenta
dedicada a ese cliente.

### 4. Desplegar
Render → New → Blueprint → el repo. Variables:

```
APP_NAME=<como quiera llamarlo el cliente>
APP_TAGLINE=<opcional>
OWNER_NAME=<nombre de pila del cliente>
TELEGRAM_TOKEN=<paso 1>
GEMINI_API_KEY=<paso 3>
DATABASE_URL=<paso 2>
BASE_URL=https://<servicio>.onrender.com
CURRENCY=USD
CURRENCY_SYMBOL=$
TIMEZONE=America/Guayaquil
BUFFER_NAME=Colchón
```

`TELEGRAM_WEBHOOK_SECRET` y `DASHBOARD_TOKEN` se generan solos.
Pon `BASE_URL` con la URL real y vuelve a desplegar: ahí se registra el webhook.

### 5. Los dos cron jobs
En [cron-job.org](https://cron-job.org):
- cada 10 min → `https://<servicio>.onrender.com/health`
- diario 8:00 → `https://<servicio>.onrender.com/tareas/recordatorios?t=<DASHBOARD_TOKEN>`

### 6. Entregar
Pídele al cliente que le escriba `/start` a su bot: **el primero que escribe
queda registrado como dueño**, nadie más puede usarlo. Luego `/setup` con él al
lado, en 5 pasos:

1. Su nombre
2. Sueldo y día de pago
3. Gastos fijos (arriendo, internet, teléfono, carro, préstamos)
4. Tarjetas: nombre, **día de corte**, **día de pago** y cupo
5. Colchón

Termina mandándole el enlace del panel y `/ayuda`.

> Si prefieres dejarlo blindado desde el principio, pon el ID de Telegram del
> cliente en `ALLOWED_USER_IDS` antes de entregarlo (que te lo pase con `/id` en
> cualquier bot, o desde [@userinfobot](https://t.me/userinfobot)).

---

## Personalizar la marca

Todo lo visible sale de variables de entorno, sin tocar código:

| Variable | Dónde se ve |
|---|---|
| `APP_NAME` | Título del panel, `/start`, pestaña del navegador |
| `APP_TAGLINE` | Subtítulo del panel y de `/start` |
| `OWNER_NAME` | Saludo en el panel y en `/resumen` |
| `BUFFER_NAME` | Cómo se llama el colchón ("Fondo", "Reserva", "Plata de mamá"…) |
| `CURRENCY_SYMBOL`, `LOCALE_DECIMAL_COMMA` | Formato de los montos |
| `TIMEZONE` | Fechas y hora de los recordatorios |

Para otro país: cambia `CURRENCY`, `CURRENCY_SYMBOL`, `TIMEZONE` y, si usan
`1.234,56`, pon `LOCALE_DECIMAL_COMMA=true`. Las pistas de comercios
ecuatorianos viven en `app/services/fallback.py` (`CATEGORY_HINTS`) — agrégale
los locales del país que toque; la IA no las necesita, son solo para el modo
sin IA.

Las categorías por defecto están en `app/services/seed.py`.

---

## Qué cobrar

Referencia, no evangelio:

- **Instalación llave en mano**: cobra una sola vez la puesta a punto (bot,
  base, deploy, configuración acompañada). Es donde está tu trabajo real.
- **Mantenimiento mensual**: si vas a responder dudas, arreglar cosas y
  vigilar que no se caiga, cóbralo aparte. Si no piensas dar soporte, dilo
  claro y no lo cobres.
- **Extras**: categorías a medida, otra moneda, reportes especiales, migrar su
  Excel histórico.

Ponle números tú según tu mercado y cuánto tiempo te toma cada instalación.

---

## Migrar el Excel del cliente

No hay importador automático todavía. Lo práctico:

1. Pídele el Excel del último mes.
2. Carga los **gastos fijos, tarjetas y sueldo** en `/setup` — eso es el 90% del
   valor y no necesita histórico.
3. Si quiere histórico, escribe un script que lea el Excel y cree
   `Transaction`s con `period` correcto (mira `scripts/demo.py`, hace
   exactamente eso).

---

## Lista de verificación antes de entregar

- [ ] `/start` responde y el cliente quedó como dueño
- [ ] `/setup` completado con sus datos reales
- [ ] Una foto de recibo de prueba se lee bien
- [ ] Una nota de voz de prueba se entiende
- [ ] `/tarjetas` muestra los cortes correctos (¡verifica contra su estado de cuenta real!)
- [ ] El panel abre en el celular del cliente y está guardado en favoritos
- [ ] Los dos cron jobs corriendo
- [ ] El cliente sabe que el enlace del panel **no se comparte**
