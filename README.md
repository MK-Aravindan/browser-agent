# Browser Agent (browser-use 0.7.0)

This project is a rebuilt `browser-use` runner with:

- clean modular structure
- explicit provider/model configuration
- optional CDP auto-attach
- explicit browser launch modes (`own`, `fresh`, `managed`, `auto`)
- tag-aware DOM handling (`include_attributes`)
- step logging and performance-focused defaults

## Project Layout

- `main.py` - entrypoint
- `browser_agent/config.py` - environment and runtime config
- `browser_agent/llm_factory.py` - OpenAI/Gemini LLM creation
- `browser_agent/browser_factory.py` - browser/CDP setup
- `browser_agent/runner.py` - agent runtime and callbacks
- `prompt.txt` - default task input

## Prerequisites

- Python 3.11+
- Chrome/Chromium installed

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
python -m playwright install
```

On macOS/Linux, use `source .venv/bin/activate` instead of PowerShell activation.

## Environment Setup

Create `.env` from `.env.example` and set at least one API key:

- `OPENAI_API_KEY` for OpenAI
- `GOOGLE_API_KEY` for Gemini

Key runtime variables:

- `PROVIDER=auto|openai|gemini`
- `MODEL` (optional override)
- `OPENAI_MODEL`, `GEMINI_MODEL`
- `ALLOWED_DOMAINS=example.com,docs.python.org`
- `INCLUDE_ATTRIBUTES=id,name,role,type,aria-label,data-testid,href`
- `MAX_STEPS=60`
- `FLASH_MODE=true`
- `CONNECT_EXISTING_CDP=true`
- `CDP_PORT=9222`
- `BROWSER_MODE=auto|own|fresh|managed`
- `CHROME_EXECUTABLE_PATH` (optional)
- `FRESH_CHROME_USER_DATA_DIR=.browser-agent/chrome-fresh-profile`
- `ENABLE_DEFAULT_EXTENSIONS=false`
- `KEEP_ALIVE=false`

## Run

Use task from `prompt.txt`:

```powershell
python main.py
```

Run with inline task:

```powershell
python main.py --task "Search browser-use docs and summarize latest Agent params"
```

Useful flags:

- `--prompt-file path/to/task.txt`
- `--max-steps 40`
- `--headless` or `--show-browser`
- `--no-cdp`
- `--browser-mode auto|own|fresh|managed`
- `--cdp-port 9222`
- `--cdp-url http://127.0.0.1:9222`
- `--chrome-path "C:\Program Files\Google\Chrome\Application\chrome.exe"`

### Browser Modes

- `auto`: attach to existing CDP if available; otherwise launch a fresh dedicated Chrome.
- `own`: require an already-running Chrome CDP session (your own browser).
- `fresh`: always launch a separate Chrome instance with its own user-data dir.
- `managed`: let `browser-use` launch internally (Playwright path).

For `own`, start Chrome manually with CDP first:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\ChromeCDP"
```

## Tag and Element Handling

The runner explicitly improves element targeting by:

- passing `include_attributes` to the agent
- extending system guidance to prefer tag-correct controls (button/input/select)
- logging each step action (and optional tag summary with `LOG_DOM_TAG_SUMMARY=true`)

This makes interactions more stable on pages with similar-looking controls.

## Performance Tuning

Defaults are tuned for speed while retaining reasoning quality:

- `FLASH_MODE=true`
- `MAX_ACTIONS_PER_STEP=6`
- `MIN_PAGE_LOAD_WAIT=0.25`
- `NETWORK_IDLE_WAIT=1.0`
- `WAIT_BETWEEN_ACTIONS=0.15`

If the site is flaky, increase the wait values.

## Notes

- Logs are written to `logs/browser_agent.log` by default.
- Default extension auto-download is disabled to avoid slow startup timeouts.
- Set `KEEP_ALIVE=true` only if you want the launched browser session to stay open after run.

## References

- browser-use docs: https://docs.browser-use.com
- Browser parameters: https://docs.browser-use.com/customize/browser/all-parameters
- Agent parameters: https://docs.browser-use.com/customize/agent/all-parameters
- Supported models: https://docs.browser-use.com/customize/supported-models
