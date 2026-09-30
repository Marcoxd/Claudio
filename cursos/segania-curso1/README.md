# Curso 1 · Gestión laboral y cumplimiento legal en Ecuador (segania.com)

Generador de las lecciones en video del curso: escenas animadas, narración con voz sintética,
preguntas con cuenta regresiva al final y material descargable.

## Cómo generar una lección

```bash
./preparar.sh                                   # una vez por entorno
python3 build.py lecciones/3.3.json             # voz local (Kokoro, gratuita)
python3 build.py lecciones/3.3.json --voz em_alex
```

Resultado en `salida/<id>/`:

- `leccion-<id>.mp4`: video 1920×1080 con narración
- `leccion-<id>.srt`: subtítulos
- `preguntas-<id>.csv`: preguntas para cargar en la plataforma

`python3 plantilla_decimos.py` crea la plantilla Excel de la lección 3.3.

## Voces

| Motor | Opción `--voz` | Notas |
|---|---|---|
| `kokoro` (por defecto) | `ef_dora`, `em_alex`, `em_santa` | Gratuita y local. Suena artificial. |
| `azure` | `es-MX-DaliaNeural` (a +4 %) | **Voz oficial de Segania.** Lee `AZURE_SPEECH_KEY` y `AZURE_SPEECH_REGION`. Uso comercial permitido. |
| `google` | p. ej. `es-US-Chirp3-HD-Kore` | Alternativa. Lee `GOOGLE_TTS_API_KEY`. |

La narración se guarda en caché (`$TTS_DIR/cache`), así que cambiar solo las imágenes no
vuelve a generar la voz.

## Formato de una lección (`lecciones/<id>.json`)

Cada escena tiene un `tipo`: `apertura`, `capitulo`, `comparar`, `linea`, `dos_listas`, `calculo`,
`cifra`, `puntos`, `resumen`, `pregunta` o `cierre`. Si `voz` es una lista, la escena se revela por partes y cada parte
aparece mientras se narra. En `calculo`, `pasos` indica cuántos elementos se ven en cada parte.
Los números se escriben con palabras en la narración para que la voz los lea bien.

Íconos: [Lucide](https://lucide.dev) (licencia ISC, ver `icons/LICENSE-lucide.txt`).
Tipografías de marca: Archivo, IBM Plex Sans e IBM Plex Mono (Google Fonts, licencia OFL). Logo: `marca/`.

`decir.py` genera la misma voz Dalia con edge-tts (servicio gratuito de Edge, sin licencia comercial clara).

Reglas del guion: tratar de tú, siglas dichas enteras, "segania punto com", comas para las pausas.
