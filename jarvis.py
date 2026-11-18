"""
JARVIS — a fully local voice assistant that can control your PC.
================================================================

Brain  : Ollama + qwen2.5  (runs offline)
Ears   : OpenAI Whisper via SpeechRecognition (runs offline)
Mouth  : pyttsx3 (offline)
Hands  : tool-calling layer (open apps, websites, files, send email, etc.)
Face   : tkinter GUI with voice + text input

------------------------------------------------------------------
SETUP (Windows 11, PowerShell)
------------------------------------------------------------------
1. Install Ollama from ollama.com, then once:
       ollama run qwen2.5

2. Python deps:
       pip install ollama pyttsx3 SpeechRecognition openai-whisper keyboard
       pip install pyaudio        # mic input; if it fails: pip install pipwin && pipwin install pyaudio

3. (Optional) email — Gmail App Password, then set env vars and reopen the terminal:
       setx JARVIS_EMAIL_ADDR "you@gmail.com"
       setx JARVIS_EMAIL_PASS "your16charapppassword"

4. Run:
       python jarvis.py

Everything except open_website / send_email works with no internet.
"""

import os
import threading
import subprocess
import webbrowser
import datetime
import smtplib
from email.message import EmailMessage

import tkinter as tk
from tkinter import scrolledtext, messagebox

import ollama

# ---- Optional voice deps: app still runs in text-only mode without them ----
try:
    import pyttsx3
    TTS_OK = True
except Exception:
    TTS_OK = False

try:
    import speech_recognition as sr
    STT_OK = True
except Exception:
    STT_OK = False

try:
    import keyboard          # global hotkey support
    HOTKEY_OK = True
except Exception:
    HOTKEY_OK = False


# ===========================================================================
# CONFIG
# ===========================================================================
MODEL = "qwen2.5"
WHISPER_SIZE = "base"          # tiny / base / small / medium — bigger = more accurate, slower
TTS_RATE = 175
HOTKEY = "ctrl+alt+j"          # press anywhere to talk to JARVIS

SYSTEM_PROMPT = (
    "You are JARVIS, a concise and capable local assistant running on the "
    "user's Windows PC. You can control the computer with the provided tools. "
    "When asked to perform an action, call the appropriate tool instead of "
    "describing it. After a tool runs, confirm what happened in one short "
    "sentence. Keep replies brief and natural since they will be spoken aloud."
)


# ===========================================================================
# 1. TOOLS — the things JARVIS can actually do
# ===========================================================================
APP_MAP = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "explorer": "explorer.exe",
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "vscode": r"C:\Users\uni_2\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "spotify": r"C:\Users\uni_2\AppData\Roaming\Spotify\Spotify.exe",
}


def open_application(name: str) -> str:
    key = name.lower().strip()
    target = APP_MAP.get(key)
    try:
        if target and os.path.exists(target):
            subprocess.Popen([target])
        elif target:
            os.system(f'start "" "{target}"')
        else:
            os.system(f'start "" "{key}"')
        return f"Opened {name}."
    except Exception as e:
        return f"Could not open {name}: {e}"


def open_website(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}."


def get_time(_: str = "") -> str:
    return datetime.datetime.now().strftime("It is %A %d %B %Y, %H:%M.")


def list_files(folder: str = ".") -> str:
    folder = os.path.expanduser(folder)
    try:
        items = os.listdir(folder)
        if not items:
            return f"{folder} is empty."
        return f"{folder} contains: " + ", ".join(items[:40])
    except Exception as e:
        return f"Could not read {folder}: {e}"


def search_files(query: str, root_dir: str = "C:/Users/uni_2") -> str:
    """Find files whose name contains `query` (stops after 15 hits)."""
    root_dir = os.path.expanduser(root_dir)
    hits = []
    try:
        for dirpath, _, filenames in os.walk(root_dir):
            for f in filenames:
                if query.lower() in f.lower():
                    hits.append(os.path.join(dirpath, f))
                    if len(hits) >= 15:
                        return "Found:\n" + "\n".join(hits)
        return ("Found:\n" + "\n".join(hits)) if hits else f"No files matching '{query}'."
    except Exception as e:
        return f"Search failed: {e}"


def system_volume(action: str) -> str:
    """action: 'mute', 'up', or 'down' (uses Windows media keys via nircmd-free fallback)."""
    keymap = {"mute": 0xAD, "down": 0xAE, "up": 0xAF}  # virtual key codes
    vk = keymap.get(action.lower().strip())
    if vk is None:
        return "Volume action must be 'mute', 'up' or 'down'."
    try:
        import ctypes
        for _ in range(1 if action == "mute" else 5):  # nudge a few steps
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        return f"Volume {action}."
    except Exception as e:
        return f"Volume control failed: {e}"


def send_email(to: str, subject: str, body: str) -> str:
    sender = os.getenv("JARVIS_EMAIL_ADDR")
    password = os.getenv("JARVIS_EMAIL_PASS")
    if not sender or not password:
        return "Email not configured. Set JARVIS_EMAIL_ADDR and JARVIS_EMAIL_PASS."
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(sender, password)
            s.send_message(msg)
        return f"Email sent to {to}."
    except Exception as e:
        return f"Failed to send email: {e}"


AVAILABLE = {
    "open_application": open_application,
    "open_website": open_website,
    "get_time": get_time,
    "list_files": list_files,
    "search_files": search_files,
    "system_volume": system_volume,
    "send_email": send_email,
}

# Actions that change things or leave the machine -> confirm before running.
NEEDS_CONFIRMATION = {"send_email"}

TOOLS = [
    {"type": "function", "function": {
        "name": "open_application",
        "description": "Open a desktop application on the Windows computer.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "e.g. chrome, notepad, spotify, vscode"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "open_website",
        "description": "Open a website in the default browser.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "e.g. youtube.com"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "get_time",
        "description": "Get the current date and time.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List files in a folder.",
        "parameters": {"type": "object", "properties": {
            "folder": {"type": "string", "description": "e.g. C:/Users/uni_2/Downloads"}},
            "required": ["folder"]}}},
    {"type": "function", "function": {
        "name": "search_files",
        "description": "Search the user's files by name.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Part of a filename to find"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "system_volume",
        "description": "Adjust system volume.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "description": "mute, up, or down"}},
            "required": ["action"]}}},
    {"type": "function", "function": {
        "name": "send_email",
        "description": "Send an email to someone.",
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            "required": ["to", "subject", "body"]}}},
]


# ===========================================================================
# 2. VOICE — speak (TTS) and listen (STT). Both offline.
# ===========================================================================
def speak(text: str):
    """Fresh engine per call avoids the pyttsx3 'second utterance is silent' bug."""
    if not TTS_OK or not text:
        return
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", TTS_RATE)
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception as e:
        print("TTS error:", e)


_recognizer = sr.Recognizer() if STT_OK else None


def listen() -> str:
    """Record one phrase from the mic and transcribe with local Whisper.

    Returns "" if no speech was detected (no scary error).
    """
    if not STT_OK:
        return ""
    with sr.Microphone() as source:
        _recognizer.adjust_for_ambient_noise(source, duration=0.4)  # auto threshold
        try:
            # timeout = seconds to wait for you to START talking
            # phrase_time_limit = max length of the phrase once you've started
            audio = _recognizer.listen(source, timeout=12, phrase_time_limit=15)
        except sr.WaitTimeoutError:
            return ""  # you didn't start speaking in time — handled gracefully upstream
    # recognize_whisper runs openai-whisper locally and caches the model after first load
    return _recognizer.recognize_whisper(audio, model=WHISPER_SIZE, language="english").strip()


# ===========================================================================
# 3. AGENT LOOP — qwen2.5 decides, tools execute, model summarises
# ===========================================================================
def run_agent(user_text: str, history: list, confirm_fn) -> str:
    history.append({"role": "user", "content": user_text})
    response = ollama.chat(model=MODEL, messages=history, tools=TOOLS)
    msg = response.message
    history.append(msg)

    while msg.tool_calls:
        for call in msg.tool_calls:
            name = call.function.name
            args = call.function.arguments or {}
            fn = AVAILABLE.get(name)
            if fn is None:
                result = f"Unknown tool: {name}"
            elif name in NEEDS_CONFIRMATION and not confirm_fn(name, args):
                result = f"User declined to run {name}."
            else:
                try:
                    result = fn(**args)
                except Exception as e:
                    result = f"Error running {name}: {e}"
            history.append({"role": "tool", "content": str(result), "tool_name": name})

        response = ollama.chat(model=MODEL, messages=history, tools=TOOLS)
        msg = response.message
        history.append(msg)

    return msg.content or "Done."


# ===========================================================================
# 4. GUI
# ===========================================================================
class JarvisApp:
    def __init__(self, root):
        self.root = root
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.busy = False
        self.tts_on = tk.BooleanVar(value=TTS_OK)

        root.title("JARVIS")
        root.configure(bg="#0d1117")
        root.geometry("640x600")

        tk.Label(root, text="J.A.R.V.I.S", bg="#0d1117", fg="#58a6ff",
                 font=("Consolas", 22, "bold")).pack(pady=(14, 2))
        self.status = tk.Label(root, text="Idle", bg="#0d1117", fg="#8b949e",
                               font=("Consolas", 11))
        self.status.pack()

        self.log = scrolledtext.ScrolledText(
            root, wrap=tk.WORD, bg="#161b22", fg="#e6edf3",
            font=("Consolas", 11), insertbackground="#e6edf3",
            relief=tk.FLAT, padx=10, pady=10)
        self.log.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)
        self.log.tag_config("you", foreground="#7ee787")
        self.log.tag_config("jarvis", foreground="#58a6ff")
        self.log.config(state=tk.DISABLED)

        row = tk.Frame(root, bg="#0d1117")
        row.pack(fill=tk.X, padx=14, pady=(0, 8))
        self.entry = tk.Entry(row, bg="#161b22", fg="#e6edf3", relief=tk.FLAT,
                              font=("Consolas", 12), insertbackground="#e6edf3")
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        self.entry.bind("<Return>", lambda e: self.on_send())
        tk.Button(row, text="Send", command=self.on_send, bg="#238636", fg="white",
                  relief=tk.FLAT, font=("Consolas", 11, "bold"), padx=14).pack(side=tk.LEFT, padx=(8, 0))

        ctrl = tk.Frame(root, bg="#0d1117")
        ctrl.pack(fill=tk.X, padx=14, pady=(0, 14))
        self.mic_btn = tk.Button(ctrl, text="🎤  Speak", command=self.on_listen,
                                 bg="#1f6feb", fg="white", relief=tk.FLAT,
                                 font=("Consolas", 11, "bold"), padx=14)
        self.mic_btn.pack(side=tk.LEFT)
        if not STT_OK:
            self.mic_btn.config(state=tk.DISABLED, text="🎤  (no mic deps)")
        tk.Checkbutton(ctrl, text="Speak replies", variable=self.tts_on,
                       bg="#0d1117", fg="#8b949e", selectcolor="#161b22",
                       activebackground="#0d1117", font=("Consolas", 10)).pack(side=tk.LEFT, padx=12)

        # ---- global hotkey: press anywhere to talk ----
        if HOTKEY_OK and STT_OK:
            try:
                keyboard.add_hotkey(HOTKEY, self._hotkey_fired)
                hk_text = f"Hotkey: {HOTKEY.upper()} — press anywhere to speak"
            except Exception as e:
                hk_text = f"Hotkey unavailable: {e}"
        elif not HOTKEY_OK:
            hk_text = "Global hotkey off — run: pip install keyboard"
        else:
            hk_text = ""
        if hk_text:
            tk.Label(root, text=hk_text, bg="#0d1117", fg="#6e7681",
                     font=("Consolas", 9)).pack(pady=(0, 6))

        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._append("jarvis", "Online and ready. How can I help?")
        if self.tts_on.get():
            threading.Thread(target=speak, args=("Online and ready.",), daemon=True).start()

    def _hotkey_fired(self):
        """Called from the keyboard library's background thread."""
        if not self.busy:
            self.on_listen()

    def on_close(self):
        if HOTKEY_OK:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        self.root.destroy()

    # ---- thread-safe GUI helpers ----
    def _append(self, who, text):
        label = "You" if who == "you" else "JARVIS"
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, f"{label}: ", who)
        self.log.insert(tk.END, text + "\n\n")
        self.log.config(state=tk.DISABLED)
        self.log.see(tk.END)

    def append(self, who, text):
        self.root.after(0, lambda: self._append(who, text))

    def set_status(self, text):
        self.root.after(0, lambda: self.status.config(text=text))

    def set_busy(self, busy):
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.root.after(0, lambda: self.mic_btn.config(
            state=tk.DISABLED if (busy or not STT_OK) else tk.NORMAL))

    # ---- confirmation dialog marshalled to the main thread ----
    def confirm(self, name, args):
        box = {}
        done = threading.Event()

        def ask():
            box["ok"] = messagebox.askyesno("JARVIS — confirm action",
                                            f"Allow this action?\n\n{name}\n{args}")
            done.set()
        self.root.after(0, ask)
        done.wait()
        return box.get("ok", False)

    # ---- actions ----
    def on_send(self):
        if self.busy:
            return
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        self.append("you", text)
        threading.Thread(target=self._process, args=(text,), daemon=True).start()

    def on_listen(self):
        if self.busy:
            return
        threading.Thread(target=self._listen_then_process, daemon=True).start()

    def _listen_then_process(self):
        self.set_busy(True)
        self.set_status("🎤 Listening — speak now…")
        try:
            text = listen()
        except Exception as e:
            self.append("jarvis", f"Mic error: {e}")
            self.set_status("Idle")
            self.set_busy(False)
            return
        if not text:
            self.set_status("Idle")
            self.append("jarvis", "I didn't catch anything — press the hotkey and speak when it says 'Listening'.")
            self.set_busy(False)
            return
        self.append("you", text)
        self._process(text, already_busy=True)

    def _process(self, text, already_busy=False):
        if not already_busy:
            self.set_busy(True)
        self.set_status("Thinking…")
        try:
            reply = run_agent(text, self.history, self.confirm)
        except Exception as e:
            reply = f"Something went wrong: {e}"
        self.append("jarvis", reply)
        if self.tts_on.get():
            self.set_status("Speaking…")
            speak(reply)
        self.set_status("Idle")
        self.set_busy(False)


if __name__ == "__main__":
    root = tk.Tk()
    JarvisApp(root)
    root.mainloop()