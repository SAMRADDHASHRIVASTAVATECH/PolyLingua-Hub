# test.py
"""
Gemini Live Voice — Final single-file streaming app
- Auto-install vosk (attempts pip), auto-download model, streaming + UI.
- Falls back to SpeechRecognition Google path if VOSK/pyaudio unavailable.
"""
import os
import sys
import math
import time
import json
import threading
import queue
import colorsys
import urllib.request
import shutil
import zipfile
import subprocess
from collections import deque
from datetime import datetime

import tkinter as tk
import customtkinter as ctk

import numpy as np
import speech_recognition as sr

# Try import pyaudio early so UI can list devices
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except Exception:
    pyaudio = None
    PYAUDIO_AVAILABLE = False

# ---------------------------
# Try to ensure 'vosk' is installed (attempt pip install if missing)
# ---------------------------
def ensure_vosk_installed(status_callback=None):
    try:
        import vosk  # noqa: F401
        return True
    except Exception:
        if callable(status_callback):
            status_callback("VOSK not found — attempting to install 'vosk' via pip...")
        try:
            cmd = [sys.executable, "-m", "pip", "install", "vosk"]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600)
            out = proc.stdout or ""
            if callable(status_callback):
                status_callback(f"pip install finished (return {proc.returncode}). See console for details.")
                print(out)
            try:
                import importlib
                importlib.invalidate_caches()
                import vosk  # noqa: F401
                return True
            except Exception:
                if callable(status_callback):
                    status_callback("Retrying pip install with --prefer-binary...")
                cmd2 = [sys.executable, "-m", "pip", "install", "--prefer-binary", "vosk"]
                proc2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600)
                if callable(status_callback):
                    print(proc2.stdout or "")
                    status_callback(f"Retry finished (return {proc2.returncode}).")
                try:
                    import importlib
                    importlib.invalidate_caches()
                    import vosk  # noqa: F401
                    return True
                except Exception:
                    if callable(status_callback):
                        status_callback("Automatic pip install failed. Please install vosk manually in the venv.")
                    print("Automatic install failed. Try:")
                    print(f"  {sys.executable} -m pip install vosk")
                    print("If you're on Windows and pip install fails, try installing a prebuilt wheel or use conda.")
                    return False
        except Exception as e:
            if callable(status_callback):
                status_callback(f"pip install error: {e}")
            print("pip install exception:", e)
            return False

# ---------------------- CONFIG ----------------------
CONFIG = {
    "app_title": "Gemini Live Voice — Streaming (final)",
    "geometry": "1300x920",
    "min_size": (1000, 820),
    "font": "Inter",
    "accent": "#7B68EE",
    "bg": "#0D0D26",
    "text": "#D7DAFF",
    "listening": "#63FF88",
    "ready": "#87CEEB",
    "error": "#FF6B6B",
    "wave_height": 120,
    "wave_len": 420,
    "sample_rate": 16000,       # VOSK small model prefers 16k
    "chunk_ms": 20,            # default frame size (you can tune down to 10)
    "partial_update_ms": 80,   # snappier partial updates
    "settings_file": "gemini_stream_settings.json",
    "model_name": "vosk-model-small-en-us-0.15",
    "model_zip": "vosk-model-small-en-us-0.15.zip",
    "model_target_dir": os.path.join("models", "vosk-model-small-en-us-0.15"),
}

CANDIDATE_URLS = [
    "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
    "https://alphacephei.com/kaldi/models/vosk-model-small-en-us-0.15.zip",
    "https://huggingface.co/ambind/vosk-model-small-en-us-0.15/resolve/main/vosk-model-small-en-us-0.15.zip",
]

message_queue = queue.Queue()
segment_queue = queue.Queue()

# ---------------------- Helpers ----------------------
def _clamp01(x):
    try:
        return max(0.0, min(1.0, float(x)))
    except Exception:
        return 0.0

def _clamp255(x):
    try:
        return max(0, min(255, int(round(x))))
    except Exception:
        return 0

def load_settings():
    try:
        if os.path.exists(CONFIG["settings_file"]):
            with open(CONFIG["settings_file"], "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_settings(d):
    try:
        with open(CONFIG["settings_file"], "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass

# ---------------------- Download + extract ----------------------
def _download_with_progress(url, dest_path, status_cb=None, chunk_size=8192, timeout=30):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = resp.getheader("Content-Length")
            total = int(total) if total and total.isdigit() else None
            downloaded = 0
            tmp_path = dest_path + ".part"
            with open(tmp_path, "wb") as out:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if callable(status_cb):
                        try:
                            percent = int(downloaded*100/total) if total else None
                            status_cb(percent, downloaded, total, f"Downloading {os.path.basename(dest_path)}")
                        except Exception:
                            pass
            os.replace(tmp_path, dest_path)
            if callable(status_cb):
                status_cb(100, downloaded, total, "Download complete")
            return True
    except Exception as e:
        if callable(status_cb):
            status_cb(None, 0, 0, f"Download error: {e}")
        return False

def _extract_zip(zip_path, extract_to, status_cb=None):
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.namelist()
            total = len(members)
            for i, name in enumerate(members, start=1):
                zf.extract(name, path=extract_to)
                if callable(status_cb):
                    try:
                        status_cb(int(i*100/total), i, total, f"Extracting {name}")
                    except Exception:
                        pass
        return True
    except Exception as e:
        if callable(status_cb):
            status_cb(None, 0, 0, f"Extract error: {e}")
        return False

def auto_download_model(target_dir, urls, ui_status_callback):
    if os.path.isdir(target_dir):
        ui_status_callback(100, 0, 0, "Model already present")
        return True
    os.makedirs(os.path.dirname(target_dir), exist_ok=True)
    zipname = CONFIG["model_zip"]
    zip_path = os.path.join(os.path.dirname(target_dir), zipname)
    for url in urls:
        ui_status_callback(None, 0, 0, f"Trying: {url}")
        ok = _download_with_progress(url, zip_path, status_cb=ui_status_callback)
        if not ok:
            continue
        ui_status_callback(None, 0, 0, "Extracting model...")
        ok2 = _extract_zip(zip_path, os.path.dirname(target_dir), status_cb=ui_status_callback)
        if ok2:
            possible = os.path.join(os.path.dirname(target_dir), CONFIG["model_name"])
            if os.path.isdir(possible):
                try:
                    os.remove(zip_path)
                except Exception:
                    pass
                ui_status_callback(100, 0, 0, "Model ready")
                if os.path.abspath(possible) != os.path.abspath(target_dir):
                    try:
                        if os.path.exists(target_dir):
                            shutil.rmtree(target_dir)
                        shutil.move(possible, target_dir)
                    except Exception:
                        pass
                return True
            else:
                found = None
                for nm in os.listdir(os.path.dirname(target_dir)):
                    p = os.path.join(os.path.dirname(target_dir), nm)
                    if nm.startswith("vosk-model") and os.path.isdir(p):
                        found = p; break
                if found:
                    try:
                        os.remove(zip_path)
                    except Exception:
                        pass
                    ui_status_callback(100, 0, 0, f"Model ready ({os.path.basename(found)})")
                    if os.path.abspath(found) != os.path.abspath(target_dir):
                        try:
                            if os.path.exists(target_dir):
                                shutil.rmtree(target_dir)
                            shutil.move(found, target_dir)
                        except Exception:
                            pass
                    return True
    ui_status_callback(None, 0, 0, "All downloads failed")
    return False

# ---------------------- Visualizer ----------------------
class GeminiVisualizer:
    def __init__(self, canvas: tk.Canvas, width: int = 1200, height: int = 560):
        self.canvas = canvas
        self.width = max(1, canvas.winfo_width() or width)
        self.height = max(1, canvas.winfo_height() or height)
        self.center = (self.width // 2, int(self.height * 0.44))
        self.bg = CONFIG["bg"]
        self.accent = CONFIG["accent"]
        self.current_amp = 0.0
        self.smoothed = 0.0
        self.peak = 0.0
        self.wave_len = CONFIG["wave_len"]
        self.wave = deque([0.0]*self.wave_len, maxlen=self.wave_len)
        self._create_items()
        self._running = False
        self.particle_angles = [i*(2*math.pi/18.0) for i in range(18)]
        self.start_time = time.time()

    def _safe_itemconfig(self, item, **kwargs):
        try:
            self.canvas.itemconfig(item, **kwargs)
        except Exception:
            safe = {}
            for k, v in kwargs.items():
                if k in ("fill", "outline") and (not isinstance(v, str) or not v.startswith("#")):
                    safe[k] = self.accent
                else:
                    safe[k] = v
            try:
                self.canvas.itemconfig(item, **safe)
            except Exception:
                pass

    def _create_items(self):
        self.bg_rect = self.canvas.create_rectangle(0,0,self.width,self.height, fill=self.bg, outline="")
        self.central_orb = self.canvas.create_oval(0,0,0,0, fill=self.accent, outline="")
        self.central_outline = self.canvas.create_oval(0,0,0,0, outline=self.accent, width=2)
        self.base_ring = self.canvas.create_oval(0,0,0,0, outline=self.accent, width=3)
        self.glow_rings = [ self.canvas.create_oval(0,0,0,0, outline="", width=max(1,3-i//3), dash=(6,8+i*2)) for i in range(8) ]
        self.wave_line = self.canvas.create_line(*([0,0]*self.wave_len), smooth=True, width=2)
        self.vu_bars = [ self.canvas.create_rectangle(0,0,0,0, fill="", outline="") for _ in range(10) ]
        self.particles = [ self.canvas.create_oval(0,0,0,0, fill="", outline="", state="hidden") for _ in range(18) ]
        self._place_static()

    def _place_static(self):
        w, h = self.width, self.height
        cx, cy = self.center
        orb_r = 36
        base_r = 160
        self.canvas.coords(self.central_orb, cx-orb_r, cy-orb_r, cx+orb_r, cy+orb_r)
        self.canvas.coords(self.central_outline, cx-orb_r-6, cy-orb_r-6, cx+orb_r+6, cy+orb_r+6)
        self.canvas.coords(self.base_ring, cx-base_r, cy-base_r, cx+base_r, cy+base_r)
        wave_top = cy + base_r + 18
        wave_left = int(w*0.08)
        wave_right = int(w*0.92)
        wave_h = CONFIG["wave_height"]
        self.wave_area = (wave_left, wave_top, wave_right, wave_top+wave_h)
        points=[]
        for i in range(self.wave_len):
            x = wave_left + (i/(self.wave_len-1))*(wave_right-wave_left)
            y = wave_top + wave_h/2
            points.append((x,y))
        flat=[c for p in points for c in p]
        try:
            self.canvas.coords(self.wave_line, *flat)
            self._safe_itemconfig(self.wave_line, fill=self.accent)
        except Exception:
            pass
        bar_left_x = wave_left - 120
        bar_w, bar_gap = 16, 8
        for i,bar in enumerate(self.vu_bars):
            bx1 = bar_left_x + (bar_w+bar_gap)*i
            by1 = wave_top + wave_h - 2
            bx2 = bx1 + bar_w
            by2 = by1 - 8
            self.canvas.coords(bar, bx1, by1, bx2, by2)
            self._safe_itemconfig(bar, fill=self.accent)

    def on_resize(self, width, height):
        self.width=max(1,width); self.height=max(1,height)
        self.center=(self.width//2,int(self.height*0.44))
        self._place_static()

    def set_amplitude(self,a:float):
        self.current_amp=float(np.clip(a,0.0,1.0))
        self.wave.append(self.current_amp**0.9)

    def start(self):
        if not self._running:
            self._running=True
            self._loop()
    def stop(self):
        self._running=False

    def _loop(self):
        if not self._running: return
        if self.current_amp > self.smoothed: alpha=0.45
        else: alpha=0.08
        self.smoothed += (self.current_amp-self.smoothed)*alpha
        self.peak += (self.smoothed-self.peak)*0.12
        cx,cy=self.center
        orb_base=36
        orb_r=orb_base + self.smoothed*110
        self.canvas.coords(self.central_orb, cx-orb_r, cy-orb_r, cx+orb_r, cy+orb_r)
        outline_op = _clamp01(self.peak*0.9)
        outline_color = self._rainbow_hex(time.time()*0.16, outline_op)
        self._safe_itemconfig(self.central_outline, outline=outline_color, width=2)
        base_r = 160 + self.smoothed*280
        self.canvas.coords(self.base_ring, cx-base_r, cy-base_r, cx+base_r, cy+base_r)
        phase=time.time()*0.14
        for i, ring in enumerate(self.glow_rings):
            radius = base_r + i*28
            self.canvas.coords(ring, cx-radius, cy-radius, cx+radius, cy+radius)
            op=(1.0 - i/(len(self.glow_rings)+1))*(0.85*self.smoothed+0.12)
            self._safe_itemconfig(ring, outline=self._rainbow_hex(phase+i*0.08, _clamp01(op)))
        wave_left, wave_top, wave_right, wave_bottom = self.wave_area
        wave_h = wave_bottom - wave_top
        pts=[]
        n=len(self.wave)
        for i,v in enumerate(self.wave):
            x = wave_left + (i/(n-1))*(wave_right-wave_left)
            y = wave_top + (wave_h/2) - (v*(wave_h*0.48))
            pts.append((x,y))
        flat=[c for p in pts for c in p]
        try:
            self.canvas.coords(self.wave_line, *flat)
        except Exception:
            pass
        intens=int(self.smoothed*len(self.vu_bars))
        for i,bar in enumerate(self.vu_bars):
            try:
                bx1,by1,bx2,by2 = self.canvas.coords(bar)
            except Exception:
                continue
            full_h = wave_bottom - wave_top
            level = (i+1)/len(self.vu_bars)
            new_top = wave_bottom - (level*(full_h*0.6)*(0.6+self.smoothed*0.8))
            self.canvas.coords(bar, bx1, new_top, bx2, wave_bottom-2)
            color_op = 0.9 if i<intens else 0.12
            self._safe_itemconfig(bar, fill=self._rainbow_hex(phase+i*0.05, color_op))
        t=time.time()-self.start_time
        for i,p in enumerate(self.particles):
            ang = self.particle_angles[i] + t*(0.6+(i%4)*0.05) + self.smoothed*2.0
            rad = orb_r*0.9 + (i%6)*18 + self.smoothed*40
            x = cx + math.cos(ang)*rad
            y = cy + math.sin(ang)*(rad*0.6)
            size = 2 + (i%3) + self.smoothed*5
            self.canvas.coords(p, x-size, y-size, x+size, y+size)
            p_op=(0.7*(0.8 - i/len(self.particles)))*(0.8 + self.smoothed*0.4)
            self._safe_itemconfig(p, fill=self._rainbow_hex(phase+i*0.03, _clamp01(p_op)), outline=self._rainbow_hex(phase+i*0.03, _clamp01(p_op)), state="normal")
        self.canvas.after(16, self._loop)

    def _rainbow_hex(self, phase, opacity):
        opacity=_clamp01(opacity)
        r,g,b = colorsys.hsv_to_rgb((phase%1.0),1.0,1.0)
        r,g,b = int(round(r*255)), int(round(g*255)), int(round(b*255))
        try:
            h=CONFIG["bg"].lstrip("#"); br,bg,bb = tuple(int(h[i:i+2],16) for i in (0,2,4))
        except Exception:
            br,bg,bb = (0,0,0)
        blend_r = _clamp255(r*opacity + br*(1.0-opacity))
        blend_g = _clamp255(g*opacity + bg*(1.0-opacity))
        blend_b = _clamp255(b*opacity + bb*(1.0-opacity))
        return f'#{blend_r:02x}{blend_g:02x}{blend_b:02x}'

# ---------------------- Low-latency capture ----------------------
class LowLatencyCapture:
    def __init__(self, rate=CONFIG["sample_rate"], chunk_ms=CONFIG["chunk_ms"], device_index=None):
        self.rate = rate
        self.chunk_ms = chunk_ms
        self.chunk = max(1, int(rate * chunk_ms / 1000))
        self.pa = None
        self.stream = None
        self.running = False
        self.device_index = device_index
        try:
            self.pa = pyaudio.PyAudio() if PYAUDIO_AVAILABLE else None
        except Exception:
            self.pa = None
        self.sink = None

    def list_input_devices(self):
        out=[]
        if not self.pa:
            try:
                self.pa = pyaudio.PyAudio()
            except Exception:
                return out
        try:
            for i in range(self.pa.get_device_count()):
                info = self.pa.get_device_info_by_index(i)
                if info.get("maxInputChannels",0) > 0:
                    out.append((i, info.get("name", f"Device {i}")))
        except Exception:
            pass
        return out

    def start(self):
        if not PYAUDIO_AVAILABLE or not self.pa:
            return False
        if self.running:
            return True
        try:
            self.stream = self.pa.open(format=pyaudio.paInt16, channels=1, rate=self.rate, input=True, frames_per_buffer=self.chunk, input_device_index=self.device_index)
            self.running = True
            threading.Thread(target=self._read_loop, daemon=True).start()
            return True
        except Exception as e:
            message_queue.put({"type":"status","text":f"Mic start failed: {e}","color":CONFIG["error"]})
            return False

    def stop(self):
        self.running=False
        try:
            if self.stream:
                self.stream.stop_stream(); self.stream.close(); self.stream=None
        except Exception:
            pass

    def _read_loop(self):
        while self.running:
            try:
                data = self.stream.read(self.chunk, exception_on_overflow=False)
            except Exception:
                message_queue.put({"type":"amplitude","value":0.0})
                time.sleep(0.05); continue
            arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            rms = 0.0
            if arr.size>0:
                rms = math.sqrt(float(np.mean(arr*arr))) / 32768.0
            message_queue.put({"type":"amplitude","value":rms})
            try:
                if callable(self.sink):
                    self.sink(data)
                else:
                    segment_queue.put(data)
            except Exception:
                pass
            time.sleep(self.chunk_ms / 1000.0 * 0.25)

# ---------------------- VOSK streaming wrapper ----------------------
class VoskStreamer:
    def __init__(self, model_path, sample_rate=CONFIG["sample_rate"], partial_interval_ms=CONFIG["partial_update_ms"]):
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.partial_interval_ms = partial_interval_ms
        self.model = None
        self.rec = None
        self.queue = queue.Queue()
        self.running = False
        self._last_partial_time = 0.0

    def load(self):
        try:
            from vosk import Model, KaldiRecognizer
        except Exception as e:
            message_queue.put({"type":"status","text":f"VOSK import failed: {e}", "color": CONFIG["error"]})
            return False
        if not os.path.isdir(self.model_path):
            message_queue.put({"type":"status","text":"VOSK model path missing","color":CONFIG["error"]})
            return False
        try:
            message_queue.put({"type":"status","text":"Loading VOSK model...","color":CONFIG["ready"]})
            self.model = Model(self.model_path)
            self.rec = KaldiRecognizer(self.model, self.sample_rate)
            try:
                self.rec.SetWords(False)
            except Exception:
                pass
            message_queue.put({"type":"status","text":"VOSK model loaded","color":CONFIG["ready"]})
            return True
        except Exception as e:
            message_queue.put({"type":"status","text":f"VOSK load failed: {e}","color":CONFIG["error"]})
            return False

    def start(self):
        if self.running or self.rec is None:
            return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False

    def feed(self, bts: bytes):
        try:
            self.queue.put_nowait(bts)
        except Exception:
            pass

    def _loop(self):
        import json as _json
        while self.running:
            try:
                bts = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if self.rec.AcceptWaveform(bts):
                    res = self.rec.Result()
                    try:
                        j = _json.loads(res)
                        txt = j.get("text","").strip()
                        if txt:
                            message_queue.put({"type":"transcription","text":txt,"time":datetime.now().strftime("%H:%M:%S")})
                    except Exception:
                        pass
                else:
                    res = self.rec.PartialResult()
                    try:
                        j = _json.loads(res)
                        p = j.get("partial","").strip()
                        now = time.time()*1000.0
                        if p and (now - self._last_partial_time) >= self.partial_interval_ms:
                            self._last_partial_time = now
                            message_queue.put({"type":"partial","text":p})
                    except Exception:
                        pass
            except Exception as e:
                message_queue.put({"type":"status","text":f"VOSK error: {e}","color":CONFIG["error"]})
        # flush final
        try:
            if self.rec:
                res = self.rec.FinalResult()
                j = json.loads(res)
                txt = j.get("text","").strip()
                if txt:
                    message_queue.put({"type":"transcription","text":txt,"time":datetime.now().strftime("%H:%M:%S")})
        except Exception:
            pass

# ---------------------- Google fallback worker ----------------------
class GoogleSegmentWorker:
    def __init__(self, q: queue.Queue, sample_rate=CONFIG["sample_rate"], sample_width=2):
        self.queue=q
        self.recognizer=sr.Recognizer()
        self.sample_rate=sample_rate
        self.sample_width=sample_width
        self.running=False
        self._thread=None

    def start(self):
        if self.running: return
        self.running=True
        self._thread=threading.Thread(target=self._loop, daemon=True); self._thread.start()

    def stop(self):
        self.running=False

    def _loop(self):
        while self.running:
            try:
                raw = segment_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                audio = sr.AudioData(raw, self.sample_rate, self.sample_width)
                try:
                    message_queue.put({"type":"status","text":"Recognizing...", "color":CONFIG["ready"]})
                    text = self.recognizer.recognize_google(audio)
                    if text.strip():
                        self.queue.put({"type":"transcription","text":text,"time":datetime.now().strftime("%H:%M:%S")})
                except sr.UnknownValueError:
                    pass
                except sr.RequestError:
                    self.queue.put({"type":"status","text":"Network/ASR Error","color":CONFIG["error"]})
                finally:
                    self.queue.put({"type":"status","text":"Listening...", "color":CONFIG["listening"]})
            except Exception as e:
                self.queue.put({"type":"status","text":f"Google worker error: {e}","color":CONFIG["error"]})

# ---------------------- Main App ----------------------
class GeminiStreamingAutoDLApp:
    def __init__(self):
        ctk.set_appearance_mode("Dark"); ctk.set_default_color_theme("blue")
        self.root = ctk.CTk()
        self.root.title(CONFIG["app_title"]); self.root.geometry(CONFIG["geometry"])
        self.root.minsize(*CONFIG["min_size"]); self.root.configure(bg=CONFIG["bg"])
        self.settings = load_settings()
        if isinstance(self.settings.get("accent"), str):
            CONFIG["accent"] = self.settings.get("accent")

        # workers & modules
        self.capture = LowLatencyCapture(rate=CONFIG["sample_rate"], chunk_ms=self.settings.get("chunk_ms", CONFIG["chunk_ms"])) if PYAUDIO_AVAILABLE else None
        self.vosk_streamer = None
        self.google_worker = GoogleSegmentWorker(message_queue)
        self.transcript_log=[]
        self.partial_text = ""
        self._build_ui()
        self._start_queue_polling()
        self.visualizer.start()
        threading.Thread(target=self._auto_model_and_start, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.root.grid_rowconfigure(1, weight=1); self.root.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(self.root, fg_color="transparent"); header.grid(row=0,column=0,pady=(8,2),sticky="ew"); header.grid_columnconfigure(0,weight=1)
        title = ctk.CTkLabel(header, text=CONFIG["app_title"], font=(CONFIG["font"],22,"bold")); title.grid(row=0,column=0,sticky="w",padx=18)
        ctrl = ctk.CTkFrame(header, fg_color="transparent"); ctrl.grid(row=0,column=1,sticky="e",padx=18)

        # device selection (if pyaudio available)
        self.device_var = tk.StringVar(value="")
        if PYAUDIO_AVAILABLE and self.capture:
            devices = self.capture.list_input_devices()
            dev_names = ["Default"] + [f"{i}: {n}" for i, n in devices]
            self.device_menu = ctk.CTkComboBox(ctrl, values=dev_names, variable=self.device_var, width=300)
            self.device_menu.grid(row=0, column=0, padx=6)
            # set default
            if dev_names:
                self.device_var.set(dev_names[0])
        else:
            self.device_menu = ctk.CTkLabel(ctrl, text="Mic device: (pyaudio not available)", font=(CONFIG["font"], 10))
            self.device_menu.grid(row=0, column=0, padx=6)

        # model path + load
        self.model_path_var = tk.StringVar(value=self.settings.get("vosk_model_path",""))
        self.model_entry = ctk.CTkEntry(ctrl, placeholder_text="VOSK model path (optional)", width=420, textvariable=self.model_path_var)
        self.model_entry.grid(row=0,column=1,padx=6)
        self.load_model_btn = ctk.CTkButton(ctrl, text="Load VOSK Model (or auto-download)", command=self._on_load_model, width=220)
        self.load_model_btn.grid(row=0,column=2,padx=6)

        # partial slider
        self.partial_var = tk.IntVar(value=self.settings.get("partial_update_ms", CONFIG["partial_update_ms"]))
        self.partial_slider = ctk.CTkSlider(ctrl, from_=30, to=600, number_of_steps=28, command=self._on_partial_change, width=200, variable=self.partial_var)
        self.partial_slider.grid(row=0,column=3,padx=6)
        self.partial_label = ctk.CTkLabel(ctrl, text=f"Partial ms: {self.partial_var.get()}", font=(CONFIG["font"],11))
        self.partial_label.grid(row=0,column=4,padx=6)

        # chunk + calibrate
        ctrl2 = ctk.CTkFrame(self.root, fg_color="transparent"); ctrl2.grid(row=0,column=0,sticky="ew",padx=18,pady=(46,0)); ctrl2.grid_columnconfigure(2,weight=1)
        self.chunk_ms_var = tk.IntVar(value=self.settings.get("chunk_ms", CONFIG["chunk_ms"]))
        self.chunk_slider = ctk.CTkSlider(ctrl2, from_=10, to=120, number_of_steps=23, variable=self.chunk_ms_var, command=self._on_chunk_change, width=260)
        self.chunk_slider.grid(row=0,column=1,padx=(0,8),sticky="w")
        self.chunk_label = ctk.CTkLabel(ctrl2, text=f"Frame(ms): {self.chunk_ms_var.get()}", font=(CONFIG["font"],11))
        self.chunk_label.grid(row=0,column=2,sticky="w")
        self.cal_button = ctk.CTkButton(ctrl2, text="Calibrate (1s)", command=self._calibrate, width=140)
        self.cal_button.grid(row=0,column=3,padx=(12,6))

        # canvas
        canvas_frame = ctk.CTkFrame(self.root, fg_color=CONFIG["bg"], corner_radius=12, border_width=2, border_color=CONFIG["accent"])
        canvas_frame.grid(row=1,column=0,padx=18,pady=12,sticky="nsew"); canvas_frame.grid_rowconfigure(0,weight=1); canvas_frame.grid_columnconfigure(0,weight=1)
        self.canvas = tk.Canvas(canvas_frame, bg=CONFIG["bg"], highlightthickness=0); self.canvas.grid(row=0,column=0,sticky="nsew",padx=12,pady=12)
        self.visualizer = GeminiVisualizer(self.canvas)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # bottom area
        bottom = ctk.CTkFrame(self.root, fg_color="transparent"); bottom.grid(row=2,column=0,padx=20,pady=(6,18),sticky="ew"); bottom.grid_columnconfigure(1,weight=1)
        self.status_label = ctk.CTkLabel(bottom, text="Starting...", text_color=CONFIG["ready"], font=(CONFIG["font"],12))
        self.status_label.grid(row=0,column=0,sticky="w",padx=(4,8))
        self.partial_display = ctk.CTkLabel(bottom, text="", font=(CONFIG["font"],13), text_color="#FFD966")
        self.partial_display.grid(row=0,column=1,sticky="w")
        self.text_box = ctk.CTkTextbox(bottom, height=160, wrap="word", font=(CONFIG["font"],13)); self.text_box.grid(row=0,column=1,sticky="ew",padx=(0,8))
        self.text_box.configure(state="disabled")
        btn_frame = ctk.CTkFrame(bottom, fg_color="transparent"); btn_frame.grid(row=0,column=2,sticky="e")
        self.clear_btn = ctk.CTkButton(btn_frame, text="Clear", command=self.clear_transcript, width=100); self.clear_btn.grid(row=0,column=0,padx=6)
        self.copy_btn = ctk.CTkButton(btn_frame, text="Copy", command=self.copy_transcript, width=100); self.copy_btn.grid(row=0,column=1,padx=6)
        self.export_btn = ctk.CTkButton(btn_frame, text="Export .txt", command=self.export_transcript, width=120); self.export_btn.grid(row=0,column=2,padx=6)
        self.save_btn = ctk.CTkButton(btn_frame, text="Save Settings", command=self._save_settings, width=120); self.save_btn.grid(row=0,column=3,padx=6)

    def _on_canvas_resize(self, event):
        self.visualizer.on_resize(event.width, event.height)

    def _start_queue_polling(self):
        self.root.after(32, self._process_queue)

    def _process_queue(self):
        try:
            while not message_queue.empty():
                msg = message_queue.get_nowait()
                tp = msg.get("type")
                if tp == "amplitude":
                    amp = float(msg.get("value",0.0)) * (self.settings.get("sensitivity",1.0) if isinstance(self.settings.get("sensitivity"), (int,float)) else 1.0)
                    amp = max(0.0, min(1.0, amp))
                    self.visualizer.set_amplitude(amp)
                elif tp == "transcription":
                    txt = msg.get("text","")
                    tstamp = msg.get("time", datetime.now().strftime("%H:%M:%S"))
                    self._append_transcript(tstamp, txt)
                    self.partial_display.configure(text="")
                elif tp == "partial":
                    p = msg.get("text","")
                    self.partial_display.configure(text=f"▸ {p}")
                elif tp == "status":
                    self._set_status(msg.get("text",""), msg.get("color", CONFIG["ready"]))
        except Exception:
            pass
        self.root.after(32, self._process_queue)

    def _set_status(self, txt, color):
        try:
            self.status_label.configure(text=txt, text_color=color)
        except Exception:
            pass

    def _append_transcript(self, tstamp, text):
        self.text_box.configure(state="normal")
        entry = f"[{tstamp}] {text}\n"
        self.text_box.insert(tk.END, entry)
        self.text_box.see(tk.END)
        self.text_box.configure(state="disabled")
        self.transcript_log.append((tstamp, text))

    def _auto_model_and_start(self):
        # start google fallback worker
        self.google_worker.start()
        # select device if pyaudio available
        if self.capture and PYAUDIO_AVAILABLE:
            dev = self.device_var.get()
            if dev and dev != "Default" and ":" in dev:
                try:
                    idx = int(dev.split(":",1)[0])
                    self.capture.device_index = idx
                except Exception:
                    pass
            # apply saved chunk
            cfg_chunk = self.settings.get("chunk_ms")
            if isinstance(cfg_chunk, int):
                self.capture.chunk_ms = cfg_chunk
                self.capture.chunk = max(1, int(self.capture.rate * cfg_chunk / 1000))
            self.capture.start()

        # Attempt to import vosk
        try:
            import vosk  # noqa: F401
            vosk_ok = True
        except Exception:
            vosk_ok = False

        if not vosk_ok:
            message_queue.put({"type":"status","text":"VOSK not available — running fallback", "color": CONFIG["error"]})
            return

        target_dir = self.settings.get("vosk_model_path") or CONFIG["model_target_dir"]
        if os.path.isdir(target_dir):
            self._load_vosk_model(target_dir)
            return

        parent = os.path.dirname(CONFIG["model_target_dir"]) or "."
        os.makedirs(parent, exist_ok=True)

        def ui_progress(percent, done, total, text):
            display = text if percent is None else f"{text} ({percent}%)"
            message_queue.put({"type":"status","text":display,"color":CONFIG["ready"]})

        ok = auto_download_model(CONFIG["model_target_dir"], CANDIDATE_URLS, ui_progress)
        if ok:
            self.settings["vosk_model_path"] = CONFIG["model_target_dir"]
            save_settings(self.settings)
            self._load_vosk_model(CONFIG["model_target_dir"])
        else:
            message_queue.put({"type":"status","text":"Auto-download failed — running fallback", "color": CONFIG["error"]})

    def _on_load_model(self):
        path = self.model_path_var.get().strip()
        if path:
            if not os.path.isdir(path):
                self._set_status("Provided path not found, attempting to auto-download...", CONFIG["error"])
                threading.Thread(target=self._auto_model_and_start, daemon=True).start()
                return
            else:
                self._load_vosk_model(path)
                return
        self._set_status("No model path given — auto-downloading small model...", CONFIG["ready"])
        threading.Thread(target=self._auto_model_and_start, daemon=True).start()

    def _load_vosk_model(self, path):
        def _load():
            try:
                message_queue.put({"type":"status","text":"Loading model...", "color": CONFIG["ready"]})
                vs = VoskStreamer(path, sample_rate=CONFIG["sample_rate"], partial_interval_ms=self.partial_var.get())
                ok = vs.load()
                if ok:
                    if self.vosk_streamer:
                        self.vosk_streamer.stop()
                    self.vosk_streamer = vs
                    self.vosk_streamer.start()
                    message_queue.put({"type":"status","text":"VOSK loaded & streaming", "color": CONFIG["ready"]})
                else:
                    message_queue.put({"type":"status","text":"VOSK load failed", "color": CONFIG["error"]})
            except Exception as e:
                message_queue.put({"type":"status","text":f"VOSK load error: {e}", "color": CONFIG["error"]})
        threading.Thread(target=_load, daemon=True).start()

    def _capture_sink(self, data_bytes):
        try:
            if self.vosk_streamer and self.vosk_streamer.running:
                self.vosk_streamer.feed(data_bytes)
            else:
                try:
                    segment_queue.put_nowait(data_bytes)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_partial_change(self, val):
        try:
            v = int(float(val))
            self.partial_label.configure(text=f"Partial ms: {v}")
            if self.vosk_streamer:
                self.vosk_streamer.partial_interval_ms = v
            self.settings["partial_update_ms"] = v
        except Exception:
            pass

    def _on_chunk_change(self, val):
        try:
            v = int(float(val))
            self.chunk_label.configure(text=f"Frame(ms): {v}")
            if self.capture:
                self.capture.chunk_ms = v
                self.capture.chunk = max(1, int(self.capture.rate * v / 1000))
            self.settings["chunk_ms"] = v
        except Exception:
            pass

    def _calibrate(self):
        try:
            mic = sr.Microphone()
            with mic as source:
                r = sr.Recognizer()
                r.adjust_for_ambient_noise(source, duration=1.0)
                self._set_status("Calibrated", CONFIG["ready"])
        except Exception as e:
            self._set_status(f"Calibrate error: {e}", CONFIG["error"])

    def clear_transcript(self):
        self.text_box.configure(state="normal"); self.text_box.delete("1.0", tk.END); self.text_box.configure(state="disabled"); self.transcript_log=[]
        self._set_status("Cleared transcript", CONFIG["ready"])

    def copy_transcript(self):
        try:
            self.root.clipboard_clear(); self.root.clipboard_append("\n".join(f"[{t}] {s}" for t,s in self.transcript_log))
            self._set_status("Copied to clipboard", CONFIG["ready"])
        except Exception:
            self._set_status("Copy failed", CONFIG["error"])

    def export_transcript(self):
        if not self.transcript_log:
            self._set_status("No transcript to export", CONFIG["error"]); return
        now = datetime.now().strftime("%Y%m%d_%H%M%S"); fname=f"transcript_{now}.txt"
        try:
            with open(fname,"w",encoding="utf-8") as f:
                for t,s in self.transcript_log: f.write(f"[{t}] {s}\n")
            self._set_status(f"Exported {fname}", CONFIG["ready"])
        except Exception as e:
            self._set_status(f"Export failed: {e}", CONFIG["error"])

    def _save_settings(self):
        self.settings["chunk_ms"] = int(self.chunk_ms_var.get()); self.settings["partial_update_ms"] = int(self.partial_var.get())
        save_settings(self.settings); self._set_status("Settings saved", CONFIG["ready"])

    def _on_close(self):
        try:
            if self.capture: self.capture.stop()
            if self.vosk_streamer: self.vosk_streamer.stop()
            self.google_worker.stop()
            self.visualizer.stop()
        except Exception:
            pass
        self.root.after(120, self.root.destroy)

    def run(self):
        self.root.mainloop()

# ---------------------- Startup ----------------------
def main():
    def console_cb(msg):
        try:
            print("[setup]", msg)
        except Exception:
            pass

    # Attempt to ensure vosk is installed (non-blocking UI will still start)
    threading.Thread(target=lambda: ensure_vosk_installed(status_callback=console_cb), daemon=True).start()

    try:
        import vosk  # noqa: F401
        VOSK_AVAILABLE = True
    except Exception:
        VOSK_AVAILABLE = False

    print("PyAudio available:", PYAUDIO_AVAILABLE, "VOSK available:", VOSK_AVAILABLE)
    try:
        app = GeminiStreamingAutoDLApp()
        app.run()
    except Exception as e:
        print("Failed to start app:", e)
        raise

if __name__ == "__main__":
    main()
