"""Voz oficial de Segania (es-MX-DaliaNeural, +4%) con edge-tts.

Uso: python decir.py "Texto a decir" salida.mp3  -> salida.mp3 y salida.json (tiempo de cada palabra).
Reglas del texto: tratar de tú, siglas dichas enteras, "segania punto com", comas donde se quiera pausa.
Ojo: edge-tts usa el servicio gratuito de lectura de Microsoft Edge; para uso comercial, generar la misma
voz con Azure Speech (build.py --motor azure).
"""
import asyncio, json, sys
from pathlib import Path
import edge_tts

VOZ = "es-MX-DaliaNeural"
VELOCIDAD = "+4%"


async def decir(texto, destino):
    # boundary="WordBoundary" es obligatorio: en edge-tts 7 el valor por defecto es por frase y no da palabras.
    com = edge_tts.Communicate(texto, VOZ, rate=VELOCIDAD, boundary="WordBoundary")
    palabras = []
    with open(destino, "wb") as f:
        async for t in com.stream():
            if t["type"] == "audio":
                f.write(t["data"])
            elif t["type"] == "WordBoundary":
                ini = t["offset"] / 1e7
                palabras.append({"t": t["text"], "inicio": round(ini, 3), "fin": round(ini + t["duration"] / 1e7, 3)})
    Path(destino).with_suffix(".json").write_text(json.dumps({"voz": VOZ, "velocidad": VELOCIDAD, "texto": texto, "palabras": palabras}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(decir(sys.argv[1], sys.argv[2]))
