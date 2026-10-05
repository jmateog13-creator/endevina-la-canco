#!/usr/bin/env python3
"""Adivina la Canción · servidor local.

Sirve la web, busca vídeos en YouTube (sin clave de API), guarda los quizzes
como archivos .json en la carpeta quizzes/ y lleva las salas del modo móviles
(los alumnos entran desde la misma wifi con un código). Solo usa la biblioteca
estándar.

El editor y la API de gestión solo responden a este ordenador; desde la red
solo se llega a la página del móvil y a las rutas de la sala.

    python3 servidor.py            abre el navegador solo
    python3 servidor.py --no-abrir
"""
import json
import os
import random
import re
import secrets
import socket
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
QUIZ_DIR = os.path.join(BASE, "quizzes")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
ID_RE = re.compile(r"^[a-z0-9-]{1,80}$")


# ---------------------------------------------------------------- YouTube

def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "es-ES,es;q=0.9",
        "Cookie": "CONSENT=YES+cb; SOCS=CAI",  # evita la pantalla de cookies de la UE
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def texto(nodo):
    if not isinstance(nodo, dict):
        return ""
    if "simpleText" in nodo:
        return nodo["simpleText"]
    return "".join(r.get("text", "") for r in nodo.get("runs", []))


def buscar_renderers(nodo, salida):
    if isinstance(nodo, dict):
        vr = nodo.get("videoRenderer")
        if isinstance(vr, dict) and vr.get("videoId"):
            salida.append(vr)
        for v in nodo.values():
            buscar_renderers(v, salida)
    elif isinstance(nodo, list):
        for v in nodo:
            buscar_renderers(v, salida)


def se_puede_incrustar(video_id):
    """oEmbed responde 401 cuando el propietario ha desactivado la inserción."""
    url = ("https://www.youtube.com/oembed?format=json&url="
           + urllib.parse.quote("https://www.youtube.com/watch?v=" + video_id))
    try:
        http_get(url, timeout=6)
        return True
    except urllib.error.HTTPError as e:
        return e.code not in (401, 403, 404)
    except Exception:
        return True  # si no sabemos, lo dejamos pasar


def buscar_youtube(consulta, maximo=5):
    html = http_get("https://www.youtube.com/results?hl=ca&gl=ES&search_query="
                    + urllib.parse.quote(consulta))
    marca = html.find("ytInitialData = ")
    if marca < 0:
        return []
    datos, _ = json.JSONDecoder().raw_decode(html, marca + len("ytInitialData = "))

    renderers = []
    buscar_renderers(datos, renderers)
    candidatos, vistos = [], set()
    for vr in renderers:
        vid = vr["videoId"]
        duracion = texto(vr.get("lengthText"))
        if vid in vistos or not duracion:  # sin duración = directo
            continue
        vistos.add(vid)
        candidatos.append({
            "id": vid,
            "titulo": texto(vr.get("title")),
            "canal": texto(vr.get("ownerText")),
            "duracion": duracion,
        })
        if len(candidatos) >= maximo + 3:
            break

    with ThreadPoolExecutor(max_workers=8) as pool:
        ok = list(pool.map(lambda c: se_puede_incrustar(c["id"]), candidatos))
    return [c for c, bien in zip(candidatos, ok) if bien][:maximo]


# ---------------------------------------------------------------- Quizzes

def slug(nombre):
    s = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50]
    return (s or "quiz") + "-" + format(int(time.time()), "x")


def ruta_quiz(qid):
    if not ID_RE.match(qid or ""):
        return None
    return os.path.join(QUIZ_DIR, qid + ".json")


def listar_quizzes():
    os.makedirs(QUIZ_DIR, exist_ok=True)
    lista = []
    for nombre in os.listdir(QUIZ_DIR):
        if not nombre.endswith(".json"):
            continue
        ruta = os.path.join(QUIZ_DIR, nombre)
        try:
            with open(ruta, encoding="utf-8") as f:
                q = json.load(f)
        except Exception:
            continue
        canciones = q.get("canciones", [])
        lista.append({
            "id": nombre[:-5],
            "nombre": q.get("nombre", "Sin nombre"),
            "total": len(canciones),
            "modificado": os.path.getmtime(ruta),
        })
    lista.sort(key=lambda q: q["modificado"], reverse=True)
    return lista


# ---------------------------------------------------------------- Salas (modo móviles)

SALAS = {}
SALAS_LOCK = threading.Lock()


def nom_xarxa():
    """Nom Bonjour del Mac (acaba amb .local): no canvia encara que canviï la IP."""
    nom = socket.gethostname()
    if not nom.endswith(".local"):
        nom += ".local"
    return nom


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # no envía nada: solo elige la interfaz de salida
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


class Sala:
    def __init__(self, nombre):
        self.codigo = None
        self.token = secrets.token_hex(12)
        self.nombre = nombre
        self.creada = time.time()
        self.cond = threading.Condition()
        self.version = 0
        self.fase = "espera"
        self.ronda = 0
        self.total = 0
        self.pregunta = ""
        self.opciones = []
        self.abierta = False
        self.t0 = 0.0
        self.limite = 15000
        self.correcta = None
        self.jugadores = {}

    # -- siempre con self.cond tomado
    def _cambio(self):
        self.version += 1
        self.cond.notify_all()

    def _ranking(self):
        orden = sorted(self.jugadores.items(), key=lambda kv: -kv[1]["puntos"])
        return [{"id": jid, "nombre": j["nombre"], "puntos": j["puntos"],
                 "ganados": j["ganados"], "acierto": j["acierto"]} for jid, j in orden]

    def _posicion(self, jid):
        for i, fila in enumerate(self._ranking()):
            if fila["id"] == jid:
                return i + 1
        return None

    def unirse(self, nombre, jid=None):
        with self.cond:
            if jid and jid in self.jugadores:
                return jid
            nombre = (nombre or "").strip()[:16] or "Jugador"
            usados = {j["nombre"].lower() for j in self.jugadores.values()}
            base, n = nombre, 2
            while nombre.lower() in usados:
                nombre = "%s %d" % (base[:13], n)
                n += 1
            jid = secrets.token_hex(6)
            self.jugadores[jid] = {"nombre": nombre, "puntos": 0, "respuesta": None,
                                   "ms": None, "ganados": 0, "acierto": None}
            self._cambio()
            return jid

    def responder(self, jid, k):
        with self.cond:
            j = self.jugadores.get(jid)
            if not j:
                return "No ets en aquesta partida"
            if not self.abierta:
                return "Ja no es pot respondre"
            if j["respuesta"] is not None:
                return None
            if not isinstance(k, int) or not 0 <= k < len(self.opciones):
                return "Resposta no vàlida"
            j["respuesta"] = k
            j["ms"] = (time.time() - self.t0) * 1000
            self._cambio()
            return None

    def host(self, accion, datos):
        with self.cond:
            if accion == "pregunta":
                self.fase = "pregunta"
                self.ronda = int(datos.get("ronda", 0))
                self.total = int(datos.get("total", 0))
                self.pregunta = str(datos.get("pregunta", ""))[:60]
                self.opciones = [str(o)[:120] for o in datos.get("opciones", [])][:4]
                self.abierta = False
                self.correcta = None
                for j in self.jugadores.values():
                    j.update(respuesta=None, ms=None, ganados=0, acierto=None)
            elif accion == "abrir":
                self.abierta = True
                self.t0 = time.time()
                self.limite = max(1000, int(datos.get("limiteMs", 15000)))
            elif accion == "resolver":
                self.abierta = False
                self.correcta = int(datos.get("correcta", -1))
                for j in self.jugadores.values():
                    if j["respuesta"] is None:
                        j["acierto"] = None
                    elif j["respuesta"] == self.correcta:
                        rapidez = min(j["ms"], self.limite) / self.limite
                        j["ganados"] = int(round(1000 - 500 * rapidez))
                        j["puntos"] += j["ganados"]
                        j["acierto"] = True
                    else:
                        j["acierto"] = False
                self.fase = "resuelto"
            elif accion in ("ranking", "fin"):
                self.abierta = False
                self.fase = accion
            elif accion == "cerrar":
                self.abierta = False
                self.fase = "cerrada"
            else:
                return None
            self._cambio()
            return self.vista(None)

    def vista(self, jid):
        """Estado para el profe (jid None) o para un jugador concreto."""
        respondidos = sum(1 for j in self.jugadores.values() if j["respuesta"] is not None)
        if jid is None:
            conteo = [0] * len(self.opciones)
            for j in self.jugadores.values():
                if j["respuesta"] is not None and j["respuesta"] < len(conteo):
                    conteo[j["respuesta"]] += 1
            return {"fase": self.fase, "ronda": self.ronda, "abierta": self.abierta,
                    "jugadores": [{"id": k, "nombre": j["nombre"]} for k, j in self.jugadores.items()],
                    "respondidos": respondidos,
                    "conteo": conteo if self.fase != "pregunta" else None,
                    "ranking": self._ranking()}
        j = self.jugadores.get(jid)
        if not j:
            return {"fase": "fuera" if self.fase != "cerrada" else "cerrada"}
        d = {"fase": self.fase, "quiz": self.nombre, "ronda": self.ronda, "total": self.total,
             "pregunta": self.pregunta, "abierta": self.abierta, "jugadores": len(self.jugadores),
             "yo": {"nombre": j["nombre"], "puntos": j["puntos"], "posicion": self._posicion(jid)},
             "miRespuesta": j["respuesta"]}
        if self.fase == "pregunta":
            d["opciones"] = self.opciones
            if self.abierta:
                d["restanteMs"] = max(0, self.limite - (time.time() - self.t0) * 1000)
                d["limiteMs"] = self.limite
        if self.fase in ("resuelto", "ranking", "fin") and self.correcta is not None:
            d["resultado"] = {"acierto": j["acierto"], "ganados": j["ganados"],
                              "correcta": self.opciones[self.correcta] if 0 <= self.correcta < len(self.opciones) else ""}
        return d


def crear_sala(nombre):
    with SALAS_LOCK:
        viejas = [c for c, s in SALAS.items() if time.time() - s.creada > 6 * 3600 or s.fase == "cerrada"]
        for c in viejas:
            del SALAS[c]
        sala = Sala(nombre)
        while True:
            codigo = "%04d" % random.randint(1000, 9999)
            if codigo not in SALAS:
                break
        sala.codigo = codigo
        SALAS[codigo] = sala
        return sala


# ---------------------------------------------------------------- HTTP

class Manejador(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def log_message(self, fmt, *args):
        if self.path.startswith(("/api/buscar", "/api/quizzes")):
            sys.stderr.write("  %s %s\n" % (self.command, self.path[:90]))

    def end_headers(self):
        # las páginas siempre frescas: así una versión nueva se ve sin vaciar la caché
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def es_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def ruta_sala(self, path):
        """/api/sala/<codigo>/<accion> → (sala, accion) o (None, None)."""
        partes = path.strip("/").split("/")
        if len(partes) == 4 and partes[:2] == ["api", "sala"]:
            return SALAS.get(partes[2]), partes[3]
        return None, None

    def eventos(self, sala, jid, es_host):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        visto = -1
        try:
            while True:
                with sala.cond:
                    if sala.version == visto:
                        sala.cond.wait(timeout=15)
                    datos = None
                    if sala.version != visto:
                        visto = sala.version
                        datos = sala.vista(None if es_host else jid)
                if datos is None:
                    self.wfile.write(b": latido\n\n")
                else:
                    self.wfile.write(("data: " + json.dumps(datos, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
                if datos and datos.get("fase") == "cerrada":
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def enviar_json(self, datos, codigo=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def leer_json(self):
        largo = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(largo).decode("utf-8"))

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        if url.path.startswith("/api/sala/") and url.path != "/api/sala/activa":
            sala, accion = self.ruta_sala(url.path)
            if accion != "eventos":
                return self.enviar_json({"error": "Ruta desconeguda"}, 404)
            if not sala:
                return self.enviar_json({"error": "No hi ha cap partida amb aquest codi"}, 404)
            es_host = qs.get("host", [""])[0] == sala.token
            return self.eventos(sala, qs.get("jugador", [""])[0], es_host)
        if url.path in ("/movil", "/movil/"):
            self.path = "/movil.html" + ("?" + url.query if url.query else "")
            return super().do_GET()
        if not self.es_local():
            # desde la red solo se llega al móvil
            if url.path in ("/", "/index.html"):
                self.send_response(302)
                self.send_header("Location", "/movil")
                self.end_headers()
                return
            if url.path == "/api/sala/activa":
                obertes = [c for c, s in SALAS.items() if s.fase != "cerrada"]
                return self.enviar_json({"codigo": obertes[0] if len(obertes) == 1 else None,
                                         "obertes": len(obertes)})
            if url.path != "/movil.html":
                return self.enviar_json({"error": "No disponible"}, 403)
            return super().do_GET()
        if url.path == "/api/buscar":
            q = urllib.parse.parse_qs(url.query).get("q", [""])[0].strip()
            if not q:
                return self.enviar_json({"error": "Falta la cerca"}, 400)
            try:
                return self.enviar_json({"resultados": buscar_youtube(q)})
            except Exception as e:
                return self.enviar_json({"error": "YouTube no ha respost: %s" % e}, 502)
        if url.path == "/api/sala/activa":
            obertes = [c for c, s in SALAS.items() if s.fase != "cerrada"]
            return self.enviar_json({"codigo": obertes[0] if len(obertes) == 1 else None,
                                     "obertes": len(obertes)})
        if url.path == "/api/quizzes":
            return self.enviar_json({"quizzes": listar_quizzes()})
        if url.path.startswith("/api/quizzes/"):
            ruta = ruta_quiz(url.path.rsplit("/", 1)[1])
            if not ruta or not os.path.exists(ruta):
                return self.enviar_json({"error": "No existeix aquest quiz"}, 404)
            with open(ruta, encoding="utf-8") as f:
                return self.enviar_json(json.load(f))
        if url.path.startswith("/quizzes/"):
            return self.enviar_json({"error": "No disponible"}, 404)
        return super().do_GET()

    def do_POST(self):
        try:
            cuerpo = self.leer_json()
        except Exception:
            return self.enviar_json({"error": "Les dades no són un JSON vàlid"}, 400)

        if self.path.startswith("/api/sala/"):
            sala, accion = self.ruta_sala(self.path)
            if not sala or sala.fase == "cerrada":
                return self.enviar_json({"error": "No hi ha cap partida amb aquest codi"}, 404)
            if accion == "unirse":
                jid = sala.unirse(cuerpo.get("nombre"), cuerpo.get("id"))
                return self.enviar_json({"id": jid, "quiz": sala.nombre})
            if accion == "responder":
                error = sala.responder(cuerpo.get("jugador"), cuerpo.get("k"))
                return self.enviar_json({"error": error} if error else {"ok": True}, 409 if error else 200)
            if accion == "host":
                if cuerpo.get("token") != sala.token:
                    return self.enviar_json({"error": "No ets l'amfitrió d'aquesta sala"}, 403)
                estado = sala.host(cuerpo.get("accion"), cuerpo)
                if estado is None:
                    return self.enviar_json({"error": "Acció desconeguda"}, 400)
                if sala.fase == "cerrada":
                    with SALAS_LOCK:
                        SALAS.pop(sala.codigo, None)
                return self.enviar_json(estado)
            return self.enviar_json({"error": "Ruta desconeguda"}, 404)

        if not self.es_local():
            return self.enviar_json({"error": "No disponible"}, 403)
        if self.path == "/api/sala":
            sala = crear_sala(str(cuerpo.get("nombre", ""))[:80])
            puerto = self.server.server_address[1]
            return self.enviar_json({
                "codigo": sala.codigo, "token": sala.token,
                "url": "http://%s:%d/movil" % (ip_local(), puerto),
                "url_nom": "http://%s:%d/movil" % (nom_xarxa(), puerto),
            })
        if self.path != "/api/quizzes":
            return self.enviar_json({"error": "Ruta desconeguda"}, 404)
        quiz = cuerpo
        qid = quiz.get("id") or slug(quiz.get("nombre", "quiz"))
        ruta = ruta_quiz(qid)
        if not ruta:
            qid = slug(quiz.get("nombre", "quiz"))
            ruta = ruta_quiz(qid)
        quiz["id"] = qid
        os.makedirs(QUIZ_DIR, exist_ok=True)
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(quiz, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ruta)
        return self.enviar_json({"id": qid})

    def do_DELETE(self):
        if not self.es_local() or not self.path.startswith("/api/quizzes/"):
            return self.enviar_json({"error": "Ruta desconeguda"}, 404)
        ruta = ruta_quiz(self.path.rsplit("/", 1)[1])
        if ruta and os.path.exists(ruta):
            os.remove(ruta)
        return self.enviar_json({"ok": True})


def main():
    fix = None
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            fix = int(sys.argv[i + 1])
    servidor = None
    for puerto in ([fix] if fix else range(8765, 8780)):
        try:
            servidor = ThreadingHTTPServer(("0.0.0.0", puerto), Manejador)
            break
        except OSError:
            continue
    if not servidor:
        sys.exit("El port %d està ocupat." % fix if fix else "No hi ha cap port lliure entre 8765 i 8779.")
    servidor.daemon_threads = True

    url = "http://localhost:%d/" % servidor.server_address[1]
    print("\n  🎵 Endevina la Cançó està en marxa: %s" % url)
    port = servidor.server_address[1]
    print("  📱 Els alumnes (mateixa wifi) entren a:")
    print("       http://%s:%d/movil   ← enllaç fix, per posar al Moodle" % (nom_xarxa(), port))
    print("       http://%s:%d/movil   ← per IP, si el de dalt no va" % (ip_local(), port))
    print("  Deixa aquesta finestra oberta mentre jugues. Ctrl+C per tancar.\n")
    if "--no-abrir" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n  Fins la propera.")


if __name__ == "__main__":
    main()
