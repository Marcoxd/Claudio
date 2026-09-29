"""Genera el video animado de una lección: escenas animadas + narración + preguntas.

Uso:
  python3 build.py lecciones/3.3.json                 # voz local (Kokoro)
  python3 build.py lecciones/3.3.json --motor google  # Google Cloud TTS (lee GOOGLE_TTS_API_KEY)
  python3 build.py lecciones/3.3.json --solo-muestras # solo algunas imágenes para revisar el diseño

Salida en salida/<id>/: leccion-<id>.mp4, leccion-<id>.srt, preguntas-<id>.csv
"""
import argparse, base64, csv, hashlib, html, io, json, math, os, random, re, shutil, subprocess, urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

BASE = Path(__file__).resolve().parent
ICONS = BASE / "icons"
FONTS_CSS = (BASE / "fonts-local.css").as_uri()
TTS_DIR = Path(os.environ.get("TTS_DIR", "/tmp/claude-0/tts"))
CHROME = os.environ.get("CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
SR = 24000
FPS = 30
PAUSA = 0.45        # silencio después de cada bloque de voz (s)
ENTRADA = 0.35      # silencio antes de la voz al empezar una escena (s)
CUENTA = 5          # segundos de cuenta regresiva
LETRAS = "ABCD"
esc = html.escape


# ---------------------------------------------------------------- íconos
def ic(name, cls="ico"):
    svg = (ICONS / f"{name}.svg").read_text()
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S).strip()
    return svg.replace('class="lucide', f'class="{cls} lucide', 1)


# ---------------------------------------------------------------- estilos
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--ink:#13212f;--muted:#5a6a7b;--line:#e1e7ef;--soft:#f4f7fb;--navy:#0d2640;
--c1:#1d4f8c;--c1s:#e9f0f9;--gold:#f2b441;--golds:#fdf3dc;--ok:#138a52;--oks:#e4f5ec}
@property --n{syntax:'<integer>';inherits:false;initial-value:0}
html,body{width:1920px;height:1080px;overflow:hidden;background:#fff}
body{font-family:'Inter',sans-serif;color:var(--ink);position:relative}
h1,h2,h3,.m{font-family:'Montserrat',sans-serif}
svg.lucide{width:1em;height:1em;stroke-width:2}
.top{position:absolute;left:110px;right:110px;top:56px;display:flex;justify-content:space-between;align-items:center;font-size:24px;color:var(--muted);z-index:2}
.top .chip{background:var(--c1s);color:var(--c1);font-weight:600;padding:8px 20px;border-radius:40px}
.bottom{position:absolute;left:110px;right:110px;bottom:48px;display:flex;justify-content:space-between;align-items:center;font-size:22px;color:var(--muted);z-index:2}
.bar{flex:1;height:6px;background:var(--line);border-radius:6px;margin-right:40px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--c1);transform-origin:left}
.brand{font-family:'Montserrat';font-weight:700;letter-spacing:.06em;color:var(--c1)}
.stage{position:absolute;left:110px;right:110px;top:150px;bottom:120px;display:flex;flex-direction:column;justify-content:center;z-index:1}
.th{display:flex;align-items:center;gap:28px}
.th .bdg{flex:none;width:92px;height:92px;border-radius:26px;background:var(--c1);color:#fff;display:flex;align-items:center;justify-content:center;font-size:50px}
h2.t{font-size:64px;font-weight:800;line-height:1.12;letter-spacing:-.01em}
.sub{font-size:30px;color:var(--muted);margin-top:18px}

/* ---- animaciones ---- */
.a{animation:up .75s cubic-bezier(.2,.8,.2,1) both;animation-delay:var(--d,0s)}
.al{animation:left .75s cubic-bezier(.2,.8,.2,1) both;animation-delay:var(--d,0s)}
.ap{animation:pop .7s cubic-bezier(.3,1.5,.5,1) both;animation-delay:var(--d,0s)}
.af{animation:fade .8s ease both;animation-delay:var(--d,0s)}
.az{animation:zoom 1.4s cubic-bezier(.2,.8,.2,1) both;animation-delay:var(--d,0s)}
@keyframes up{from{opacity:0;transform:translateY(46px)}to{opacity:1;transform:none}}
@keyframes left{from{opacity:0;transform:translateX(-70px)}to{opacity:1;transform:none}}
@keyframes pop{from{opacity:0;transform:scale(.5)}to{opacity:1;transform:none}}
@keyframes fade{from{opacity:0}to{opacity:1}}
@keyframes zoom{from{opacity:0;transform:scale(.7)}to{opacity:1;transform:none}}
.bar i.grow{animation:grow .9s ease both}
@keyframes grow{from{transform:scaleX(var(--from,0))}to{transform:scaleX(1)}}
/* transición entre escenas: una cortina cruza la pantalla */
.prev{position:absolute;inset:0;z-index:50;animation:hideprev .4s steps(1,end) both}
@keyframes hideprev{0%{opacity:1}100%{opacity:0}}
.wipe{position:absolute;top:0;bottom:0;left:0;width:100%;z-index:60;background:var(--c1);border-left:26px solid var(--gold);animation:wipe .8s cubic-bezier(.7,0,.3,1) both}
@keyframes wipe{0%{transform:translateX(-110%)}45%,55%{transform:translateX(-26px)}100%{transform:translateX(110%)}}

/* ---- lista ---- */
.items{margin-top:48px;display:flex;flex-direction:column;gap:22px}
.it{display:flex;align-items:center;gap:30px;background:var(--soft);border-radius:22px;padding:24px 34px;font-size:36px;line-height:1.3}
.it .n{flex:none;width:66px;height:66px;border-radius:50%;background:#fff;color:var(--c1);display:flex;align-items:center;justify-content:center;font-size:34px;box-shadow:0 0 0 3px var(--c1s)}
.it.hide{visibility:hidden}
.it.now{background:var(--c1s);box-shadow:inset 8px 0 0 var(--c1)}
.it.now .n{background:var(--c1);color:#fff;box-shadow:none}
.it.was{animation:unhl .6s ease both}
@keyframes unhl{from{background:var(--c1s);box-shadow:inset 8px 0 0 var(--c1)}to{background:var(--soft);box-shadow:inset 0 0 0 var(--c1)}}

/* ---- comparar ---- */
.cols{display:grid;grid-template-columns:1fr 1fr;gap:44px;margin-top:50px}
.col{border:2px solid var(--line);border-radius:28px;padding:40px 46px;position:relative;background:#fff}
.col.hide{visibility:hidden}
.col .icb{position:absolute;right:40px;top:36px;width:104px;height:104px;border-radius:50%;background:var(--golds);color:#b57a09;display:flex;align-items:center;justify-content:center;font-size:54px}
.col .lab{display:inline-block;background:var(--c1);color:#fff;font-weight:700;font-size:24px;padding:8px 20px;border-radius:40px;letter-spacing:.03em}
.col h3{font-size:50px;font-weight:800;margin-top:24px;color:var(--c1);padding-right:120px}
.col p{font-size:33px;line-height:1.4;margin-top:18px;color:#2c3e50}
.nota{margin-top:40px;font-size:31px;background:var(--golds);border-left:8px solid var(--gold);padding:22px 30px;border-radius:0 18px 18px 0;color:#4a3b17;display:flex;gap:18px;align-items:center}
.nota svg{flex:none;font-size:38px;color:#b57a09}
.nota.hide{visibility:hidden}

/* ---- cálculo ---- */
.calc{display:grid;grid-template-columns:.85fr 1.15fr;gap:50px;margin-top:46px;align-items:stretch}
.case{background:var(--navy);color:#fff;border-radius:28px;padding:46px 48px;font-size:36px;line-height:1.45;position:relative;overflow:hidden}
.case .lab{font-size:24px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--gold);margin-bottom:20px;display:flex;gap:12px;align-items:center}
.case .deco{position:absolute;right:-40px;bottom:-50px;font-size:260px;color:rgba(255,255,255,.06)}
.rows{border:2px solid var(--line);border-radius:28px;padding:18px 44px;display:flex;flex-direction:column}
.row{display:flex;justify-content:space-between;gap:30px;font-size:34px;padding:20px 0;border-bottom:2px solid var(--line)}
.row b{font-weight:700;white-space:nowrap}
.hide{visibility:hidden}
.res{margin-top:auto;display:flex;justify-content:space-between;align-items:center;background:var(--c1);color:#fff;border-radius:20px;padding:24px 32px;margin:22px -24px 8px}
.res span{font-size:30px;font-weight:600}
.res b{font-family:'Montserrat';font-size:54px;font-weight:800}

/* ---- cifra ---- */
.big{text-align:center;align-items:center}
.big .lab{font-size:34px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--c1)}
.big .num{font-family:'Montserrat';font-size:240px;font-weight:800;line-height:1.05;margin-top:10px;color:var(--navy);display:flex;gap:40px;justify-content:center}
.big .num .pre{color:var(--gold)}
.count{counter-reset:n var(--n);animation:cnt 1.8s cubic-bezier(.15,.8,.25,1) both;animation-delay:var(--d,0s)}
.count::after{content:counter(n)}
@keyframes cnt{from{--n:0}to{--n:var(--to)}}
.big .line{width:520px;height:12px;border-radius:12px;background:var(--gold);margin:18px auto 0;transform-origin:center}
.big .line.g{animation:grow 1.2s cubic-bezier(.2,.8,.2,1) both;animation-delay:var(--d,0s)}
.big p{font-size:36px;color:var(--muted);margin-top:34px}

/* ---- resumen ---- */
.grid{display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:46px}
.card{background:var(--soft);border-radius:24px;padding:32px 40px;border-top:8px solid var(--c1);display:flex;gap:28px}
.card .ci{flex:none;width:76px;height:76px;border-radius:20px;background:var(--c1s);color:var(--c1);display:flex;align-items:center;justify-content:center;font-size:40px}
.card h3{font-size:36px;font-weight:800;color:var(--c1)}
.card p{font-size:30px;line-height:1.4;margin-top:10px}
.card.hide{visibility:hidden}

/* ---- pregunta ---- */
.stage.qa{justify-content:flex-start;padding-top:40px}
.qhead{display:flex;justify-content:space-between;align-items:center;height:140px}
.qchip{background:var(--gold);color:var(--navy);font-weight:800;font-family:'Montserrat';font-size:28px;padding:10px 26px;border-radius:40px;display:inline-flex;gap:12px;align-items:center}
.q{font-size:52px;font-weight:700;line-height:1.25;margin-top:20px;font-family:'Montserrat'}
.ops{display:grid;grid-template-columns:1fr 1fr;gap:26px;margin-top:50px}
.op{display:flex;align-items:center;gap:26px;border:3px solid var(--line);border-radius:22px;padding:26px 30px;font-size:36px;background:#fff}
.op .l{flex:none;width:64px;height:64px;border-radius:50%;background:var(--soft);display:flex;align-items:center;justify-content:center;font-family:'Montserrat';font-weight:800;font-size:30px;color:var(--c1)}
.op.ok{border-color:var(--ok);background:var(--oks)}
.op.ok .l{background:var(--ok);color:#fff}
.op.ok.an{animation:okpulse .9s cubic-bezier(.3,1.4,.5,1) both;animation-delay:var(--d,0s)}
@keyframes okpulse{0%{transform:scale(1);background:#fff;border-color:var(--line)}40%{transform:scale(1.06)}100%{transform:scale(1);background:var(--oks);border-color:var(--ok)}}
.op.off{opacity:.35}
.op.off.an{animation:dim .6s ease both}
@keyframes dim{from{opacity:1}to{opacity:.35}}
.timer{position:relative;width:132px;height:132px;display:flex;align-items:center;justify-content:center}
.timer svg{position:absolute;inset:0;transform:rotate(-90deg)}
.timer circle{fill:none;stroke-width:10}
.timer .bg{stroke:var(--line)}
.timer .fg{stroke:var(--gold);stroke-dasharray:377;stroke-linecap:round;animation:ring 5s linear both}
@keyframes ring{from{stroke-dashoffset:0}to{stroke-dashoffset:377}}
.timer .num{font-family:'Montserrat';font-weight:800;font-size:58px;color:var(--navy);counter-reset:n var(--n);animation:cd 5s steps(5,end) both}
.timer .num::after{content:counter(n)}
@keyframes cd{from{--n:5}to{--n:0}}
.pausa{font-size:28px;color:var(--muted);margin-right:26px}
.exp{margin-top:34px;font-size:32px;line-height:1.4;background:var(--oks);border-left:8px solid var(--ok);padding:22px 30px;border-radius:0 18px 18px 0;display:flex;gap:18px;align-items:flex-start}
.exp svg{flex:none;font-size:40px;color:var(--ok);margin-top:2px}

/* ---- portada y cierre ---- */
body.dark{background:var(--navy);color:#fff}
body.dark .top{color:#9fb3c8}
body.dark .top .chip{background:rgba(255,255,255,.1);color:#fff}
body.dark .bottom{color:#9fb3c8}
body.dark .bar{background:rgba(255,255,255,.15)}
body.dark .bar i{background:var(--gold)}
body.dark .brand{color:var(--gold)}
.glow{position:absolute;right:-260px;top:-260px;width:900px;height:900px;border-radius:50%;background:radial-gradient(circle at 35% 35%,rgba(242,180,65,.18),rgba(242,180,65,0) 62%)}
.glow2{position:absolute;left:-300px;bottom:-420px;width:1000px;height:1000px;border-radius:50%;background:radial-gradient(circle,rgba(29,79,140,.55),rgba(29,79,140,0) 62%)}
.hero-wrap{display:flex;align-items:center;justify-content:space-between;gap:60px}
.kick{font-size:30px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--gold)}
.hero{font-size:96px;font-weight:800;line-height:1.06;margin-top:26px;max-width:1150px}
.lead{font-size:40px;color:#c9d6e5;margin-top:34px;max-width:1100px;line-height:1.4}
.orb{flex:none;width:420px;height:420px;border-radius:50%;background:rgba(242,180,65,.12);border:3px solid rgba(242,180,65,.45);display:flex;align-items:center;justify-content:center;color:var(--gold);font-size:210px;position:relative}
.orb::before{content:"";position:absolute;inset:-40px;border-radius:50%;border:2px dashed rgba(255,255,255,.18)}
.check{width:150px;height:150px;border-radius:50%;background:var(--gold);color:var(--navy);display:flex;align-items:center;justify-content:center;font-size:90px}
.check svg{stroke-width:3}
.next{margin-top:56px;display:inline-flex;gap:18px;align-items:center;font-size:32px;background:rgba(255,255,255,.08);border:2px solid rgba(255,255,255,.18);border-radius:20px;padding:22px 32px}
.next b{color:var(--gold)}
.conf{position:absolute;left:185px;top:360px;width:18px;height:28px;border-radius:4px;background:var(--c);animation:conf 1.9s cubic-bezier(.1,.7,.3,1) both;animation-delay:var(--d,0s);z-index:3}
@keyframes conf{0%{opacity:0;transform:translate(0,0) rotate(0)}8%{opacity:1}80%{opacity:1}100%{opacity:0;transform:translate(var(--x),var(--y)) rotate(var(--r))}}
"""


def page(body, cls, les, idx, total, prev_img=None, bar_from=None):
    pct = (idx + 1) / total
    grow = f' class="grow" style="width:{pct*100:.2f}%;--from:{bar_from/pct if bar_from else 0:.4f}"' if bar_from is not None else f' style="width:{pct*100:.2f}%"'
    trans = ""
    if prev_img:
        trans = f'<img class="prev" src="{prev_img}"><div class="wipe"></div>'
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<link rel="stylesheet" href="{FONTS_CSS}"><style>{CSS}</style></head>
<body class="{cls}">{trans}
<div class="top"><span>Curso 1 · {esc(les['curso'])}</span><span class="chip">Lección {esc(les['id'])}</span></div>
{body}
<div class="bottom"><div class="bar"><i{grow}></i></div><span class="brand">SEGANIA.COM</span></div>
</body></html>"""


def A(cls, new, d):
    """Clase de animación si el elemento es nuevo en este paso."""
    return f' {cls}" style="--d:{d:.2f}s' if new else ""


# ---------------------------------------------------------------- escenas -> pasos
def pasos_de(les):
    """Lista de pasos. Cada paso: dict(body, cls, voz, inicio_escena, fijo)."""
    out = []
    for e in les["escenas"]:
        t = e["tipo"]
        D0 = 0.55  # retraso inicial cuando hay cortina
        if t == "portada":
            body = f"""<div class="glow af"></div><div class="glow2 af"></div><div class="stage"><div class="hero-wrap"><div>
<div class="kick a" style="--d:.2s">{esc(les['modulo'])}</div><h1 class="hero a" style="--d:.4s">{esc(e['titulo'])}</h1>
<p class="lead a" style="--d:.7s">{esc(e['subtitulo'])}</p></div>
<div class="orb az" style="--d:.5s">{ic(e.get('icono','book-open'))}</div></div></div>"""
            out.append(dict(body=body, cls="dark", voz=e["voz"], inicio=True))

        elif t == "lista":
            voces = e["voz"] if isinstance(e["voz"], list) else [e["voz"]]
            items = [x if isinstance(x, dict) else {"texto": x, "icono": None} for x in e["items"]]
            progresivo = len(voces) == len(items) + 1
            pasos = list(range(len(voces))) if progresivo else [len(items)]
            for k, paso in enumerate(pasos):
                first = k == 0
                d = D0 if first else 0
                its = []
                for i, it in enumerate(items):
                    new = (progresivo and i == paso - 1) or (not progresivo and first)
                    c = "it"
                    if progresivo and i >= paso:
                        c += " hide"
                    elif progresivo and i == paso - 1:
                        c += " now"
                    elif progresivo and i == paso - 2:
                        c += " was"
                    dd = d + (0.15 * i if not progresivo else 0.05)
                    n = ic(it["icono"]) if it.get("icono") else str(i + 1)
                    its.append(f'<div class="{c}{A("al", new, dd)}"><span class="n">{n}</span><span>{esc(it["texto"])}</span></div>')
                sub = f'<p class="sub{A("a", first, d+.15)}">{esc(e["subtitulo"])}</p>' if e.get("subtitulo") else ""
                bdg = f'<span class="bdg{A("ap", first, d)}">{ic(e["icono"])}</span>' if e.get("icono") else ""
                body = f'<div class="stage"><div class="th">{bdg}<h2 class="t{A("a", first, d)}">{esc(e["titulo"])}</h2></div>{sub}<div class="items">{"".join(its)}</div></div>'
                out.append(dict(body=body, cls="", voz=voces[k] if progresivo else " ".join(voces), inicio=first))

        elif t == "comparar":
            voces = e["voz"] if isinstance(e["voz"], list) else [e["voz"]]
            n_el = len(e["cols"]) + (1 if e.get("nota") else 0)
            vis_por_paso = list(range(1, len(voces) + 1)) if len(voces) > 1 else [n_el]
            prev_vis = 0
            for k, vis in enumerate(vis_por_paso):
                first = k == 0
                d = D0 if first else 0
                cols = []
                for i, c in enumerate(e["cols"]):
                    new = prev_vis <= i < vis
                    hid = " hide" if i >= vis else ""
                    icb = f'<span class="icb">{ic(c["icono"])}</span>' if c.get("icono") else ""
                    cols.append(f'<div class="col{hid}{A("a", new, d + .2 + .2*(i-prev_vis))}">{icb}<span class="lab">{esc(c["etiqueta"])}</span><h3>{esc(c["titulo"])}</h3><p>{esc(c["texto"])}</p></div>')
                nota = ""
                if e.get("nota"):
                    i = len(e["cols"])
                    new = prev_vis <= i < vis
                    hid = " hide" if i >= vis else ""
                    nota = f'<div class="nota{hid}{A("a", new, d + .2)}">{ic("info")}<span>{esc(e["nota"])}</span></div>'
                body = f'<div class="stage"><h2 class="t{A("a", first, d)}">{esc(e["titulo"])}</h2><div class="cols">{"".join(cols)}</div>{nota}</div>'
                out.append(dict(body=body, cls="", voz=voces[k] if len(voces) > 1 else voces[0], inicio=first))
                prev_vis = vis

        elif t == "calculo":
            voces = e["voz"] if isinstance(e["voz"], list) else [e["voz"]]
            n_el = 1 + len(e["filas"]) + 1
            vis_por_paso = e.get("pasos") or ([n_el] if len(voces) == 1 else list(range(1, len(voces) + 1)))
            prev_vis = 0
            for k, vis in enumerate(vis_por_paso):
                first = k == 0
                d = D0 if first else 0

                def cl(i, base, anim="a", extra=0.0):
                    new = prev_vis <= i < vis
                    hid = " hide" if i >= vis else ""
                    return f'{base}{hid}{A(anim, new, d + .15 + .25*(i-prev_vis) + extra)}'
                rows = "".join(f'<div class="{cl(1+j, "row")}"><span>{esc(a)}</span><b>{esc(b)}</b></div>' for j, (a, b) in enumerate(e["filas"]))
                ir = 1 + len(e["filas"])
                res = f'<div class="{cl(ir, "res", "ap", .2)}"><span>{esc(e["resultado"][0])}</span><b>{esc(e["resultado"][1])}</b></div>'
                case = f'<div class="{cl(0, "case", "al")}"><span class="deco">{ic("calculator")}</span><div class="lab">{ic("user-check")} Caso</div>{esc(e["caso"])}</div>'
                body = f'<div class="stage"><h2 class="t{A("a", first, d)}">{esc(e["titulo"])}</h2><div class="calc">{case}<div class="rows">{rows}{res}</div></div></div>'
                out.append(dict(body=body, cls="", voz=voces[k], inicio=first))
                prev_vis = vis

        elif t == "cifra":
            d = D0
            body = f'''<div class="stage big"><div class="lab a" style="--d:{d:.2f}s">{esc(e["etiqueta"])}</div>
<div class="num a" style="--d:{d+.15:.2f}s"><span class="pre">{esc(e.get("prefijo",""))}</span><span class="count" style="--to:{int(e["valor"])};--d:{d+.25:.2f}s"></span></div>
<div class="line g" style="--d:{d+.5:.2f}s"></div><p class="a" style="--d:{d+1.2:.2f}s">{esc(e["nota"])}</p></div>'''
            out.append(dict(body=body, cls="", voz=e["voz"], inicio=True))

        elif t == "resumen":
            voces = e["voz"] if isinstance(e["voz"], list) else [e["voz"]]
            prog = len(voces) == len(e["items"])
            for k in range(len(voces)):
                first = k == 0
                d = D0 if first else 0
                cards = []
                for i, it in enumerate(e["items"]):
                    a, b = it[0], it[1]
                    icono = it[2] if len(it) > 2 else "check-circle"
                    new = (i == k) if prog else first
                    hid = " hide" if prog and i > k else ""
                    cards.append(f'<div class="card{hid}{A("a", new, d + (.15 if prog else .15 + .15*i))}"><span class="ci">{ic(icono)}</span><div><h3>{esc(a)}</h3><p>{esc(b)}</p></div></div>')
                body = f'<div class="stage"><h2 class="t{A("a", first, d)}">{esc(e["titulo"])}</h2><div class="grid">{"".join(cards)}</div></div>'
                out.append(dict(body=body, cls="", voz=voces[k], inicio=first))

        elif t == "pregunta":
            n = sum(1 for x in les["escenas"][: les["escenas"].index(e) + 1] if x["tipo"] == "pregunta")
            tot = sum(1 for x in les["escenas"] if x["tipo"] == "pregunta")

            def q(estado, extra="", anim=False):
                d = D0 if anim else 0
                ops = []
                for i, o in enumerate(e["opciones"]):
                    c = "op"
                    st = ""
                    if estado == "respuesta":
                        c += (" ok an" if i == e["correcta"] else " off an")
                        st = f'" style="--d:.1s'
                    elif anim:
                        c += " a"; st = f'" style="--d:{d + .5 + .12*i:.2f}s'
                    ops.append(f'<div class="{c}{st}"><span class="l">{LETRAS[i]}</span><span>{esc(o)}</span></div>')
                exp = f'<div class="exp a" style="--d:.5s">{ic("lightbulb")}<span>{esc(e["explicacion"])}</span></div>' if estado == "respuesta" else ""
                chip = f'<span class="qchip{A("ap", anim, d)}">{ic("circle-help")} Pregunta {n} de {tot}</span>'
                qq = f'<div class="q{A("a", anim, d + .2)}">{esc(e["pregunta"])}</div>'
                return f'<div class="stage qa"><div class="qhead">{chip}{extra}</div>{qq}<div class="ops">{"".join(ops)}</div>{exp}</div>'

            out.append(dict(body=q("pregunta", anim=True), cls="", voz=e["voz_pregunta"], inicio=True))
            timer = ('<div style="display:flex;align-items:center" class="af"><span class="pausa">Pausa el video si necesitas más tiempo</span>'
                     '<div class="timer"><svg viewBox="0 0 132 132"><circle class="bg" cx="66" cy="66" r="60"/><circle class="fg" cx="66" cy="66" r="60"/></svg><span class="num"></span></div></div>')
            out.append(dict(body=q("pregunta", timer), cls="", voz=None, fijo=float(CUENTA), inicio=False))
            out.append(dict(body=q("respuesta"), cls="", voz=e["voz_respuesta"], inicio=False))

        elif t == "cierre":
            rnd = random.Random(7)
            colors = ["#f2b441", "#ffffff", "#6fa8e8", "#138a52", "#f58b6c"]
            conf = "".join(
                f'<i class="conf" style="--x:{rnd.uniform(-150, 1500):.0f}px;--y:{rnd.uniform(-520, 380):.0f}px;--r:{rnd.uniform(-720, 720):.0f}deg;--c:{rnd.choice(colors)};--d:{.35 + rnd.uniform(0, .25):.2f}s"></i>'
                for _ in range(46))
            body = f"""<div class="glow af"></div><div class="glow2 af"></div>{conf}<div class="stage">
<div class="check ap" style="--d:.25s">{ic('check')}</div><h1 class="hero a" style="font-size:84px;--d:.45s">{esc(e['titulo'])}</h1>
<p class="lead a" style="--d:.65s">{esc(e['texto'])}</p>
<div class="a" style="--d:.85s"><div class="next">{ic('book-open')} Próxima lección: <b>{esc(les['siguiente'])}</b></div></div></div>"""
            out.append(dict(body=body, cls="dark", voz=e["voz"], inicio=True))
        else:
            raise ValueError(t)
    return out


# ---------------------------------------------------------------- voz
def tts_kokoro(texto, voz, vel):
    global _K
    if "_K" not in globals():
        from kokoro_onnx import Kokoro
        _K = Kokoro(str(TTS_DIR / "kokoro-v1.0.int8.onnx"), str(TTS_DIR / "voices-v1.0.bin"))
    wav, sr = _K.create(texto, voice=voz, speed=vel, lang="es-419")
    assert sr == SR
    return wav.astype(np.float32)


def tts_google(texto, voz, vel):
    key = os.environ["GOOGLE_TTS_API_KEY"]
    body = {"input": {"text": texto},
            "voice": {"languageCode": voz.split("-")[0] + "-" + voz.split("-")[1], "name": voz},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": SR, "speakingRate": vel}}
    req = urllib.request.Request(f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    data = json.load(urllib.request.urlopen(req, timeout=120))
    wav, sr = sf.read(io.BytesIO(base64.b64decode(data["audioContent"])), dtype="float32")
    assert sr == SR
    return wav


def voz_de(texto, motor, voz, vel):
    cache = TTS_DIR / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(f"{motor}|{voz}|{vel}|{texto}".encode()).hexdigest()[:20]
    f = cache / f"{h}.wav"
    if f.exists():
        return sf.read(f, dtype="float32")[0]
    wav = (tts_google if motor == "google" else tts_kokoro)(texto, voz, vel)
    sf.write(f, wav, SR)
    return wav


def srt_time(s):
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); sec, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"


# ---------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("leccion")
    ap.add_argument("--motor", choices=["kokoro", "google"], default="kokoro")
    ap.add_argument("--voz", default=None, help="kokoro: ef_dora/em_alex/em_santa · google: p. ej. es-US-Chirp3-HD-Kore")
    ap.add_argument("--velocidad", type=float, default=1.0)
    ap.add_argument("--solo-muestras", action="store_true")
    a = ap.parse_args()
    voz = a.voz or ("ef_dora" if a.motor == "kokoro" else "es-US-Chirp3-HD-Kore")

    les = json.loads(Path(a.leccion).read_text())
    lid = les["id"]
    work = BASE / "build" / lid
    outd = BASE / "salida" / lid
    if work.exists():
        shutil.rmtree(work)
    (work / "fr").mkdir(parents=True); outd.mkdir(parents=True, exist_ok=True)
    pasos = pasos_de(les)
    N = len(pasos)

    # 1) Voz (antes que las imágenes, para conocer la duración de cada paso)
    audios = []
    if not a.solo_muestras:
        for i, p in enumerate(pasos):
            audios.append(voz_de(p["voz"], a.motor, voz, a.velocidad) if p["voz"] else None)
            print(f"  voz {i+1}/{N}", flush=True)

    # 2) Animación cuadro por cuadro
    from playwright.sync_api import sync_playwright
    frames, dur_pasos = [], []
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME)
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        prev_last = None
        for i, p in enumerate(pasos):
            if a.solo_muestras and i not in (0, 1, 2, 5, 8, 12, 16, 20, 30, 34, 36, N - 1):
                continue
            prev = prev_last.as_uri() if (p["inicio"] and prev_last and i > 0) else None
            f = work / f"p{i:03}.html"
            f.write_text(page(p["body"], p["cls"], les, i, N, prev_img=prev, bar_from=i / N))
            pg.goto(f.as_uri())
            pg.evaluate("document.fonts.ready.then(() => true)")
            fin = pg.evaluate("() => { const an = document.getAnimations(); an.forEach(x => x.pause());"
                              " return Math.max(0, ...an.map(x => x.effect.getComputedTiming().endTime)); }") / 1000.0
            n_anim = max(1, math.ceil(fin * FPS) + 1)
            mis = []
            for k in range(n_anim):
                pg.evaluate("t => document.getAnimations().forEach(x => { x.pause(); x.currentTime = t; })", k * 1000.0 / FPS)
                out = work / "fr" / f"p{i:03}_{k:04}.jpg"
                pg.screenshot(path=str(out), type="jpeg", quality=90)
                mis.append(out)
                if a.solo_muestras:
                    break
            if a.solo_muestras:
                pg.evaluate("t => document.getAnimations().forEach(x => { x.pause(); x.currentTime = t; })", fin * 1000.0)
                pg.screenshot(path=str(work / f"muestra_{i:03}.jpg"), type="jpeg", quality=90)
                continue
            prev_last = mis[-1]
            lead = ENTRADA if p["inicio"] and p["voz"] else 0.0
            habla = (len(audios[i]) / SR + PAUSA + lead) if audios[i] is not None else p.get("fijo", 0.0)
            total = max(habla, n_anim / FPS + 0.2)
            n_tot = math.ceil(total * FPS)
            frames += mis + [mis[-1]] * (n_tot - len(mis))
            dur_pasos.append((n_tot / FPS, lead))
            print(f"  paso {i+1}/{N}: {len(mis)} cuadros animados, {n_tot/FPS:.1f}s", flush=True)
        b.close()
    if a.solo_muestras:
        print("muestras listas"); return

    # 3) Audio sincronizado + subtítulos
    pistas, subs, t0 = [], [], 0.0
    for i, (dur, lead) in enumerate(dur_pasos):
        seg = np.zeros(int(round(dur * SR)), dtype=np.float32)
        if audios[i] is not None:
            s = int(lead * SR); w = audios[i][: len(seg) - s]
            seg[s:s + len(w)] = w
            frases = [x.strip() for x in re.split(r"(?<=[.?!:])\s+", pasos[i]["voz"]) if x.strip()]
            habla = len(audios[i]) / SR; tot = sum(len(x) for x in frases); c = t0 + lead
            for x in frases:
                d = habla * len(x) / tot; subs.append((c, c + d, x)); c += d
        pistas.append(seg); t0 += dur
    sf.write(work / "audio.wav", np.concatenate(pistas), SR)

    # 4) Video: secuencia de cuadros (enlaces) + audio
    seq = work / "seq"; seq.mkdir()
    for k, fr in enumerate(frames):
        os.link(fr, seq / f"{k:06}.jpg")
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    mp4 = outd / f"leccion-{lid}.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(seq / "%06d.jpg"), "-i", str(work / "audio.wav"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium", "-tune", "animation",
                    "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(mp4)], check=True)
    shutil.rmtree(seq); shutil.rmtree(work / "fr")

    with open(outd / f"leccion-{lid}.srt", "w") as fh:
        for n, (s, e, txt) in enumerate(subs, 1):
            fh.write(f"{n}\n{srt_time(s)} --> {srt_time(e)}\n{txt}\n\n")
    with open(outd / f"preguntas-{lid}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["leccion", "pregunta", "opcion_a", "opcion_b", "opcion_c", "opcion_d", "correcta", "explicacion"])
        for e in les["escenas"]:
            if e["tipo"] == "pregunta":
                w.writerow([lid, e["pregunta"], *e["opciones"], LETRAS[e["correcta"]], e["explicacion"]])
    print(f"listo: {mp4} ({t0/60:.1f} min, {len(frames)} cuadros)")


if __name__ == "__main__":
    main()
