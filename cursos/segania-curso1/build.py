"""Genera el video de una lección con acabado profesional.

Uso:
  python3 build.py lecciones/3.3.json                 # voz local (Kokoro)
  python3 build.py lecciones/3.3.json --motor google  # Google Cloud TTS (lee GOOGLE_TTS_API_KEY)
  python3 build.py lecciones/3.3.json --muestras      # solo imágenes de control del diseño

Salida en salida/<id>/: leccion-<id>.mp4, leccion-<id>.srt, preguntas-<id>.csv
"""
import argparse, base64, csv, hashlib, html, io, json, math, os, re, shutil, subprocess, urllib.request
from multiprocessing import Process
from pathlib import Path

import numpy as np
import soundfile as sf

BASE = Path(__file__).resolve().parent
ICONS = BASE / "icons"
FONTS_CSS = (BASE / "fonts-local.css").as_uri()
TTS_DIR = Path(os.environ.get("TTS_DIR", "/tmp/claude-0/tts"))
CHROME = os.environ.get("CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
SR = 24000          # frecuencia de la voz
SRM = 48000         # frecuencia final
FPS = 30
CUENTA = 5          # segundos para responder
FUNDIDO = 0.5       # fundido entre escenas (s)
WORKERS = max(1, min(4, (os.cpu_count() or 2) - 1))
LETRAS = "ABCD"
esc = html.escape


def ic(name, cls="ico"):
    svg = (ICONS / f"{name}.svg").read_text()
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S).strip()
    return svg.replace('class="lucide', f'class="{cls} lucide', 1)


# ======================================================================= diseño
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--paper:#f6f4ef;--ink:#111c2b;--muted:#5f6b7a;--line:#e2ded5;--navy:#0f2742;--navy2:#153459;
--blue:#1f4f8a;--gold:#e0a526;--gold2:#f3d9a0;--ok:#0f7a4c;--no:#b5473a;
--ease:cubic-bezier(.16,1,.3,1)}
@property --n{syntax:'<integer>';inherits:false;initial-value:0}
html,body{width:1920px;height:1080px;overflow:hidden}
body{font-family:'Inter',sans-serif;color:var(--ink);background:var(--paper);position:relative;-webkit-font-smoothing:antialiased}
body.dark{background:var(--navy);color:#fff}
h1,h2,h3,.m{font-family:'Montserrat',sans-serif;letter-spacing:-.015em}
svg.lucide{width:1em;height:1em;stroke-width:1.75}

/* fondo vivo: manchas de color que se desplazan muy despacio + grano */
.bg{position:absolute;inset:0;overflow:hidden;z-index:0}
.blob{position:absolute;border-radius:50%;filter:blur(90px);opacity:.55}
.b1{width:900px;height:900px;left:-250px;top:-350px;background:#f1dfb5;animation:drift1 60s linear infinite}
.b2{width:1000px;height:1000px;right:-350px;bottom:-500px;background:#d7e2f0;animation:drift2 70s linear infinite}
body.dark .b1{background:#274b7a;opacity:.6}
body.dark .b2{background:#6b5320;opacity:.35}
@keyframes drift1{0%{transform:translate(0,0)}50%{transform:translate(260px,140px)}100%{transform:translate(0,0)}}
@keyframes drift2{0%{transform:translate(0,0)}50%{transform:translate(-240px,-120px)}100%{transform:translate(0,0)}}
.grain{position:absolute;inset:-100px;background:url(GRAIN) repeat;opacity:.07;z-index:40;pointer-events:none;animation:grain 1s steps(6) infinite}
body.dark .grain{opacity:.1}
@keyframes grain{0%{transform:translate(0,0)}20%{transform:translate(-37px,21px)}40%{transform:translate(18px,-44px)}60%{transform:translate(-12px,33px)}80%{transform:translate(41px,9px)}100%{transform:translate(0,0)}}

/* cámara: acercamiento lento durante cada escena */
.cam{position:absolute;inset:0;z-index:2;transform-origin:50% 50%;animation:push 80s linear both}
@keyframes push{from{transform:scale(1)}to{transform:scale(1.06)}}
.stage{position:absolute;left:150px;right:150px;top:120px;bottom:130px;display:flex;flex-direction:column;justify-content:center}

/* marca */
.bug{position:absolute;left:150px;bottom:54px;z-index:30;font-size:21px;color:var(--muted);display:flex;gap:14px;align-items:center;letter-spacing:.02em}
.bug b{color:var(--ink);font-weight:600}
.bug i{width:28px;height:2px;background:var(--gold);display:inline-block}
.logo{position:absolute;right:150px;bottom:50px;z-index:30;font-family:'Montserrat';font-weight:800;font-size:26px;letter-spacing:-.01em;color:var(--navy)}
.logo span{color:var(--gold)}
body.dark .bug{color:#8ea3bb} body.dark .bug b{color:#fff} body.dark .logo{color:#fff}

/* entradas */
.a{animation:up 1s var(--ease) both;animation-delay:var(--d,0s)}
.af{animation:fade 1.1s ease both;animation-delay:var(--d,0s)}
.ar{animation:right 1s var(--ease) both;animation-delay:var(--d,0s)}
.as{animation:scl 1s var(--ease) both;animation-delay:var(--d,0s)}
@keyframes up{from{opacity:0;transform:translateY(34px)}to{opacity:1;transform:none}}
@keyframes right{from{opacity:0;transform:translateX(-40px)}to{opacity:1;transform:none}}
@keyframes fade{from{opacity:0}to{opacity:1}}
@keyframes scl{from{opacity:0;transform:scale(.92)}to{opacity:1;transform:none}}
.w{display:inline-block;overflow:hidden;vertical-align:top;padding-bottom:.08em;margin-bottom:-.08em}
.wi{display:inline-block;animation:wup 1s var(--ease) both;animation-delay:var(--d,0s)}
@keyframes wup{from{transform:translateY(105%)}to{transform:none}}
.rule{height:4px;width:120px;background:var(--gold);transform-origin:left}
.rule.g{animation:grow 1.2s var(--ease) both;animation-delay:var(--d,0s)}
@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.hide{visibility:hidden}

.kick{font-size:24px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--gold)}
h2.t{font-size:62px;font-weight:800;line-height:1.1;margin-top:22px}

/* apertura / capítulo / cierre */
.hero{font-size:112px;font-weight:800;line-height:1.02;margin-top:30px;max-width:1500px}
.lead{font-size:40px;color:#b9c7d8;margin-top:36px;font-weight:400}
.chap{display:flex;align-items:center;gap:70px}
.chap .num{font-family:'Montserrat';font-weight:800;font-size:260px;line-height:1;color:transparent;-webkit-text-stroke:3px rgba(224,165,38,.9)}
.chap h1{font-size:96px;font-weight:800;line-height:1.05}
.done{width:130px;height:130px}
.done circle{fill:none;stroke:var(--gold);stroke-width:5;stroke-dasharray:380;animation:draw 1.2s var(--ease) both;animation-delay:.2s}
.done path{fill:none;stroke:var(--gold);stroke-width:7;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:80;animation:draw .8s var(--ease) both;animation-delay:.8s}
@keyframes draw{from{stroke-dashoffset:var(--len,380)}to{stroke-dashoffset:0}}
.next{margin-top:60px;font-size:30px;color:#b9c7d8;display:flex;gap:16px;align-items:center}
.next b{color:#fff;font-weight:600}

/* comparar */
.cols{display:grid;grid-template-columns:1fr 1fr;gap:40px;margin-top:56px}
.col{background:#fff;border-radius:6px;padding:44px 50px 48px;box-shadow:0 1px 0 var(--line),0 24px 60px -30px rgba(17,28,43,.25);border-top:5px solid var(--navy)}
.col .hd{display:flex;justify-content:space-between;align-items:center}
.col .lab{font-size:22px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.col .ci{font-size:46px;color:var(--gold)}
.col h3{font-size:52px;font-weight:800;margin-top:22px;color:var(--navy)}
.col p{font-size:32px;line-height:1.45;margin-top:16px;color:#334155}
.nota{margin-top:44px;font-size:30px;color:var(--ink);display:flex;gap:20px;align-items:center}
.nota .bar{width:6px;align-self:stretch;background:var(--gold);border-radius:3px}

/* línea de tiempo */
.tl{margin-top:80px}
.tl .row{display:grid;grid-template-columns:repeat(12,1fr);gap:12px}
.mes{height:110px;border-radius:4px;background:#e7e2d7;position:relative;overflow:hidden}
.mes i{position:absolute;inset:0;background:var(--navy);transform-origin:left}
.mes i.on{animation:grow .7s var(--ease) both;animation-delay:var(--d,0s)}
.mes.hl i{background:var(--gold)}
.lbls{display:grid;grid-template-columns:repeat(12,1fr);gap:12px;margin-top:16px;font-size:26px;color:var(--muted);text-align:center;font-weight:500}
.brk{display:grid;grid-template-columns:repeat(12,1fr);gap:12px;height:90px;margin-bottom:12px}
.brk div{border:3px solid var(--gold);border-bottom:none;border-radius:8px 8px 0 0;position:relative;height:30px;align-self:end}
.brk span{position:absolute;left:50%;bottom:44px;transform:translateX(-50%);white-space:nowrap;font-size:28px;font-weight:700;color:var(--ink)}
.tltext{margin-top:54px;font-size:38px;font-weight:500;min-height:60px}
.tltext.big{font-family:'Montserrat';font-weight:800;font-size:64px;color:var(--navy)}

/* dos listas */
.dl{display:grid;grid-template-columns:1fr 1fr;gap:60px;margin-top:60px}
.dl h3{font-size:28px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;display:flex;gap:14px;align-items:center;padding-bottom:18px;border-bottom:2px solid var(--line)}
.dl .si h3{color:var(--ok)} .dl .no h3{color:var(--no)}
.dl li{list-style:none;font-size:40px;padding:22px 0;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
.dl li svg{font-size:34px}
.dl .si li svg{color:var(--ok)} .dl .no li svg{color:var(--no)}

/* cálculo */
.calc{display:grid;grid-template-columns:.8fr 1.2fr;gap:70px;margin-top:56px;align-items:start}
.facts{border-left:5px solid var(--gold);padding-left:36px}
.facts .f{padding:18px 0}
.facts .f span{display:block;font-size:24px;color:var(--muted);letter-spacing:.04em}
.facts .f b{display:block;font-size:40px;font-weight:700;margin-top:4px}
.ledger{background:#fff;border-radius:6px;padding:26px 54px 34px;box-shadow:0 1px 0 var(--line),0 24px 60px -30px rgba(17,28,43,.25)}
.lr{display:grid;grid-template-columns:60px 1fr auto;align-items:center;font-size:36px;padding:22px 0;border-bottom:1px solid var(--line)}
.lr .op{font-family:'Inter';font-weight:700;color:var(--gold);font-size:40px}
.lr b{font-weight:700;font-variant-numeric:tabular-nums}
.tot{display:flex;justify-content:space-between;align-items:baseline;margin-top:26px}
.tot > span{font-size:30px;font-weight:600;color:var(--muted);letter-spacing:.04em;text-transform:uppercase}
.tot b{font-family:'Montserrat';font-size:92px;font-weight:800;color:var(--navy)}
.tot b small{font-size:.5em;color:var(--gold);margin-right:16px}
.count{counter-reset:n var(--n);animation:cnt 1.6s var(--ease) both;animation-delay:var(--d,0s)}
.count::after{content:counter(n)}
@keyframes cnt{from{--n:0}to{--n:var(--to)}}

/* cifra */
.big{align-items:flex-start}
.bignum{font-family:'Montserrat';font-weight:800;font-size:300px;line-height:1;color:var(--navy);margin-top:24px;display:flex;align-items:baseline;gap:40px}
.bignum small{font-size:110px;color:var(--gold)}
.big p{font-size:40px;color:var(--muted);margin-top:40px;max-width:1300px}

/* puntos */
.pts{margin-top:52px}
.pt{display:flex;align-items:center;gap:34px;padding:26px 0;border-bottom:1px solid var(--line);font-size:40px;position:relative}
.pt .pi{flex:none;width:72px;height:72px;border-radius:50%;border:2px solid var(--line);display:flex;align-items:center;justify-content:center;font-size:34px;color:var(--muted);background:#fff}
.pt.now .pi{background:var(--navy);border-color:var(--navy);color:#fff}
.pt.now{font-weight:600}
.pt.past{opacity:.5}
.pt.dim{animation:dimk .8s ease both}
@keyframes dimk{from{opacity:1}to{opacity:.5}}

/* resumen */
.sum{display:grid;grid-template-columns:1fr 1fr;gap:34px 60px;margin-top:56px}
.si2{border-top:4px solid var(--navy);padding-top:24px}
.si2 h3{font-size:36px;font-weight:800;color:var(--navy);display:flex;gap:16px;align-items:center}
.si2 h3 svg{color:var(--gold)}
.si2 p{font-size:31px;line-height:1.45;margin-top:12px;color:#334155}

/* preguntas */
.qa{justify-content:flex-start;padding-top:10px}
.qtop{display:flex;justify-content:space-between;align-items:center;height:120px}
.q{font-size:54px;font-weight:700;line-height:1.22;margin-top:10px;max-width:1500px}
.ops{display:grid;grid-template-columns:1fr 1fr;gap:22px 34px;margin-top:54px}
.opt{display:flex;align-items:center;gap:26px;background:#fff;border-radius:6px;padding:28px 34px;font-size:36px;box-shadow:0 1px 0 var(--line),0 18px 40px -28px rgba(17,28,43,.3)}
.opt .l{flex:none;width:58px;height:58px;border-radius:50%;border:2px solid var(--line);display:flex;align-items:center;justify-content:center;font-family:'Montserrat';font-weight:800;font-size:26px;color:var(--navy)}
.opt.ok{background:var(--navy);color:#fff}
.opt.ok .l{background:var(--gold);border-color:var(--gold);color:var(--navy)}
.opt.ok.an{animation:okf .9s var(--ease) both;animation-delay:.1s}
@keyframes okf{from{background:#fff;color:var(--ink)}to{background:var(--navy);color:#fff}}
.opt.off{opacity:.35}
.opt.off.an{animation:offf .7s ease both}
@keyframes offf{from{opacity:1}to{opacity:.35}}
.timer{position:relative;width:110px;height:110px;display:flex;align-items:center;justify-content:center}
.timer svg{position:absolute;inset:0;transform:rotate(-90deg)}
.timer circle{fill:none;stroke-width:6}
.timer .bgc{stroke:var(--line)}
.timer .fg{stroke:var(--gold);stroke-dasharray:314;stroke-linecap:round;animation:ring 5s linear both}
@keyframes ring{from{stroke-dashoffset:0}to{stroke-dashoffset:314}}
.timer .num{font-family:'Montserrat';font-weight:800;font-size:44px;color:var(--navy);counter-reset:n var(--n);animation:cd 5s steps(5,end) both}
.timer .num::after{content:counter(n)}
@keyframes cd{from{--n:5}to{--n:0}}
.hint{font-size:24px;color:var(--muted);margin-right:24px}
.exp{margin-top:40px;font-size:32px;line-height:1.45;display:flex;gap:22px;max-width:1500px}
.exp .bar{flex:none;width:6px;background:var(--gold);border-radius:3px}
"""

CLOCK_JS = """<script>
window.__set = (tl, ts, tg) => {
  for (const a of document.getAnimations()) {
    a.pause();
    const el = a.effect && a.effect.target;
    const c = el && el.dataset ? el.dataset.clock : null;
    a.currentTime = (c === 'g' ? tg : c === 's' ? ts : tl) * 1000;
  }
};
window.__end = () => Math.max(0, ...document.getAnimations()
  .filter(a => !(a.effect.target.dataset && a.effect.target.dataset.clock))
  .map(a => a.effect.getComputedTiming().endTime));
</script>"""


def page(body, dark, les, grain_uri):
    css = CSS.replace("GRAIN", grain_uri)
    bug = f'<div class="bug"><i></i><b>Lección {esc(les["id"])}</b>{esc(les["titulo"])}</div>'
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<link rel="stylesheet" href="{FONTS_CSS}"><style>{css}</style>{CLOCK_JS}</head>
<body class="{'dark' if dark else ''}">
<div class="bg"><div class="blob b1" data-clock="g"></div><div class="blob b2" data-clock="g"></div></div>
<div class="cam" data-clock="s">{body}</div>
{bug}<div class="logo">segania<span>.</span></div><div class="grain" data-clock="g"></div>
</body></html>"""


def A(cls, new, d):
    return f' {cls}" style="--d:{d:.2f}s' if new else ""


def H(text, new, d0=0.0, step=0.06):
    """Titular con palabras que suben desde una máscara."""
    if not new:
        return esc(text)
    return " ".join(f'<span class="w"><span class="wi" style="--d:{d0 + i*step:.2f}s">{esc(w)}</span></span>'
                    for i, w in enumerate(text.split()))


# ======================================================================= escenas
def pasos_de(les):
    out = []
    for si, e in enumerate(les["escenas"]):
        t = e["tipo"]
        voces = e.get("voz") if isinstance(e.get("voz"), list) else [e.get("voz")]

        def add(body, voz, dark=False, fijo=None):
            out.append(dict(body=body, voz=voz, dark=dark, fijo=fijo, escena=si))

        if t == "apertura":
            add(f"""<div class="stage"><div class="kick a" style="--d:.3s">{esc(les['modulo'])} · Lección {esc(les['id'])}</div>
<h1 class="hero">{H(e['titulo'], True, .5, .09)}</h1><div class="rule g" style="--d:1.1s;margin-top:40px"></div>
<p class="lead a" style="--d:1.3s">{esc(e['subtitulo'])}</p></div>""", voces[0], dark=True)

        elif t == "capitulo":
            add(f"""<div class="stage"><div class="chap"><div class="num as" style="--d:.1s">{esc(e['numero'])}</div>
<div><div class="rule g" style="--d:.4s"></div><h1 style="margin-top:30px">{H(e['titulo'], True, .45, .08)}</h1></div></div></div>""",
                voces[0], dark=True)

        elif t == "comparar":
            n_el = len(e["cols"]) + (1 if e.get("nota") else 0)
            vis_list = list(range(1, len(voces) + 1)) if len(voces) > 1 else [n_el]
            prev = 0
            for k, vis in enumerate(vis_list):
                first = k == 0
                cols = ""
                for i, c in enumerate(e["cols"]):
                    new = prev <= i < vis
                    cols += (f'<div class="col{" hide" if i >= vis else ""}{A("a", new, .45 + .15*(i-prev) if first else .1)}">'
                             f'<div class="hd"><span class="lab">{esc(c["etiqueta"])}</span><span class="ci">{ic(c["icono"])}</span></div>'
                             f'<h3>{esc(c["titulo"])}</h3><p>{esc(c["texto"])}</p></div>')
                nota = ""
                if e.get("nota"):
                    i = len(e["cols"])
                    nota = f'<div class="nota{" hide" if i >= vis else ""}{A("a", prev <= i < vis, .1)}"><span class="bar"></span>{esc(e["nota"])}</div>'
                add(f'<div class="stage"><h2 class="t">{H(e["titulo"], first, .1)}</h2><div class="cols">{cols}</div>{nota}</div>',
                    voces[k] if len(voces) > 1 else voces[0])
                prev = vis

        elif t == "linea":
            estado = {}
            for k, p in enumerate(e["pasos"]):
                first = k == 0
                antes = dict(estado)
                estado.update(p)
                rango = estado.get("rango")
                meses = ""
                for i, m in enumerate(e["meses"]):
                    hl = rango and rango[0] <= i <= rango[1]
                    nuevo_hl = hl and antes.get("rango") != rango
                    if first and not hl:
                        fill = f'<i class="on" style="--d:{.4 + .05*i:.2f}s;background:#c9c1ae"></i>'
                    elif first and hl:
                        fill = f'<i class="on" style="--d:{.4 + .05*i:.2f}s"></i>'
                    elif nuevo_hl:
                        fill = f'<i class="on" style="--d:{.1 + .06*(i-rango[0]):.2f}s"></i>'
                    else:
                        fill = '<i></i>' if hl else '<i style="background:#c9c1ae"></i>'
                    meses += f'<div class="mes{" hl" if hl and not first else ""}">{fill}</div>'
                brk = '<div class="brk">'
                if rango:
                    nuevo = antes.get("rango") != rango
                    style = f"grid-column:{rango[0]+1}/{rango[1]+2}" + (f";--d:{.9 if first else .5}s" if nuevo else "")
                    cls = ' class="a"' if nuevo else ""
                    brk += f'<div{cls} style="{style}"><span>{esc(estado.get("rotulo",""))}</span></div>'
                brk += '</div>'
                lbls = "".join(f"<span>{esc(m)}</span>" for m in e["meses"])
                txt_new = "texto" in p
                tcls = "tltext big" if estado.get("destacar") else "tltext"
                txt = f'<div class="{tcls}{A("a", txt_new, 1.0 if first else .1)}">{esc(estado.get("texto",""))}</div>'
                add(f'<div class="stage"><h2 class="t">{H(e["titulo"], first, .1)}</h2><div class="tl">{brk}<div class="row">{meses}</div>'
                    f'<div class="lbls">{lbls}</div></div>{txt}</div>', voces[k])

        elif t == "dos_listas":
            for k in range(2):
                first = k == 0

                def col(cls, titulo, icono, items, visible, new):
                    lis = "".join(f'<li class="{A("ar", new, (.6 if first else .1) + .12*i).strip()}"><span>{esc(x)}</span>{ic(icono)}</li>'.replace('<li class=""', "<li")
                                  for i, x in enumerate(items))
                    return f'<div class="{cls}{"" if visible else " hide"}"><h3 class="{A("af", new, (.45 if first else 0)).strip()}">{titulo}</h3><ul>{lis}</ul></div>'.replace('<h3 class=""', "<h3")
                si = col("si", f'{ic("check")} Sí se suma', "check", e["si"], True, first)
                no = col("no", f'{ic("x")} No se suma', "x", e["no"], k == 1, k == 1)
                add(f'<div class="stage"><h2 class="t">{H(e["titulo"], first, .1)}</h2><div class="dl">{si}{no}</div></div>', voces[k])

        elif t == "calculo":
            vis_list = e["pasos"]
            n_rows = len(e["filas"])
            prev = 0
            for k, vis in enumerate(vis_list):
                first = k == 0

                def st(i, extra=0.0):
                    new = prev <= i < vis
                    return (" hide" if i >= vis else "") + A("a", new, (.5 if first else .1) + .2*(i-prev) + extra)
                facts = "".join(f'<div class="f"><span>{esc(a)}</span><b>{esc(b)}</b></div>' for a, b in e["datos"])
                rows = "".join(f'<div class="lr{st(1+j)}"><span class="op">{esc(o)}</span><span>{esc(l)}</span><b>{esc(v)}</b></div>'
                               for j, (o, l, v) in enumerate(e["filas"]))
                ir = 1 + n_rows
                new_r = prev <= ir < vis
                val = (f'<span class="count" style="--to:{int(e["resultado"][1])};--d:.5s"></span>' if new_r
                       else (str(e["resultado"][1]) if ir < vis else ""))
                tot = f'<div class="tot{st(ir, .1)}"><span>{esc(e["resultado"][0])}</span><b><small>USD</small>{val}</b></div>'
                body = (f'<div class="stage"><h2 class="t">{H(e["titulo"], first, .1)}</h2><div class="calc">'
                        f'<div class="facts{st(0)}">{facts}</div><div class="ledger{st(1)}">{rows}{tot}</div></div></div>')
                add(body, voces[k])
                prev = vis

        elif t == "cifra":
            add(f"""<div class="stage big"><div class="kick a" style="--d:.3s">{esc(e['etiqueta'])}</div>
<div class="bignum a" style="--d:.45s"><small>{esc(e.get('prefijo',''))}</small><span class="count" style="--to:{int(e['valor'])};--d:.6s"></span></div>
<div class="rule g" style="--d:1.2s;width:260px;margin-top:30px"></div><p class="a" style="--d:1.5s">{esc(e['nota'])}</p></div>""", voces[0])

        elif t == "puntos":
            items = e["items"]
            for k in range(len(voces)):
                first = k == 0
                pts = ""
                for i, it in enumerate(items):
                    if i >= k:
                        c = "pt hide"
                    elif i == k - 1:
                        c = "pt now" + A("ar", True, .05)
                    elif i == k - 2:
                        c = "pt past dim"
                    else:
                        c = "pt past"
                    pts += f'<div class="{c}"><span class="pi">{ic(it["icono"])}</span><span>{esc(it["texto"])}</span></div>'
                add(f'<div class="stage"><h2 class="t">{H(e["titulo"], first, .1)}</h2><div class="pts">{pts}</div></div>', voces[k])

        elif t == "resumen":
            for k in range(len(voces)):
                first = k == 0
                cards = "".join(
                    f'<div class="si2{" hide" if i > k else ""}{A("a", i == k, .5 if first else .1)}"><h3>{ic("check")} {esc(a)}</h3><p>{esc(b)}</p></div>'
                    for i, (a, b) in enumerate(e["items"]))
                add(f'<div class="stage"><h2 class="t">{H(e["titulo"], first, .1)}</h2><div class="sum">{cards}</div></div>', voces[k])

        elif t == "pregunta":
            n = sum(1 for x in les["escenas"][: si + 1] if x["tipo"] == "pregunta")
            tot = sum(1 for x in les["escenas"] if x["tipo"] == "pregunta")

            def q(estado, extra="", anim=False):
                ops = ""
                for i, o in enumerate(e["opciones"]):
                    if estado == "respuesta":
                        c = "opt ok an" if i == e["correcta"] else "opt off an"
                    else:
                        c = "opt" + A("a", anim, .9 + .1*i)
                    ops += f'<div class="{c}"><span class="l">{LETRAS[i]}</span><span>{esc(o)}</span></div>'
                exp = f'<div class="exp a" style="--d:.5s"><span class="bar"></span><span>{esc(e["explicacion"])}</span></div>' if estado == "respuesta" else ""
                return (f'<div class="stage qa"><div class="qtop"><span class="kick{A("af", anim, .2)}">Pregunta {n} de {tot}</span>{extra}</div>'
                        f'<div class="q m">{H(e["pregunta"], anim, .3, .025)}</div><div class="ops">{ops}</div>{exp}</div>')
            add(q("pregunta", anim=True), e["voz_pregunta"])
            timer = ('<div style="display:flex;align-items:center" class="af"><span class="hint">Pausa el video si necesitas más tiempo</span>'
                     '<div class="timer"><svg viewBox="0 0 110 110"><circle class="bgc" cx="55" cy="55" r="50"/><circle class="fg" cx="55" cy="55" r="50"/></svg><span class="num"></span></div></div>')
            add(q("pregunta", timer), None, fijo=float(CUENTA))
            add(q("respuesta"), e["voz_respuesta"])

        elif t == "cierre":
            add(f"""<div class="stage"><svg class="done" viewBox="0 0 130 130"><circle cx="65" cy="65" r="60" style="--len:380"/><path d="M40 67 l17 17 l34 -36" style="--len:80"/></svg>
<h1 class="hero" style="font-size:100px">{H(e['titulo'], True, .6, .1)}</h1>
<p class="lead a" style="--d:1.1s">{esc(e['texto'])}</p>
<div class="next a" style="--d:1.4s">{ic('arrow-right')} Siguiente: <b>{esc(les['siguiente'])}</b></div></div>""", voces[0], dark=True)
        else:
            raise ValueError(t)
    for i, p in enumerate(out):
        p["inicio"] = i == 0 or out[i - 1]["escena"] != p["escena"]
    return out


# ======================================================================= voz
def tts_kokoro(texto, voz, vel):
    global _K
    if "_K" not in globals():
        from kokoro_onnx import Kokoro
        _K = Kokoro(str(TTS_DIR / "kokoro-v1.0.int8.onnx"), str(TTS_DIR / "voices-v1.0.bin"))
    wav, sr = _K.create(texto, voice=voz, speed=vel, lang="es-419")
    return wav.astype(np.float32)


def tts_google(texto, voz, vel):
    key = os.environ["GOOGLE_TTS_API_KEY"]
    lang = "-".join(voz.split("-")[:2])
    body = {"input": {"text": texto}, "voice": {"languageCode": lang, "name": voz},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": SR, "speakingRate": vel}}
    req = urllib.request.Request(f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    data = json.load(urllib.request.urlopen(req, timeout=120))
    wav, _ = sf.read(io.BytesIO(base64.b64decode(data["audioContent"])), dtype="float32")
    return wav


def frase(texto, motor, voz, vel):
    cache = TTS_DIR / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / (hashlib.sha1(f"{motor}|{voz}|{vel}|{texto}".encode()).hexdigest()[:20] + ".wav")
    if f.exists():
        return sf.read(f, dtype="float32")[0]
    wav = (tts_google if motor == "google" else tts_kokoro)(texto, voz, vel)
    # recorta silencios del modelo en los extremos
    idx = np.where(np.abs(wav) > 0.01)[0]
    if len(idx):
        wav = wav[max(0, idx[0] - int(.03*SR)): idx[-1] + int(.08*SR)]
    sf.write(f, wav, SR)
    return wav


def locucion(texto, motor, voz, vel):
    """Sintetiza oración por oración con pausas naturales. Devuelve audio y tiempos de subtítulos."""
    partes = [x.strip() for x in re.split(r"(?<=[.?!])\s+", texto) if x.strip()]
    audio, subs, t = [], [], 0.0
    for i, p in enumerate(partes):
        w = frase(p, motor, voz, vel)
        subs.append((t, t + len(w) / SR, p))
        audio.append(w); t += len(w) / SR
        if i < len(partes) - 1:
            pausa = 0.42 if p.endswith(("?", ":")) else 0.34
            audio.append(np.zeros(int(pausa * SR), np.float32)); t += pausa
    return np.concatenate(audio), subs


# ======================================================================= música
def musica(dur, sr=SRM):
    """Colchón musical suave (acordes sostenidos), generado aquí: sin derechos de terceros."""
    def hz(m): return 440 * 2 ** ((m - 69) / 12)
    acordes = [[41, 53, 57, 60, 64], [45, 52, 55, 60, 64], [38, 50, 53, 57, 60], [43, 50, 55, 59, 62]]  # Fmaj7 Am7 Dm7 G
    seg = 8.0
    L = int(seg * len(acordes) * sr)
    t = np.arange(int(seg * sr) + int(3 * sr)) / sr
    loop = np.zeros(L + int(3 * sr), np.float32)
    rng = np.random.default_rng(3)
    for k, ac in enumerate(acordes):
        env = np.minimum(1, t / 2.5) * np.minimum(1, np.maximum(0, (seg + 3 - t) / 3))
        s = np.zeros_like(t)
        for m in ac:
            f = hz(m)
            for det in (-0.004, 0.0, 0.004):
                ph = rng.uniform(0, 2 * np.pi)
                s += (np.sin(2*np.pi*f*(1+det)*t + ph) + .18*np.sin(4*np.pi*f*(1+det)*t + ph)) / (1 + (m - 40) / 30)
        a = int(k * seg * sr)
        loop[a:a + len(t)] += (s * env).astype(np.float32)
    loop[:int(3*sr)] += loop[L:]            # cierra el ciclo sin cortes
    loop = loop[:L]
    # reverberación simple (convolución circular con cola de ruido que decae)
    ir = rng.standard_normal(int(2.5 * sr)) * np.exp(-np.arange(int(2.5 * sr)) / (0.7 * sr))
    ir = np.concatenate([[1.0], ir * 0.08])
    n = len(loop)
    wet = np.fft.irfft(np.fft.rfft(loop, n) * np.fft.rfft(ir, n), n).astype(np.float32)
    loop = 0.5 * loop + wet
    loop /= np.max(np.abs(loop)) + 1e-9
    out = np.tile(loop, int(np.ceil(dur * sr / n)) + 1)[: int(dur * sr)]
    fade = int(3 * sr)
    out[:fade] *= np.linspace(0, 1, fade); out[-fade:] *= np.linspace(1, 0, fade)
    return out


def mezclar(voz24, dur, work):
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    sf.write(work / "voz_raw.wav", voz24, SR)
    # tratamiento de la voz: limpieza de graves, calidez, presencia, menos sibilancia, compresión suave
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(work / "voz_raw.wav"), "-af",
                    "aresample=48000,highpass=f=70,equalizer=f=160:t=q:w=1:g=2,equalizer=f=3200:t=q:w=1.4:g=2,"
                    "equalizer=f=7000:t=q:w=2:g=-3,acompressor=threshold=0.12:ratio=2.5:attack=8:release=150:makeup=1.6",
                    str(work / "voz.wav")], check=True)
    v, _ = sf.read(work / "voz.wav", dtype="float32")
    n = int(dur * SRM)
    v = np.pad(v, (0, max(0, n - len(v))))[:n]
    m = musica(dur)
    # baja la música cuando hay voz
    hop = SRM // 50
    envv = np.sqrt(np.convolve(v**2, np.ones(hop) / hop, mode="same"))
    act = (envv > 0.02).astype(np.float32)
    k = int(0.6 * SRM)
    act = np.convolve(act, np.ones(k) / k, mode="same")
    gain = 0.16 - 0.10 * np.clip(act * 1.5, 0, 1)
    mix = v + m * gain
    sf.write(work / "mezcla.wav", mix.astype(np.float32), SRM)
    return work / "mezcla.wav"


# ======================================================================= render
def ruido(path):
    from PIL import Image
    rng = np.random.default_rng(1)
    a = (rng.standard_normal((320, 320)) * 42 + 128).clip(0, 255).astype(np.uint8)
    Image.fromarray(a, "L").save(path)


def render_worker(wid, tareas, htmls, frdir):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME)
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        for (i, f0, nf, ts0, tg0) in tareas:
            pg.goto(htmls[i]); pg.evaluate("document.fonts.ready.then(() => true)")
            for k in range(nf):
                tl = k / FPS
                pg.evaluate(f"window.__set({tl}, {ts0 + tl}, {tg0 + tl})")
                pg.screenshot(path=str(frdir / f"{f0 + k:06}.jpg"), type="jpeg", quality=92)
        b.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("leccion")
    ap.add_argument("--motor", choices=["kokoro", "google"], default="kokoro")
    ap.add_argument("--voz", default=None)
    ap.add_argument("--velocidad", type=float, default=None)
    ap.add_argument("--muestras", action="store_true")
    a = ap.parse_args()
    voz = a.voz or ("ef_dora" if a.motor == "kokoro" else "es-US-Chirp3-HD-Kore")
    vel = a.velocidad or (0.96 if a.motor == "kokoro" else 1.0)

    les = json.loads(Path(a.leccion).read_text())
    lid = les["id"]
    work, outd = BASE / "build" / lid, BASE / "salida" / lid
    if work.exists():
        shutil.rmtree(work)
    (work / "fr").mkdir(parents=True); outd.mkdir(parents=True, exist_ok=True)
    ruido(work / "grano.png")
    grain = (work / "grano.png").as_uri()
    pasos = pasos_de(les)
    htmls = []
    for i, p in enumerate(pasos):
        f = work / f"p{i:03}.html"
        f.write_text(page(p["body"], p["dark"], les, grain))
        htmls.append(f.as_uri())

    if a.muestras:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=CHROME)
            pg = b.new_page(viewport={"width": 1920, "height": 1080})
            for i in range(len(pasos)):
                pg.goto(htmls[i]); pg.evaluate("document.fonts.ready.then(() => true)")
                fin = pg.evaluate("window.__end()") / 1000
                pg.evaluate(f"window.__set({fin + .1}, {fin + 3}, {i * 7})")
                pg.screenshot(path=str(work / f"m{i:03}.jpg"), type="jpeg", quality=85)
            b.close()
        print(f"{len(pasos)} muestras en {work}"); return

    # 1) voz y duración de cada paso
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME)
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        fins = []
        for h in htmls:
            pg.goto(h); fins.append(pg.evaluate("window.__end()") / 1000)
        b.close()
    audios, subs_all, dur = [], [], []
    for i, p in enumerate(pasos):
        lead = 0.55 if p["inicio"] else 0.15
        if p["voz"]:
            w, subs = locucion(p["voz"], a.motor, voz, vel)
            d = max(lead + len(w) / SR + (0.75 if p["escena"] != pasos[min(i+1, len(pasos)-1)]["escena"] else 0.35), fins[i] + 0.3)
        else:
            w, subs, d = None, [], max(p["fijo"], fins[i])
        if i == len(pasos) - 1:
            d += 2.5
        nf = math.ceil(d * FPS)
        audios.append((w, lead, subs)); dur.append(nf)
        print(f"  voz {i+1}/{len(pasos)}: {nf/FPS:.1f}s", flush=True)

    # 2) cuadros en paralelo, con reloj local, de escena y global
    f0 = np.concatenate([[0], np.cumsum(dur)]).astype(int)
    esc_ini = {}
    for i, p in enumerate(pasos):
        esc_ini.setdefault(p["escena"], f0[i])
    tareas = [(i, int(f0[i]), dur[i], (f0[i] - esc_ini[p["escena"]]) / FPS, f0[i] / FPS) for i, p in enumerate(pasos)]
    tareas.sort(key=lambda x: -x[2])
    grupos = [[] for _ in range(WORKERS)]
    carga = [0] * WORKERS
    for tk in tareas:
        j = carga.index(min(carga)); grupos[j].append(tk); carga[j] += tk[2]
    procs = [Process(target=render_worker, args=(j, g, htmls, work / "fr")) for j, g in enumerate(grupos)]
    [p.start() for p in procs]; [p.join() for p in procs]
    assert all(p.exitcode == 0 for p in procs), "falló el render"
    print(f"  {int(f0[-1])} cuadros listos", flush=True)

    # 3) fundidos entre escenas (la escena anterior se desvanece con un leve acercamiento)
    from PIL import Image
    nt = int(FUNDIDO * FPS)
    for i, p in enumerate(pasos):
        if i == 0 or not p["inicio"]:
            continue
        prev = Image.open(work / "fr" / f"{f0[i]-1:06}.jpg")
        for k in range(nt):
            x = (k + 1) / (nt + 1)
            e = x * x * (3 - 2 * x)
            s = 1 + 0.03 * e
            W, Hh = int(1920 * s), int(1080 * s)
            pz = prev.resize((W, Hh), Image.BILINEAR).crop(((W-1920)//2, (Hh-1080)//2, (W-1920)//2 + 1920, (Hh-1080)//2 + 1080))
            fp = work / "fr" / f"{f0[i]+k:06}.jpg"
            Image.blend(pz, Image.open(fp), e).save(fp, quality=92)

    # 4) audio: voz + música, sincronizados con los cuadros
    total = f0[-1] / FPS
    pista = np.zeros(int(total * SR) + SR, np.float32)
    subs = []
    for i, (w, lead, ss) in enumerate(audios):
        if w is None:
            continue
        s = int((f0[i] / FPS + lead) * SR)
        pista[s:s + len(w)] += w
        subs += [(f0[i] / FPS + lead + x, f0[i] / FPS + lead + y, txt) for x, y, txt in ss]
    mezcla = mezclar(pista, total, work)

    # 5) video
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    mp4 = outd / f"leccion-{lid}.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(work / "fr" / "%06d.jpg"), "-i", str(mezcla),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-shortest", "-movflags", "+faststart", str(mp4)], check=True)
    shutil.rmtree(work / "fr")

    def ts(s):
        ms = int(round(s * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); se, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{se:02},{ms:03}"
    with open(outd / f"leccion-{lid}.srt", "w") as fh:
        for n, (s, e, txt) in enumerate(subs, 1):
            fh.write(f"{n}\n{ts(s)} --> {ts(e)}\n{txt}\n\n")
    with open(outd / f"preguntas-{lid}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["leccion", "pregunta", "opcion_a", "opcion_b", "opcion_c", "opcion_d", "correcta", "explicacion"])
        for e in les["escenas"]:
            if e["tipo"] == "pregunta":
                w.writerow([lid, e["pregunta"], *e["opciones"], LETRAS[e["correcta"]], e["explicacion"]])
    print(f"listo: {mp4} ({total/60:.1f} min)")


if __name__ == "__main__":
    main()
