"""Parser por reglas para cuando Gemini no está disponible (o se acabó la cuota)."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

AMOUNT_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![\w])")
INSTALLMENTS_RE = re.compile(r"(?:diferid\w*\s*(?:a|en)?\s*|a\s+)(\d{1,2})\s*(?:meses|cuotas|pagos)|(\d{1,2})\s*(?:meses|cuotas)")
INCOME_WORDS = {
    "cobre", "cobré", "me pagaron", "sueldo", "salario", "ingreso", "asesoria",
    "asesoría", "asesoramiento", "recibi", "recibí", "deposito", "depósito",
    "honorarios", "factura cobrada", "me depositaron", "bono", "comision", "comisión",
}
BUFFER_USE_WORDS = {"saque del colchon", "use el colchon", "del colchon", "colchon"}
BUFFER_REPAY_WORDS = {"repuse", "devolvi al colchon", "devolví al colchón", "reponer"}

CATEGORY_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("Supermercado", (
        "supermaxi", "megamaxi", "mi comisariato", "comisariato", "aki", "akí",
        "santa maria", "santamaria", "tia", "tía", "hipermarket", "coral hiper",
        "mercado", "vivere", "víveres", "gran aki", "magda", "camari",
    )),
    ("Comida", (
        "almuerzo", "comida", "cena", "desayuno", "restaurante", "cafe", "café",
        "pizza", "hamburguesa", "sushi", "kfc", "juan valdez", "sweet and coffe",
        "sweet & coffee", "mcdonald", "burger", "dominos", "domino's", "american deli",
        "pedidos ya", "pedidosya", "rappi", "rapi", "uber eats", "chifa", "menestra",
        "encebollado", "bolon", "bolón", "hornado", "ceviche", "corn dog", "crepes",
        "alitas", "el español", "los alpes", "pollo", "panaderia", "panadería", "pan",
        "helado", "dulces", "papipollo", "chugchucaras", "fritada", "seco de",
    )),
    ("Combustible", (
        "gasolina", "combustible", "diesel", "primax", "petroecuador", "mobil",
        "terpel", "aditivo", "gasolinera", "p&s", "masgas",
    )),
    ("Transporte", (
        "taxi", "uber", "cabify", "indriver", "didi", "bus", "pasaje", "peaje",
        "parqueadero", "parqueo", "lavada", "mecanico", "mecánico", "llantas",
        "matricula", "matrícula", "revision vehicular", "revisión", "aceite",
        "carro", "moto", "tag", "sri vehicular",
    )),
    ("Vivienda", (
        "arriendo", "alquiler", "renta", "condominio", "alicuota", "alícuota",
        "airbnb", "mudanza", "pintulac", "ferreteria", "ferretería", "kywi", "kiwy",
        "decoracion", "decoración", "pintura",
    )),
    ("Servicios", (
        "luz", "agua", "energia", "energía", "electrica", "eléctrica", "gas",
        "emaap", "eeq", "epmaps", "interagua",
    )),
    ("Internet y teléfono", (
        "internet", "telefono", "teléfono", "claro", "movistar", "cnt", "tuenti",
        "netlife", "plan celular", "plan marco", "plan paty", "recarga", "celular",
        "puntonet", "dominio", "hosting",
    )),
    ("Salud", (
        "farmacia", "medico", "médico", "doctor", "medicina", "clinica", "clínica",
        "hospital", "dentista", "fybeca", "sana sana", "pharmacys", "cruz azul",
        "difare", "solca", "examenes", "exámenes", "laboratorio", "inyeccion",
        "inyección", "pastilla", "vacuna", "optica", "óptica",
    )),
    ("Educación", (
        "curso", "colegiatura", "matricula", "universidad", "libro", "iece",
        "capacitacion", "capacitación", "certificacion", "certificación",
    )),
    ("Entretenimiento", (
        "cine", "multicines", "supercines", "bar", "cerveza", "licor", "trago",
        "fiesta", "concierto", "juego", "salida", "viaje", "hotel", "hostal",
        "playa", "papallacta", "tandapi", "quenko", "sabai", "mistika", "vino",
        "whisky", "discoteca",
    )),
    ("Ropa", (
        "ropa", "zapatos", "camisa", "pantalon", "pantalón", "zara", "h&m", "hym",
        "de prati", "deprati", "etafashion", "eta fashion", "marathon", "skechers",
        "patprimo", "coral ropa", "r y b", "payless", "bata", "perfume", "casco",
    )),
    ("Suscripciones", (
        "netflix", "spotify", "disney", "hbo", "max", "youtube", "suscripcion",
        "suscripción", "icloud", "claude", "chatgpt", "canva", "adobe", "prime",
    )),
    ("Mascotas", ("veterinario", "perro", "gato", "mascota", "balanceado",
                  "mundo mascotas", "pet", "nala")),
    ("Préstamos", ("prestamo", "préstamo", "cuota del prestamo", "deuda",
                   "cuota coop", "cooperativa", "banco", "credito", "crédito")),
    ("Regalos", ("regalo", "cumpleaños", "aniversario", "flores")),
    ("Otros", ("registro civil", "notaria", "notaría", "sri", "tramite", "trámite",
               "papeleta", "multa", "anuncios", "publicidad", "marketing")),
]

ACCOUNT_HINTS = ("visa", "mastercard", "master", "diners", "amex", "american express",
                 "titanium", "platinum", "gold", "black", "efectivo", "cash",
                 "debito", "débito", "tarjeta", "banco", "pichincha", "guayaquil",
                 "produbanco", "pacifico", "pacífico", "internacional", "bolivariano",
                 "austro", "loja", "jep", "deuna", "transferencia", "payphone")

PEOPLE_RE = re.compile(r"\bcon\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s*(?:,|y)\s*[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)*)")


def _strip(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )


def parse_amount(text: str) -> float:
    matches = AMOUNT_RE.findall(text)
    best = 0.0
    for raw in matches:
        value = raw
        if "," in value and "." in value:
            value = value.replace(".", "").replace(",", ".") if value.rfind(",") > value.rfind(".") else value.replace(",", "")
        elif "," in value:
            value = value.replace(",", ".") if len(value.split(",")[-1]) <= 2 else value.replace(",", "")
        try:
            number = float(value)
        except ValueError:
            continue
        best = max(best, number)
    return best


def guess_category(text: str, available: list[str]) -> str:
    flat = _strip(text)
    for name, words in CATEGORY_HINTS:
        if name not in available:
            continue
        if any(_strip(w) in flat for w in words):
            return name
    return "Otros" if "Otros" in available else (available[0] if available else "")


def parse_text_rules(text: str, ctx: dict | None = None):
    """Devuelve un ParsedCapture aproximado sin usar IA."""
    from app.services.ai import ParsedCapture

    ctx = ctx or {}
    text = (text or "").strip()
    if not text:
        return ParsedCapture(kind="unknown", confidence=0.0, notes="Mensaje vacío")

    flat = _strip(text)
    amount = parse_amount(text)
    kind = "income" if any(_strip(w) in flat for w in INCOME_WORDS) else "expense"

    installments = 1
    m = INSTALLMENTS_RE.search(flat)
    if m:
        installments = int(next(g for g in m.groups() if g))

    account = ""
    for hint in ACCOUNT_HINTS:
        if _strip(hint) in flat:
            account = hint
            break

    people: list[str] = []
    pm = PEOPLE_RE.search(text)
    if pm:
        people = [p.strip() for p in re.split(r",|\sy\s", pm.group(1)) if p.strip()]

    buffer_direction = ""
    if any(_strip(w) in flat for w in BUFFER_REPAY_WORDS) and "colchon" in flat:
        buffer_direction = "repay"
    elif "colchon" in flat:
        buffer_direction = "use"

    description = AMOUNT_RE.sub("", text).strip(" .,-")
    description = re.sub(r"\s{2,}", " ", description) or text

    return ParsedCapture(
        kind=kind if amount else "unknown",
        amount=amount,
        date=dt.date.today().isoformat(),
        description=description[:120],
        category=guess_category(text, ctx.get("categories", [])) if kind == "expense" else "",
        account=account,
        installments=installments,
        people=people,
        split_mode="equal" if people else "",
        is_buffer=bool(buffer_direction),
        buffer_direction=buffer_direction,
        notes="Interpretado sin IA (reglas locales)",
        confidence=0.45 if amount else 0.1,
    )
