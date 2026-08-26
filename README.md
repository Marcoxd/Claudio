<h1 align="center">Kuri 💸</h1>
<p align="center"><i>Tus finanzas, en un chat.</i></p>

Bot de Telegram para llevar tus gastos sin abrir Excel nunca más. Le escribes,
le hablas o le mandas la foto del recibo, y él ordena todo: gastos fijos,
tarjetas de crédito con sus cortes y diferidos, ingresos extra, cuentas
divididas con amigos y el "colchón" que usas pero no es tuyo.

Todo corre **gratis**: Render (free) + Neon (Postgres free) + Gemini (Google AI
Studio, tier gratuito).

---

## Qué hace

**Anotar como hablas**

| Mandas | Entiende |
|---|---|
| `almuerzo 12.50 con la visa` | $12.50 · Comida · Visa |
| `tv 899 diferido a 12 meses con diners` | 12 cuotas de $74.92, mes a mes en el corte correcto |
| 🎤 nota de voz | la transcribe y extrae el gasto |
| 📷 foto del recibo | comercio, fecha, total **y cada ítem** |
| 📄 PDF de la factura | igual, con IVA y subtotales |
| `me pagaron 450 de asesoría` | ingreso extra, aparte del sueldo |
| `saqué 100 del colchón` | movimiento del dinero ajeno |

**Tarjetas de crédito de verdad**
- Día de **corte** y día de **pago** por tarjeta: sabe si una compra cae en este
  corte o en el siguiente.
- **Al anotar el gasto te dice a qué mes va**, antes de que confirmes:
  *«Va al corte del 20 sep, lo pagas el 10 oct»*.
- `/corte` responde la pregunta de todos los días: *si compro hoy, ¿en qué mes
  me lo cobran?* — tarjeta por tarjeta, y te avisa si el corte es en 3 días.
- **Diferidos**: reparte las cuotas mes a mes y te dice cuánto tienes
  comprometido en los próximos meses.
- `/tarjetas` te dice cuánto pagar, cuándo vence y cuánto cupo te queda; desde
  ahí abres el **detalle de un corte** (qué compras entraron, con sus fechas) o
  le **cambias las fechas** a una tarjeta.
- `/nuevatarjeta` agrega una sin volver a pasar por `/setup`.
- **`/conciliar`**: le mandas el PDF del estado de cuenta y cruza cada
  movimiento del banco contra lo que registraste. Te dice qué ya tenías, qué
  te faltó anotar, dónde el banco cobró distinto y qué no pertenece a ese
  corte. Con un toque agrega los faltantes, corrige los montos, registra los
  pagos y te fija el día de corte y de pago leídos del propio estado.
  Indispensable si compartes la tarjeta con alguien más.
- `/diferidos` te dice de cada compra a cuotas cuántas llevas, cuánto falta y
  cuánto se te va cada mes solo en cuotas.

**Cuentas compartidas**
- `cena 96 con Ana y Luis` → divide en partes iguales.
- ¿Lo pagaste tú pero el gasto es de ellos? Destilda **Yo** en la lista de
  personas: te deben el total y a ti no te cuenta como gasto.
- Recibo con ítems → **marcas quién consumió qué** y el IVA y la propina se
  prorratean solos según lo que comió cada quien.
- `/deudas` lleva quién te debe; cuando te pagan, saldas con un toque.
- Ojo al detalle: la tarjeta cobra el **total**, pero tu gasto real es **tu parte**.
  El panel muestra las dos cosas.

**Gastos fijos e ingresos**
- Arriendo, internet, teléfono, cuota del carro, préstamo de una persona…
- Cada mes se generan solos como pendientes y los marcas pagados.
- Sueldo recurrente + extras (asesorías, bonos) por separado.

**El colchón**
- Ese dinero que usas pero **no es tuyo**, en su propia cuenta.
- Nunca suma a tu disponible y siempre ves cuánto debes reponer.

**Panel web**
- Cuánto te queda para gastar este mes (lo más importante, arriba y grande).
- Ingresos vs. gastos, en qué se te va la plata, tarjetas, deudas, colchón.
- Por tarjeta: qué rango de compras cubre el corte que estás pagando, la lista
  de movimientos que entraron y a qué corte irá lo que compres hoy.
- Compras a cuotas: cuántas llevas pagadas y cuánto queda de cada una.
- Modo claro y oscuro, funciona en el celular.
- Sin pedir nada a servidores externos: ni fuentes, ni scripts, ni CDNs.

**Extras**
- `/pregunta ¿en qué se me fue la plata?` — responde con tus números reales.
- `/exportar` — CSV para Excel, por si extrañas la hoja de cálculo.
- Recordatorios diarios antes de que venza una tarjeta o un fijo.

---

## Ponlo a andar en 15 minutos (gratis)

### 1. Crea el bot en Telegram
Habla con [@BotFather](https://t.me/BotFather) → `/newbot` → guarda el **token**.

### 2. Consigue la API key de Gemini
Entra a [aistudio.google.com/apikey](https://aistudio.google.com/apikey) con tu
cuenta de Google → **Create API key**. El tier gratuito alcanza de sobra para uso
personal.

### 3. Base de datos gratis (Neon)
1. Crea una cuenta en [neon.tech](https://neon.tech) (no pide tarjeta).
2. Nuevo proyecto → copia la **connection string** (`postgresql://…`).
   El bot la convierte solo al driver async.

> ¿Solo quieres probar en tu compu? Sáltate este paso: por defecto usa un
> archivo SQLite en `./data/gastos.db`.

### 4. Publica en Render
1. Sube este repo a tu GitHub.
2. En [render.com](https://render.com) → **New → Blueprint** → elige el repo
   (lee `render.yaml` solo).
3. Llena las variables que te pide:
   - `TELEGRAM_TOKEN` — el de BotFather
   - `GEMINI_API_KEY` — la de AI Studio
   - `DATABASE_URL` — la de Neon
   - `BASE_URL` — la URL que te da Render, por ejemplo `https://kuri.onrender.com`
     *(ponla después del primer deploy y vuelve a desplegar: con ella se registra
     el webhook automáticamente)*
4. `TELEGRAM_WEBHOOK_SECRET` y `DASHBOARD_TOKEN` se generan solos.

### 5. Que no se duerma
El plan gratuito de Render suspende el servicio tras 15 minutos sin tráfico
(el primer mensaje después tarda ~50 s). Para evitarlo:

1. Entra a [cron-job.org](https://cron-job.org) (gratis, sin tarjeta).
2. Crea un job cada **10 minutos** a `https://TU-APP.onrender.com/health`.
3. Crea otro job **una vez al día a las 8:00** a
   `https://TU-APP.onrender.com/tareas/recordatorios?t=TU_DASHBOARD_TOKEN`
   → ese te manda por Telegram los avisos de tarjetas y fijos por vencer.

### 6. Configúralo
Escríbele `/start` al bot (el primero que escriba queda como dueño) y luego
`/setup`: en 5 pasos quedan cargados sueldo, gastos fijos, tarjetas y colchón.

---

## ¿Ya llevas los gastos en Excel?

`scripts/importar_excel.py` lee un libro con una hoja por mes y carga fijos,
tarjetas, personas, colchón y las compras a cuotas en curso.

```bash
# primero mira qué haría, sin tocar nada
PYTHONPATH=. python scripts/importar_excel.py Gastos.xlsx --anio 2026

# cuando te cuadre
PYTHONPATH=. python scripts/importar_excel.py Gastos.xlsx --anio 2026 \
    --tarjeta "Pacífico" --corte 24 --pago 8 \
    --colchon 989.12 --personas "Ana,Luis" --aplicar
```

`--corte` y `--pago` salen de la primera página de tu estado de cuenta, donde
dice **Fecha de corte** y **Fecha máxima de pago sin recargos**. Son lo único
que el bot no puede adivinar y de lo que depende todo lo demás.

Espera este formato por hoja: **A** descripción, **B** total de la compra,
**C** valor del mes, **D** tarjeta o número de cuota, **E/F** el bloque de
resumen con los fijos y el sueldo. Un diferido se reconoce por su fórmula
(`=B6/3` son tres cuotas), no por la proporción, para no confundir una
coincidencia con cuotas.

De paso te avisa de los números escritos como texto (`17,46` con coma) que
Excel no estaba sumando.

---

## Correrlo en tu máquina

```bash
git clone <tu-repo> && cd kuri
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # llena TELEGRAM_TOKEN y GEMINI_API_KEY
python run_bot.py         # el bot por polling, sin webhook

# en otra terminal, el panel:
uvicorn app.main:app --reload
# ábrelo en http://localhost:8000/?t=TU_DASHBOARD_TOKEN
```

¿Quieres verlo con datos de ejemplo antes de configurar nada?

```bash
PYTHONPATH=. python scripts/demo.py --reset
uvicorn app.main:app --reload
```

Con Docker:

```bash
cp .env.example .env
docker compose up -d
```

---

## Cómo está hecho

```
app/
├── config.py          Variables de entorno (marca, moneda, claves)
├── models.py          15 tablas: cuentas, transacciones, cuotas, splits…
├── money.py           Dinero exacto en centavos + repartos sin perder centavos
├── db.py              Motor async (SQLite o Postgres)
├── services/
│   ├── ai.py          Gemini: texto, audio, imagen y PDF → JSON estructurado
│   ├── fallback.py    Parser por reglas si no hay IA o se acaba la cuota
│   ├── capture.py     De lo que entendió la IA a una transacción guardada
│   ├── cards.py       Cortes, vencimientos y diferidos
│   ├── splits.py      División por partes iguales, por ítems o a medida
│   ├── fixed.py       Gastos fijos e ingresos recurrentes mes a mes
│   ├── buffer.py      El colchón
│   ├── reports.py     Resumen mensual y "cuánto puedo gastar"
│   └── reminders.py   Avisos diarios
├── bot/               aiogram 3: handlers, teclados, middlewares
├── web/               FastAPI + Jinja: panel y API de solo lectura
└── main.py            App web + webhook de Telegram
```

**Decisiones que importan**

- **El dinero se guarda en centavos** (enteros). Nada de floats: los repartos
  cuadran al centavo, siempre.
- **Las cuotas se materializan al comprar.** Cada diferido genera N filas con su
  período de corte, así el "cuánto debo este mes" es una suma, no una simulación.
- **Tu gasto real ≠ lo que cobra la tarjeta.** Si divides una cuenta, la tarjeta
  cobra el total y tu presupuesto solo carga tu parte.
- **El colchón vive aparte.** Nunca entra al disponible ni al patrimonio.
- **Sin IA también funciona.** Si falla Gemini o se acaba la cuota, un parser por
  reglas en español entiende los mensajes de texto.

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Cubren lo que duele si se rompe: aritmética de dinero, ciclos de corte de
tarjetas, diferidos, división de cuentas y el cálculo de disponible.

---

## Privacidad

- Los datos viven en **tu** base de datos; nadie más los ve.
- El panel está detrás de un token; cámbialo si lo compartiste por error.
- A Gemini solo se le manda lo que le pides interpretar (el texto, el audio o la
  imagen del recibo), nunca tu historial.
- El panel no carga nada de terceros, así que abrirlo no le avisa a nadie.
- Google no entrena con los datos de la API de pago; en el **tier gratuito sí
  puede usarlos para mejorar sus modelos**. Si eso te incomoda, activa
  facturación en AI Studio o usa el parser por reglas.

---

## Licencia

Software propietario. Ver [`LICENSE`](LICENSE).
¿Quieres revenderlo o instalarlo para otra persona? Lee
[`docs/VENTA.md`](docs/VENTA.md).
