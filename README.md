# Browser Agent – Setup & Run Guide

This guide gives you copy‑paste commands for Windows, macOS, and Linux to install dependencies (including Playwright), set API keys, and run `main.py`.

---

## 1) Prerequisites

* **Python** 3.8+ (`python --version`)
* **Google Chrome or Chromium** installed and runnable on your machine
* Network access to the domains in `ALLOWED_DOMAINS` (default allows YouTube and Google sign‑in)

> The script can auto‑attach to an existing Chrome **CDP** session or auto‑launch its own.

---

## 2) Create & activate a virtual environment

**Windows (PowerShell/CMD):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

> To exit later: `deactivate`

---

## 3) Install Python packages (Playwright included)

Upgrade tooling:

```bash
python -m pip install -U pip setuptools wheel
```

Install required libraries:

```bash
pip install browser-use python-dotenv psutil playwright openai google-generativeai
```

Install Playwright browsers (Chromium, WebKit, Firefox):

```bash
python -m playwright install
```

**Linux only – optional system deps** (helps with headless/graphics libs):

```bash
# Option A: Let Playwright install common OS deps
sudo python -m playwright install-deps

# Option B: Minimal libs via apt (Debian/Ubuntu)
sudo apt-get update && sudo apt-get install -y \
  libnss3 libatk-bridge2.0-0 libxkbcommon0 libgtk-3-0 libgbm1 libasound2
```

---

## 4) Configure API keys (choose one provider)

### OpenAI

**Windows (PowerShell):**

```powershell
$env:OPENAI_API_KEY="YOUR_OPENAI_KEY"
# Optional aliases
$env:OPENAI_KEY=$env:OPENAI_API_KEY
```

**macOS / Linux:**

```bash
export OPENAI_API_KEY="YOUR_OPENAI_KEY"
# Optional alias
export OPENAI_KEY="$OPENAI_API_KEY"
```

### Google Gemini

**Windows (PowerShell):**

```powershell
$env:GOOGLE_API_KEY="YOUR_GEMINI_KEY"
# Optional alias
$env:GEMINI_API_KEY=$env:GOOGLE_API_KEY
```

**macOS / Linux:**

```bash
export GOOGLE_API_KEY="YOUR_GEMINI_KEY"
# Optional alias
export GEMINI_API_KEY="$GOOGLE_API_KEY"
```

**Optional overrides:**

```bash
# Choose provider explicitly: openai | gemini
export PROVIDER="openai"
# Force a model name (otherwise sensible defaults are used)
export MODEL="gpt-4.1-mini"
```

**.env option** (loaded automatically if present):

```
OPENAI_API_KEY=...
# or
GOOGLE_API_KEY=...
PROVIDER=openai # gemini | openai
MODEL=gpt-5 
# MODEL=gemini-2.5-flash
```

---

## 5) Provide your task

Create `prompt.txt` next to `main.py` with a single line describing what to do:

```
Play "A. R. Rahman – Aalaporaan Thamizhan" on YouTube Music and like the track.
```

---

## 6) Run the agent

```bash
python main.py
```

If Chrome CDP isn’t detected and auto‑launch fails, start Chrome manually then re‑run:

**Windows (PowerShell):**

```powershell
start chrome --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\ChromeCDP"
```

**macOS:**

```bash
open -a "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/.chrome-cdp"
```

**Linux:**

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.chrome-cdp"
```

> To point at an existing CDP, set `CDP_PORT` (e.g., `export CDP_PORT=9222`).

---

## 7) Quick checks if something fails

* **Chrome not found** → ensure Chrome/Chromium is installed and on PATH
* **CDP blocked** (corp devices) → manually launch Chrome with flags above
* **Missing keys** → set one of: `OPENAI_API_KEY` or `GOOGLE_API_KEY`
* **Linux graphics errors** → run the *Linux system deps* commands
* **Domains restricted** → edit `ALLOWED_DOMAINS` in `main.py`

---

## 8) Clean up

```bash
deactivate
rm -rf .venv  # macOS/Linux
# On Windows, just delete the .venv folder in Explorer
```

---

## Copy‑paste summary (macOS/Linux)

```bash
python3 -m venv .venv && source .venv/bin/activate \
&& python -m pip install -U pip setuptools wheel \
&& pip install browser-use python-dotenv psutil playwright openai google-generativeai \
&& python -m playwright install
```

## Copy‑paste summary (Windows PowerShell)

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; \
python -m pip install -U pip setuptools wheel; \
pip install browser-use python-dotenv psutil playwright openai google-generativeai; \
python -m playwright install
```
