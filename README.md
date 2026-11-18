# JARVIS: Offline Voice Assistant

> **Personal project**: built in my own time
> **Dates:** May 2026 to June 2026
> **Author:** Unais Usmani

JARVIS is a speech-to-speech desktop assistant that runs **fully offline** on a Windows PC and can control the machine through tool calling.

| Part | Technology |
|---|---|
| Brain | Local LLM: Qwen 2.5 via **Ollama**, using its native tool/function-calling API |
| Ears | **Whisper** speech-to-text (via SpeechRecognition), calibrated for ambient noise |
| Mouth | pyttsx3 text-to-speech, using a fresh engine for each reply to avoid a "silent second reply" bug |
| Hands | Tools: open apps and websites, list and search files, change the system volume, send email |
| Face | Tkinter GUI with a conversation log, text and voice input, and a global hotkey (Ctrl+Alt+J) |

Things I had to solve along the way:
- Microphone lock conflicts between the wake-word loop and push-to-talk, fixed with a `threading.Event` pause.
- Windows temp-file locking that broke Whisper.
- Tuning the microphone energy threshold.
- A confirmation step before any risky action, such as sending email.

## Run

```bash
ollama run qwen2.5
pip install ollama pyttsx3 SpeechRecognition openai-whisper keyboard pyaudio
python jarvis.py
```

Email is optional. It reads `JARVIS_EMAIL_ADDR` and `JARVIS_EMAIL_PASS` (a Gmail App Password) from environment variables.
