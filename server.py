"""Voice Generator - local web UI for edge-tts. Run: python server.py  (opens http://localhost:8765)

Supports SSML-style markup in the text:
  <break time="500ms"/>  or  <break time="1.5s"/>      -> silence
  <prosody rate="+20%" pitch="-5Hz" volume="+10%">text</prosody>   (also: slow, fast, x-slow, x-fast, low, high, soft, loud)
  <emphasis>text</emphasis>                              -> slightly slower + louder
Tags can be nested; values add up on top of the speaker's own settings.
"""
import asyncio, importlib, importlib.util, json, os, re, subprocess, sys, tempfile, threading, shutil, webbrowser
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import edge_tts

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
_extra = os.pathsep.join([os.path.join(HERE, "bin"),
                          os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links")])
FFMPEG = shutil.which("ffmpeg") or shutil.which("ffmpeg", path=_extra)
_voices = None

RATE_WORDS = {"x-slow": -40, "slow": -20, "medium": 0, "fast": 20, "x-fast": 40}
PITCH_WORDS = {"x-low": -30, "low": -15, "medium": 0, "high": 15, "x-high": 30}
VOL_WORDS = {"silent": -50, "x-soft": -40, "soft": -20, "medium": 0, "loud": 20, "x-loud": 40}


def fmt(v, unit):
    v = int(round(v))
    return f"{'+' if v >= 0 else ''}{v}{unit}"


def num(s, words):
    s = s.strip().lower()
    if s in words:
        return words[s]
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else 0


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


async def get_voices():
    global _voices
    if _voices is None:
        vs = await edge_tts.list_voices()
        _voices = [{"name": v["ShortName"], "gender": v["Gender"], "locale": v["Locale"]} for v in vs]
        _voices.sort(key=lambda x: (x["locale"], x["name"]))
    return _voices


async def synth(text, voice, rate, pitch, volume, path):
    c = edge_tts.Communicate(text, voice, rate=fmt(clamp(rate, -90, 200), "%"),
                             pitch=fmt(clamp(pitch, -100, 100), "Hz"), volume=fmt(clamp(volume, -90, 100), "%"))
    await c.save(path)


TAG = re.compile(r"<\s*(/?)\s*(break|prosody|emphasis)\b([^>]*?)(/?)\s*>", re.I)


def parse_markup(text, rate, pitch, vol):
    """Return list of ('speech', text, rate, pitch, vol) / ('pause', ms)."""
    items, stack, pos = [], [], 0
    cur = (rate, pitch, vol)

    def add_speech(t):
        t = t.strip()
        if t and re.search(r"\w", t):  # skip pieces with only punctuation (Microsoft returns "no audio")
            items.append(("speech", t) + cur)

    for m in TAG.finditer(text):
        add_speech(text[pos:m.start()])
        pos = m.end()
        closing, name, attrs, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if name == "break":
            tm = re.search(r'time\s*=\s*["\']?([\d.]+)\s*(ms|s)?', attrs, re.I)
            ms = 500
            if tm:
                ms = float(tm.group(1)) * (1000 if (tm.group(2) or "ms").lower() == "s" else 1)
            items.append(("pause", int(clamp(ms, 0, 10000))))
        elif closing:
            if stack:
                cur = stack.pop()
        else:
            stack.append(cur)
            if name == "emphasis":
                cur = (cur[0] - 10, cur[1], cur[2] + 15)
            else:
                def attr(k):
                    a = re.search(k + r'\s*=\s*["\']([^"\']*)["\']', attrs, re.I)
                    return a.group(1) if a else None
                r, p, v = attr("rate"), attr("pitch"), attr("volume")
                cur = (cur[0] + (num(r, RATE_WORDS) if r else 0),
                       cur[1] + (num(p, PITCH_WORDS) if p else 0),
                       cur[2] + (num(v, VOL_WORDS) if v else 0))
    add_speech(text[pos:])
    return items


def join_items(items, out):
    """items: ('file', path) / ('pause', ms). Joins into one mp3."""
    files = [i for i in items if i[0] == "file"]
    if not FFMPEG or all(i[0] == "file" for i in items) and len(items) == 1:
        with open(out, "wb") as o:
            for kind, p in items:
                if kind == "file":
                    with open(p, "rb") as f:
                        o.write(f.read())
        return
    cmd = [FFMPEG, "-y", "-loglevel", "error"]
    labels = []
    n = 0
    for kind, v in items:
        if kind == "file":
            cmd += ["-i", v]
        else:
            if v <= 0:
                continue
            cmd += ["-f", "lavfi", "-t", f"{v / 1000:.3f}", "-i", "anullsrc=r=24000:cl=mono"]
        labels.append(f"[{n}:a]aresample=24000,aformat=channel_layouts=mono[a{n}]")
        n += 1
    fc = ";".join(labels) + ";" + "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
    cmd += ["-filter_complex", fc, "-map", "[out]", "-b:a", "96k", out]
    subprocess.run(cmd, check=True)


async def render(tmp, voice, markup, rate, pitch, vol, counter):
    out = []
    for it in parse_markup(markup, rate, pitch, vol):
        if it[0] == "pause":
            out.append(("pause", it[1]))
        else:
            counter[0] += 1
            p = os.path.join(tmp, f"{counter[0]:04d}.mp3")
            await synth(it[1], voice, it[2], it[3], it[4], p)
            out.append(("file", p))
    return out


async def generate(d):
    tmp = tempfile.mkdtemp()
    counter = [0]
    try:
        vol = d.get("volume", 0)
        if d["mode"] == "single":
            items = await render(tmp, d["voice"], d["text"], d["rate"], d["pitch"], vol, counter)
        else:
            sp = d["speakers"]
            items, first = [], True
            for raw in d["text"].splitlines():
                m = re.match(r"^\s*([A-Za-z0-9]+)\s*[:：]\s*(.+)$", raw)
                if not (m and m.group(1).upper() in sp):
                    continue
                cfg = sp[m.group(1).upper()]
                if not first:
                    items.append(("pause", int(d.get("gap", 400))))
                first = False
                items += await render(tmp, cfg["voice"], m.group(2), cfg["rate"], cfg["pitch"], vol, counter)
        if not any(i[0] == "file" for i in items):
            raise ValueError("Nothing to speak. In Conversation mode use the format  A: your text")
        out = os.path.join(tmp, "o.mp3")
        join_items(items, out)
        with open(out, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- Transcriber (faster-whisper, installed on demand) ----------
INSTALL = {"state": "idle", "msg": ""}  # idle | installing | done | error
_models = {}
_model_lock = threading.Lock()
MODELS = {"base", "small", "medium"}


def fw_installed():
    return importlib.util.find_spec("faster_whisper") is not None


def install_fw():
    INSTALL.update(state="installing", msg="")
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "faster-whisper"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "pip failed")[-600:])
        importlib.invalidate_caches()
        INSTALL.update(state="done")
    except Exception as e:
        INSTALL.update(state="error", msg=str(e))


def stamp(sec):
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def decode_audio(path):
    """Decode any audio/video file to 16 kHz mono float32 (own decoder: newer PyAV versions break faster-whisper's)."""
    import av
    import numpy as np
    chunks = []
    with av.open(path, mode="r") as container:
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(stream):
            for f in resampler.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in resampler.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
    if not chunks:
        raise ValueError("No audio found in this file")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def transcribe(path, model, language, timestamps):
    from faster_whisper import WhisperModel
    audio = decode_audio(path)
    with _model_lock:
        if model not in _models:
            _models[model] = WhisperModel(model, device="cpu", compute_type="int8")
        m = _models[model]
    segs, info = m.transcribe(audio, language=None if language == "auto" else language, vad_filter=True)
    lines = []
    for s in segs:
        t = s.text.strip()
        lines.append(f"[{stamp(s.start)}] {t}" if timestamps else t)
    return {"text": ("\n" if timestamps else " ").join(lines), "language": info.language,
            "duration": round(info.duration)}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif self.path == "/api/voices":
            self._send(200, json.dumps(asyncio.run(get_voices())).encode(), "application/json")
        elif self.path == "/api/transcribe/status":
            self._send(200, json.dumps({"installed": fw_installed(), "install": INSTALL}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/transcribe/install":
            if INSTALL["state"] != "installing" and not fw_installed():
                threading.Thread(target=install_fw, daemon=True).start()
            return self._send(200, b"{}", "application/json")
        if u.path == "/api/transcribe":
            tmp = tempfile.mkdtemp()
            try:
                q = parse_qs(u.query)
                model = q.get("model", ["small"])[0]
                if model not in MODELS:
                    raise ValueError("Unknown model")
                if not fw_installed():
                    raise ValueError("faster-whisper is not installed yet")
                ext = os.path.splitext(q.get("name", [""])[0])[1][:8] or ".audio"
                path = os.path.join(tmp, "in" + re.sub(r"[^A-Za-z0-9.]", "", ext))
                left = int(self.headers["Content-Length"])
                with open(path, "wb") as f:
                    while left > 0:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
                res = transcribe(path, model, q.get("language", ["auto"])[0], q.get("timestamps", ["0"])[0] == "1")
                return self._send(200, json.dumps(res).encode(), "application/json")
            except Exception as e:
                return self._send(400, str(e).encode(), "text/plain")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        if u.path != "/api/generate":
            return self._send(404, b"not found", "text/plain")
        try:
            d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send(200, asyncio.run(generate(d)), "audio/mpeg")
        except Exception as e:
            self._send(400, str(e).encode(), "text/plain")


if __name__ == "__main__":
    print(f"Voice Generator running at http://localhost:{PORT}  (ffmpeg: {'yes' if FFMPEG else 'no - pauses disabled'})")
    webbrowser.open(f"http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
