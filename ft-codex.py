#!/usr/bin/env python3
"""FT-CODEX v1.0 - free AI terminal assistant with chat, files, images and memory."""
import os, sys, re, json, glob, shlex, subprocess, importlib.util, threading, time
import urllib.parse, urllib.request, random
from datetime import datetime


OUT_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_FILE_BYTES = 5 * 1024 * 1024
HISTORY_CHAR_LIMIT = 400_000
BIG_REPLY_CHARS = 200_000
MAX_TOKENS = 16000
ENGINE_TIMEOUT = 120
MEMORY_FILE = os.path.join(OUT_DIR, "codex_memory.json")
SESSION_FILE = os.path.join(OUT_DIR, "codex_session.json")
MEMORY_MAX_ITEMS = 200
MEMORY_ITEM_CHARS = 500
VERSION = "1.0.0"


class C:
    RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
    RED = "\033[91m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
    BLUE = "\033[94m"; MAGENTA = "\033[95m"; CYAN = "\033[96m"


def col(text, *codes):
    return "".join(codes) + str(text) + C.RESET


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def hide_cursor(): sys.stdout.write("\033[?25l"); sys.stdout.flush()
def show_cursor(): sys.stdout.write("\033[?25h"); sys.stdout.flush()


def has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def human_size(n):
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _sanitize(text):
    """User-facing text se internal provider/library names hide kar do."""
    s = str(text)
    s = re.sub(r"pollinations\.ai", "service", s, flags=re.I)
    s = re.sub(r"\bpollinations\b", "service", s, flags=re.I)
    for term in ["g4f", "llmf", "fishr", "ddgs", "llm7", "keylessai",
                 "pypdf", "PyPDF2", "python-docx", "rapidapi"]:
        s = re.sub(rf"\b{re.escape(term)}\b", "service", s, flags=re.I)
    return s


class Spinner:
    def __init__(self, message):
        self.message = message
        self.stop_flag = False
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.thread = None

    def _spin(self):
        i = 0
        while not self.stop_flag:
            sys.stdout.write(f"\r  {col(self.frames[i % len(self.frames)], C.CYAN)} {self.message}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1

    def start(self):
        hide_cursor()
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def stop(self, success=True, final_msg=None):
        self.stop_flag = True
        if self.thread:
            self.thread.join(timeout=1)
        sys.stdout.write("\r" + " " * 80 + "\r")
        if final_msg:
            icon = col("✅", C.GREEN) if success else col("❌", C.RED)
            print(f"  {icon} {final_msg}")
        show_cursor()


def auto_install():
    packages = [
        ("requests", "requests", "Network"),
        ("httpx", "httpx", "Network"),
        ("g4f", "g4f", "AI Chat"),
        ("llmf", "llmf", "AI Chat"),
        ("fishr", "fishr", "AI Chat"),
        ("ddgs", "ddgs", "AI Chat"),
        ("Pillow", "PIL", "Image"),
        ("pypdf", "pypdf", "PDF"),
        ("python-docx", "docx", "Document"),
        ("rich", "rich", "UI"),
    ]
    missing = [(pkg, mod, label) for pkg, mod, label in packages if not has_module(mod)]
    ready = [pkg for pkg, mod, label in packages if has_module(mod)]
    print(col(f"\n📦 Installed: {len(ready)} | Missing: {len(missing)}", C.BOLD))
    if not missing:
        print(col("All modules ready. No download needed.", C.GREEN))
        return
    choice = arrow_menu("Module setup:", [
        f"Install {len(missing)} missing modules",
        "Skip downloads and continue",
    ], 0)
    if choice:
        print(col("Downloads skipped. Available features will continue.", C.YELLOW))
        return
    for index, (package, module, label) in enumerate(missing, 1):
        spinner = Spinner(f"Setting up {label} ({index}/{len(missing)})")
        spinner.start()
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", package],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=90, check=False
            )
            installed = has_module(module)
            spinner.stop(installed, f"{label} ready" if installed else f"{label} unavailable")
        except Exception:
            spinner.stop(False, f"{label} setup failed; continuing")


def flatten(messages):
    parts = []
    for m in messages:
        if m["role"] == "system":
            continue
        who = "User" if m["role"] == "user" else "Assistant"
        parts.append(f"{who}: {m['content']}")
    parts.append("Assistant:")
    return "\n\n".join(parts)


def system_of(messages):
    return next((m["content"] for m in messages if m["role"] == "system"), None)


def _http_chat(url, model, messages, headers=None):
    h = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    if headers:
        h.update(headers)
    payload = json.dumps({"model": model, "messages": messages, "max_tokens": MAX_TOKENS}).encode()
    req = urllib.request.Request(url, data=payload, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=ENGINE_TIMEOUT) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
    return json.loads(body)["choices"][0]["message"]["content"]


def engine_primary(messages):
    return _http_chat("https://text.pollinations.ai/openai", "openai", messages)


def engine_alt1(m):
    return _http_chat("https://api.llm7.io/v1/chat/completions", "gpt-4o-mini", m)


def engine_alt2(m):
    from g4f.client import Client
    c = Client()
    r = c.chat.completions.create(model="gpt-4o-mini", messages=m)
    return r.choices[0].message.content


def engine_alt3(messages):
    import llmf
    kw = {"model": "best", "max_tokens": MAX_TOKENS, "temperature": 0.7}
    sp = system_of(messages)
    if sp:
        kw["system"] = sp
    return str(llmf.chat(flatten(messages), **kw))


def engine_alt4(messages):
    from fishr import Client
    c = Client()
    return c.chat.completions.create(model="noxus/openai", messages=messages).text


def engine_alt5(messages):
    from ddgs import DDGS
    return DDGS().chat(flatten(messages), model="gpt-4o-mini")


def engine_alt6(m):
    return _http_chat("https://keylessai.thryx.workers.dev/v1/chat/completions", "gpt-4o", m)


def engine_alt7(m):
    return _http_chat("https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions",
                      "Meta-Llama-3_3-70B-Instruct", m)


ENGINES = {
    "engine1": engine_primary,
    "engine2": engine_alt1,
    "engine3": engine_alt2,
    "engine4": engine_alt3,
    "engine5": engine_alt4,
    "engine6": engine_alt5,
    "engine7": engine_alt6,
    "engine8": engine_alt7,
}
ENGINE_CHOICES = ["auto"] + list(ENGINES)


def _run_timeout(fn, secs, arg):
    box = {}

    def work():
        try:
            box["r"] = fn(arg)
        except Exception:
            box["r"] = None

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(secs)
    return box.get("r")


def _race_engines(names, messages, timeout):
    """Multiple engines parallel race karo - jo pehle successful ho wo return."""
    box = {"ans": None, "name": None}
    lock = threading.Lock()

    def try_engine(name):
        try:
            ans = ENGINES[name](messages)
            if ans and str(ans).strip():
                with lock:
                    if box["ans"] is None:
                        box["ans"] = str(ans).strip()
                        box["name"] = name
        except Exception:
            pass

    threads = [threading.Thread(target=try_engine, args=(n,), daemon=True) for n in names]
    for t in threads:
        t.start()
    end = time.time() + timeout
    while time.time() < end:
        with lock:
            if box["ans"]:
                return box["ans"], box["name"]
        time.sleep(0.05)
    with lock:
        return box["ans"], box["name"]


def get_reply(messages, engine="auto"):
    if engine != "auto":
        if engine not in ENGINES:
            return None, None
        ans = _run_timeout(ENGINES[engine], ENGINE_TIMEOUT + 15, messages)
        if ans and str(ans).strip():
            return str(ans).strip(), engine
        return None, None

    names = list(ENGINES)
    ans = _run_timeout(ENGINES[names[0]], 25, messages)
    if ans and str(ans).strip():
        return str(ans).strip(), names[0]

    rest = names[1:]
    if rest[:4]:
        ans, name = _race_engines(rest[:4], messages, 60)
        if ans:
            return ans, name
    if rest[4:]:
        ans, name = _race_engines(rest[4:], messages, 45)
        if ans:
            return ans, name
    return None, None


IMAGE_MODELS = ["standard", "turbo", "realistic", "anime"]
IMAGE_MODEL_MAP = {
    "standard": "flux",
    "turbo": "turbo",
    "realistic": "flux-realism",
    "anime": "flux-anime",
}


def _save_image_response(data, content_type, prefix):
    if not isinstance(data, (bytes, bytearray)) or len(data) < 1000:
        raise ValueError("image response is empty or too small")
    signatures = [
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"\xff\xd8\xff", ".jpg"),
        (b"RIFF", ".webp"),
        (b"GIF87a", ".gif"),
        (b"GIF89a", ".gif"),
        (b"BM", ".bmp"),
    ]
    extension = None
    for signature, ext in signatures:
        if data.startswith(signature):
            extension = ext
            if ext == ".webp" and data[8:12] != b"WEBP":
                extension = None
            break
    if not extension:
        raise ValueError(f"provider returned invalid image data ({content_type or 'unknown type'})")
    if has_module("PIL"):
        try:
            from PIL import Image
            from io import BytesIO
            with Image.open(BytesIO(data)) as image:
                image.verify()
        except Exception as exc:
            raise ValueError(f"image validation failed: {exc}")
    path = unique_path(f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{extension}")
    with open(path, "wb") as file:
        file.write(data)
    return path


def generate_image(prompt, width=1024, height=1024):
    prompt = prompt.strip()[:1500]
    if not prompt:
        return None, "empty prompt"
    selected = STATE.get("image_model", "standard")
    internal_model = IMAGE_MODEL_MAP.get(selected, "flux")
    models = [internal_model] + (["flux"] if internal_model != "flux" else [])
    errors = []
    for model in models:
        seed = random.randint(1, 999999)
        url = (
            f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
            f"?model={urllib.parse.quote(model)}&width={width}&height={height}"
            f"&nologo=true&seed={seed}"
        )
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "FT-CODEX/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
                content_type = response.headers.get("Content-Type", "")
            path = _save_image_response(data, content_type, "ft_codex_image")
            return path, model
        except Exception as exc:
            errors.append(_sanitize(exc))
    return None, " | ".join(errors) if errors else "Image service unavailable"


def test_providers():
    print(col("\n🧪 Live checks (internet required)", C.BOLD))
    probe = [{"role": "user", "content": "Reply with exactly CODEX_OK"}]
    for name, fn in ENGINES.items():
        sp = Spinner(f"Testing chat: {name}"); sp.start()
        result = _run_timeout(fn, min(ENGINE_TIMEOUT, 25), probe)
        ok = bool(result and str(result).strip())
        sp.stop(ok, f"{name}: {'working' if ok else 'no valid response'}")
    sp = Spinner("Testing image generation"); sp.start()
    path, info = generate_image("simple blue circle on white background", 256, 256)
    sp.stop(bool(path), "Image generated and validated" if path else "No image provider returned an image")
    if path:
        print(col(f"Test image saved: {path}", C.GREEN))
    else:
        print(col(f"Image test: {info}", C.YELLOW))


def safe_name(name, default="output.txt"):
    name = os.path.basename(name.strip().replace("\\", "/"))
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    return name or default


def unique_path(name):
    path = os.path.join(OUT_DIR, safe_name(name))
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(path):
        path = f"{base}_{n}{ext}"
        n += 1
    return path


def strip_fence(text):
    lines = text.strip("\n").split("\n")
    if len(lines) >= 2 and lines[0].lstrip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return text


def save_text_file(name, content):
    path = unique_path(name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(strip_fence(content))
    return path


def read_attachment(path):
    path = os.path.expanduser(path)
    size = os.path.getsize(path)
    if size > MAX_FILE_BYTES:
        raise ValueError(f"file bohat badi hai ({human_size(size)}), limit {human_size(MAX_FILE_BYTES)}")
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()

    if ext == ".pdf":
        reader_cls = None
        if has_module("pypdf"):
            from pypdf import PdfReader as reader_cls
        elif has_module("PyPDF2"):
            from PyPDF2 import PdfReader as reader_cls
        if not reader_cls:
            raise ValueError("PDF support unavailable. Please try again later.")
        text = "\n\n".join((p.extract_text() or "") for p in reader_cls(path).pages)
        if not text.strip():
            raise ValueError("PDF me text nahi mila (scanned ho sakti hai)")
        return name, text

    if ext == ".docx":
        if not has_module("docx"):
            raise ValueError("DOCX support unavailable. Please try again later.")
        import docx
        return name, "\n".join(p.text for p in docx.Document(path).paragraphs)

    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".mp3", ".mp4", ".zip", ".exe"):
        raise ValueError("ye binary/media file hai - sirf text, code, PDF, DOCX supported hain")

    with open(path, "rb") as f:
        raw = f.read()
    if b"\x00" in raw[:4096]:
        raise ValueError("binary file lag rahi hai, text nahi")
    return name, raw.decode("utf-8", errors="replace")


def find_files(token):
    token = os.path.expanduser(token)
    found = []
    for base in ("", OUT_DIR):
        pattern = os.path.join(base, token) if base else token
        hits = glob.glob(pattern) if any(c in token for c in "*?[") else [pattern]
        found = [h for h in hits if os.path.isfile(h)]
        if found:
            break
    return sorted(set(found))


def list_folder():
    rows = []
    for name in sorted(os.listdir(OUT_DIR)):
        p = os.path.join(OUT_DIR, name)
        if os.path.isfile(p) and not name.startswith("."):
            rows.append((name, os.path.getsize(p)))
    return rows


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_memory():
    data = _load_json(MEMORY_FILE, [])
    return [m for m in data if isinstance(m, dict) and m.get("text")] if isinstance(data, list) else []


def save_memory():
    try:
        _save_json(MEMORY_FILE, STATE["memory"])
    except Exception as e:
        print(col(f"   ⚠ memory save fail: {_sanitize(e)}", C.RED))


def add_memory(text, source="user"):
    text = " ".join(text.split())[:MEMORY_ITEM_CHARS]
    if not text:
        return "empty"
    if any(m["text"].lower() == text.lower() for m in STATE["memory"]):
        return "duplicate"
    STATE["memory"].append({"text": text, "source": source,
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
    del STATE["memory"][:-MEMORY_MAX_ITEMS]
    save_memory()
    return "added"


def memory_block():
    if not STATE["memory_on"] or not STATE["memory"]:
        return ""
    facts = "\n".join(f"- {m['text']}" for m in STATE["memory"])
    return ("\n\nLONG-TERM MEMORY (facts the user wants you to remember; use them naturally, "
            "do not recite them unless asked):\n" + facts)


def save_session():
    if not STATE["autosave"]:
        return
    try:
        _save_json(SESSION_FILE, STATE["history"])
    except Exception:
        pass


def load_session():
    data = _load_json(SESSION_FILE, [])
    ok = isinstance(data, list) and all(isinstance(m, dict) and "role" in m and "content" in m for m in data)
    return data if ok else []


def get_key():
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            return {b"H": "UP", b"P": "DOWN", b"K": "LEFT", b"M": "RIGHT"}.get(ch2, "")
        if ch == b"\r": return "ENTER"
        if ch == b"\x03": return "CTRL_C"
        try: return ch.decode(errors="ignore")
        except Exception: return ""
    import tty, termios
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            if sys.stdin.read(1) == "[":
                return {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT"}.get(sys.stdin.read(1), "")
            return ""
        if ch in ("\r", "\n"): return "ENTER"
        if ch == "\x03": return "CTRL_C"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def arrow_menu(title, items, default=0):
    idx = default if 0 <= default < len(items) else 0
    n = len(items)
    if not sys.stdin.isatty():
        print(title)
        for i, it in enumerate(items, 1):
            print(f"  {i}. {it}")
        try:
            return max(0, min(n - 1, int(input("Number: ")) - 1))
        except Exception:
            return idx

    def draw():
        print(f"\r\033[K{col(title, C.CYAN, C.BOLD)}")
        for i, item in enumerate(items):
            prefix = "» " if i == idx else "  "
            style = (C.CYAN + C.BOLD) if i == idx else C.DIM
            print(f"\r\033[K{col(prefix + item, style)}")
        print(f"\r\033[K{col('   ↑↓ / ←→ se move · Enter se select', C.DIM)}")

    draw()
    while True:
        key = get_key()
        if key in ("UP", "LEFT"):
            idx = (idx - 1) % n
            print(f"\033[{n + 2}A", end=""); draw()
        elif key in ("DOWN", "RIGHT"):
            idx = (idx + 1) % n
            print(f"\033[{n + 2}A", end=""); draw()
        elif key == "ENTER":
            return idx
        elif key == "CTRL_C":
            raise KeyboardInterrupt


def read_paste():
    print(col("📋 Paste mode: apna poora text paste karein, phir nayi line par /end likhein "
              "(cancel: /cancel).", C.YELLOW))
    lines = []
    while True:
        try:
            ln = sys.stdin.readline()
        except KeyboardInterrupt:
            return None
        if ln == "":
            break
        stripped = ln.strip()
        if stripped == "/end":
            break
        if stripped == "/cancel":
            return None
        lines.append(ln.rstrip("\r\n"))
    text = "\n".join(lines).strip()
    if text:
        print(col(f"   ✓ {len(text):,} chars ({human_size(len(text.encode()))}) mil gaye", C.DIM))
    return text or None


DEFAULT_SYSTEM = ("You are CODEX, a helpful, accurate AI assistant. Developer: FT. "
                  "Reply in the same language the user writes in.")

FILE_RULES = """

OUTPUT RULES (important):
- When the user asks you to create/write/generate a file (code, text, html, json, csv, etc.),
  output each file EXACTLY in this format, with the complete content and no markdown fences inside:
=====FILE: filename.ext=====
<full file content>
=====END FILE=====
  You may write normal explanation text outside these blocks. One block per file.
- When the user asks you to generate/draw an image, output one line:
=====IMAGE: detailed english image prompt=====
- Attached files from the user appear inside <attached_file name="..."> tags.
- Never use the FILE/IMAGE markers unless the user actually wants a file or image.
- When the user shares a lasting fact or preference about themselves (name, job, skills, likes,
  project details) or says "remember"/"yaad rakho", also output one line per fact:
=====MEMORY: short fact in third person=====
  Do not save temporary things, secrets, passwords or API keys."""

STATE = {
    "mode": "chat",
    "engine": "auto",
    "history": [],
    "pending": [],
    "system": DEFAULT_SYSTEM,
    "size": (1024, 1024),
    "image_model": "standard",
    "memory": [],
    "memory_on": True,
    "autosave": True,
    "new_memories": [],
    "stats": {"messages": 0, "images": 0, "files": 0, "errors": 0},
    "start": datetime.now(),
}

BANNER = f"""
{C.BLUE}{C.BOLD}
   ██████╗ ██████╗ ██████╗ ███████╗██╗  ██╗
  ██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗██╔╝
  ██║     ██║   ██║██║  ██║█████╗   ╚███╔╝
  ██║     ██║   ██║██║  ██║██╔══╝   ██╔██╗
  ╚██████╗╚██████╔╝██████╔╝███████╗██╔╝ ██╗
   ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
{C.RESET}{C.CYAN}
        FT-CODEX  ·  Smart AI Assistant  ·  Free providers
        Developer: FT
{C.RESET}"""


def dev_info():
    print(col("\n👨‍💻 Developer Info", C.BOLD))
    print(f"   {col('Name     :', C.CYAN)} Shehryar Official")
    print(f"   {col('Age      :', C.CYAN)} 16")
    print(f"   {col('Location :', C.CYAN)} Unknown")
    print(f"   {col('Skill    :', C.CYAN)} Web Developer · Vibe Coder")
    print(f"   {col('Team     :', C.CYAN)} FT")
    print(f"   {col('Website  :', C.CYAN)} https://ft-shehryar.pages.dev")


def show_help():
    print(col("\n📖 Commands", C.BOLD))
    rows = [
        ("/help", "commands list"),
        ("/chat", "chat mode"),
        ("/img", "image mode (free)"),
        ("/imagine <prompt>", "kisi bhi mode me image banao"),
        ("/size WxH", "image size (default 1024x1024)"),
        ("/file <filename> (questions)", "file attach karo aur us par sawal poochho"),
        ("/cat <filename>", "text file ka content preview"),
        ("/find <text>", "CODEX folder ki text files me search"),
        ("/files", "attached files dekho"),
        ("/detach [n|name]", "attachment hatao (bina argument = sab)"),
        ("/ls", "CODEX folder ki files dekho"),
        ("/paste", "bada multi-line text paste karo (/end se khatam)"),
        ("/remember <text>", "long-term memory me kuch save karo"),
        ("/memory [on|off|clear]", "memory dekho, on/off ya clear karo"),
        ("/forget <n|all>", "memory se hatao"),
        ("/retry", "last jawab dobara generate karo"),
        ("/new", "nayi chat shuru karo"),
        ("/summary", "current chat ka summary banao"),
        ("/undo", "last sawal-jawab hatao"),
        ("/autosave [on|off]", "chat auto-save (agli baar resume)"),
        ("/engine", "AI engine chuno (auto = fallback chain)"),
        ("/engines", "chat providers aur image models"),
        ("/test", "live AI + image API smoke test"),
        ("/imgmodel <name>", "standard / turbo / realistic / anime"),
        ("/clear", "memory clear"),
        ("/reset", "session reset"),
        ("/history", "conversation dikhao"),
        ("/save <file>", "JSON save"),
        ("/load <file>", "JSON load"),
        ("/export <file>", "text export"),
        ("/sys <text>", "system prompt set"),
        ("/out /pwd", "save folder dikhao"),
        ("/stats", "session stats"),
        ("/about /developer", "info"),
        ("/version /time /date /echo", "misc"),
        ("/exit", "exit"),
    ]
    for cmd, desc in rows:
        print(f"  {col(cmd.ljust(26), C.YELLOW)} – {desc}")
    print(col("\n  Tip: AI se bolo 'ek index.html bana do' - file isi folder me save ho jayegi.", C.DIM))
    print(col("  Tip: terminal me bahut lamba single-line paste kat sakta hai -> /paste ya /file use karein.", C.DIM))
    print(col("  Tip: AI se bolo 'yaad rakho meri age 16 hai' - wo khud memory me save kar lega.", C.DIM))


FILE_RE = re.compile(r"=====FILE:\s*(.+?)\s*=====[ \t]*\r?\n(.*?)\r?\n?=====END FILE=====", re.S)
IMG_RE = re.compile(r"=====IMAGE:\s*(.+?)\s*=====")
MEM_RE = re.compile(r"=====MEMORY:\s*(.+?)\s*=====")


def build_messages():
    kept, total = [], 0
    for m in reversed(STATE["history"]):
        total += len(m["content"])
        if total > HISTORY_CHAR_LIMIT and kept:
            break
        kept.append(m)
    kept.reverse()
    return [{"role": "system", "content": STATE["system"] + memory_block() + FILE_RULES}] + kept


def process_outputs(ans):
    saved_files, saved_images = [], []
    if STATE["memory_on"]:
        for m in MEM_RE.finditer(ans):
            if add_memory(m.group(1), "ai") == "added":
                STATE["new_memories"].append(m.group(1))
    ans = MEM_RE.sub("", ans)
    for m in FILE_RE.finditer(ans):
        try:
            saved_files.append(save_text_file(m.group(1), m.group(2)))
        except Exception as e:
            print(col(f"   ⚠ file save fail ({m.group(1)}): {_sanitize(e)}", C.RED))
    clean = FILE_RE.sub("", ans)
    for m in list(IMG_RE.finditer(clean))[:3]:
        s = Spinner("Image bana raha hoon...")
        s.start()
        path, info = generate_image(m.group(1), *STATE["size"])
        s.stop(bool(path), None)
        if path:
            saved_images.append(path)
        else:
            STATE["stats"]["errors"] += 1
            print(col(f"   ⚠ image fail: {_sanitize(info)}", C.RED))
    clean = IMG_RE.sub("", clean).strip()
    STATE["stats"]["files"] += len(saved_files)
    STATE["stats"]["images"] += len(saved_images)
    return clean, saved_files, saved_images


def send_chat(prompt, raw=False):
    full = prompt
    if STATE["pending"] and not raw:
        blocks = "\n\n".join(f'<attached_file name="{n}">\n{t}\n</attached_file>' for n, t in STATE["pending"])
        full = f"{blocks}\n\n{prompt}"
        STATE["pending"] = []
    STATE["history"].append({"role": "user", "content": full})

    s = Spinner(f"Thinking... ({STATE['engine']})")
    s.start()
    ans, used = get_reply(build_messages(), STATE["engine"])
    s.stop(bool(ans), None)

    if not ans:
        STATE["stats"]["errors"] += 1
        STATE["history"].pop()
        print(col("\n❌ Koi engine jawab nahi de saka. Dobara try karein ya /engine se doosra chuno.", C.RED))
        return

    STATE["history"].append({"role": "assistant", "content": ans})
    STATE["stats"]["messages"] += 1
    save_session()
    STATE["new_memories"] = []
    clean, files, images = process_outputs(ans)

    print(col(f"\n✅ {used} ›", C.GREEN + C.BOLD))
    if clean:
        print(clean)
    for p in files:
        print(col(f"\n💾 File saved  : {p}", C.GREEN))
    for p in images:
        print(col(f"\n🖼  Image saved : {p}", C.GREEN))
    for fact in STATE["new_memories"]:
        print(col(f"\n🧠 Yaad kar liya: {fact}", C.MAGENTA))
    if len(ans) > BIG_REPLY_CHARS:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        p = save_text_file(f"response_{ts}.md", ans)
        print(col(f"\n📦 Bada jawab ({human_size(len(ans.encode()))}) bhi save kiya: {p}", C.YELLOW))


def send_image(prompt):
    s = Spinner("Generating image...")
    s.start()
    path, info = generate_image(prompt, *STATE["size"])
    s.stop(bool(path), None)
    if path:
        STATE["stats"]["images"] += 1
        print(col(f"\n✅ Saved : {path}", C.GREEN))
        print(col(f"   Model : {STATE['image_model']}", C.DIM))
    else:
        STATE["stats"]["errors"] += 1
        print(col("\n❌ Image generation failed. Please try again.", C.RED))


def cmd_file(arg):
    if not arg:
        print("Usage: /file <filename> [sawal]")
        print(col("  Examples: /file app.py kya galti hai?  |  /file a.py b.py compare karo  |  "
                  "/file *.py", C.DIM))
        print(col("  Spaces wali path ko \"quotes\" me likhein. Pehle current folder, phir CODEX folder me "
                  "dhoondta hai.", C.DIM))
        return
    try:
        tokens = shlex.split(arg, posix=(os.name != "nt"))
    except ValueError:
        tokens = arg.split()
    tokens = [t.strip('"\'') if os.name == "nt" else t for t in tokens]
    added = matched = 0
    while tokens:
        paths = find_files(tokens[0])
        if not paths:
            break
        tokens.pop(0)
        matched += len(paths)
        for p in paths:
            try:
                name, text = read_attachment(p)
                if any(n == name and t == text for n, t in STATE["pending"]):
                    continue
                STATE["pending"].append((name, text))
                added += 1
                print(col(f"📎 {name} attach ({len(text):,} chars)", C.GREEN))
            except Exception as e:
                print(col(f"❌ {os.path.basename(p)}: {_sanitize(e)}", C.RED))
    if not matched:
        print(col(f"❌ File nahi mili: {tokens[0] if tokens else arg}  (/ls se folder ki files dekhein)", C.RED))
        return
    if not STATE["pending"]:
        return
    question = " ".join(tokens).strip()
    if question:
        send_chat(question)
    else:
        print(col("   Ab apna sawal likhein - file uske saath jayegi.", C.DIM))


def preview_file(name):
    paths = find_files(name)
    if not paths:
        print(col(f"❌ File nahi mili: {name}", C.RED))
        return
    try:
        filename, content = read_attachment(paths[0])
        print(col(f"\n📄 {filename} · {len(content):,} characters", C.CYAN))
        print(content[:12000])
        if len(content) > 12000:
            print(col(f"\n... preview limited; total {len(content):,} characters", C.DIM))
    except Exception as exc:
        print(col(f"❌ {_sanitize(exc)}", C.RED))


def search_folder(query):
    if not query:
        print("Usage: /find <text>")
        return
    matches = []
    allowed = {".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json",
               ".php", ".xml", ".yml", ".yaml", ".sql", ".csv", ".log", ".ini"}
    for name in os.listdir(OUT_DIR):
        path = os.path.join(OUT_DIR, name)
        if not os.path.isfile(path) or os.path.splitext(name)[1].lower() not in allowed:
            continue
        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                continue
            with open(path, encoding="utf-8", errors="replace") as file:
                for line_no, line in enumerate(file, 1):
                    if query.casefold() in line.casefold():
                        matches.append((name, line_no, line.strip()[:180]))
                        if len(matches) >= 50:
                            break
        except OSError:
            continue
        if len(matches) >= 50:
            break
    if not matches:
        print(col("No matches found in the FT-CODEX folder.", C.YELLOW))
        return
    print(col(f"\n🔎 Found {len(matches)} match(es):", C.CYAN))
    for name, line_no, line in matches:
        print(f"  {name}:{line_no}  {line}")


def handle_command(line):
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit"):
        return "exit"
    elif cmd == "/help": show_help()
    elif cmd == "/chat":
        STATE["mode"] = "chat"; print(col("\n✅ CHAT mode", C.GREEN))
    elif cmd == "/img":
        STATE["mode"] = "image"; print(col("\n✅ IMAGE mode · free", C.GREEN))
    elif cmd == "/imagine":
        if not arg: print("Usage: /imagine <prompt>")
        else: send_image(arg)
    elif cmd == "/size":
        m = re.match(r"^(\d{2,4})\s*[xX*]\s*(\d{2,4})$", arg)
        if not m: print("Usage: /size 1024x1024  (256-2048)")
        else:
            w, h = (max(256, min(2048, int(v))) for v in m.groups())
            STATE["size"] = (w, h); print(col(f"✅ Image size {w}x{h}", C.GREEN))
    elif cmd == "/file": cmd_file(arg)
    elif cmd == "/cat": preview_file(arg) if arg else print("Usage: /cat <filename>")
    elif cmd == "/find": search_folder(arg)
    elif cmd == "/files":
        if not STATE["pending"]: print(col("(koi file attach nahi)", C.DIM))
        for n, t in STATE["pending"]: print(f"  📎 {n} ({len(t):,} chars)")
    elif cmd == "/detach":
        if not arg:
            STATE["pending"].clear(); print(col("🧹 Sab attachments hata diye.", C.YELLOW))
        else:
            before = len(STATE["pending"])
            if arg.isdigit() and 1 <= int(arg) <= before:
                STATE["pending"].pop(int(arg) - 1)
            else:
                STATE["pending"] = [(n, t) for n, t in STATE["pending"] if n.lower() != arg.lower()]
            print(col("🧹 Hata diya." if len(STATE["pending"]) < before else "❌ Aisi attachment nahi mili.",
                      C.YELLOW))
    elif cmd == "/ls":
        rows = list_folder()
        print(col(f"\n📁 {OUT_DIR}", C.CYAN))
        if not rows: print(col("(khali)", C.DIM))
        for name, size in rows: print(f"  {name.ljust(40)} {human_size(size)}")
        print(col("  /file <name> se attach karein.", C.DIM))
    elif cmd == "/remember":
        if not arg: print("Usage: /remember <text>"); return None
        r = add_memory(arg)
        print(col({"added": "🧠 Yaad kar liya.", "duplicate": "ℹ  Ye pehle se yaad hai.",
                   "empty": "❌ Khali text."}[r], C.MAGENTA))
    elif cmd == "/memory":
        a = arg.lower()
        if a == "clear":
            STATE["memory"].clear()
            save_memory()
            print(col("🧹 Long-term memory cleared.", C.YELLOW))
        elif a in ("on", "off"):
            STATE["memory_on"] = (a == "on")
            print(col(f"🧠 Memory {'ON' if STATE['memory_on'] else 'OFF'}", C.GREEN))
        else:
            state = "ON" if STATE["memory_on"] else "OFF"
            print(col(f"\n🧠 Long-term memory [{state}] · {len(STATE['memory'])} items · {MEMORY_FILE}", C.BOLD))
            if not STATE["memory"]: print(col("(khali) /remember <text> se add karein", C.DIM))
            for i, m in enumerate(STATE["memory"], 1):
                tag = "AI" if m.get("source") == "ai" else "me"
                print(f"  {col(str(i).rjust(3), C.YELLOW)}. {m['text']}  {col('[' + tag + ' · ' + m.get('time', '') + ']', C.DIM)}")
    elif cmd == "/forget":
        if not arg: print("Usage: /forget <number> | all"); return None
        if arg.lower() == "all":
            STATE["memory"].clear(); save_memory()
            print(col("🧹 Poori memory saaf.", C.YELLOW))
        elif arg.isdigit() and 1 <= int(arg) <= len(STATE["memory"]):
            gone = STATE["memory"].pop(int(arg) - 1); save_memory()
            print(col(f"🧹 Bhula diya: {gone['text']}", C.YELLOW))
        else:
            print(col("❌ Galat number. /memory se list dekhein.", C.RED))
    elif cmd == "/autosave":
        a = arg.lower()
        if a in ("on", "off"):
            STATE["autosave"] = (a == "on")
            if STATE["autosave"]: save_session()
        print(col(f"💾 Chat auto-save {'ON' if STATE['autosave'] else 'OFF'} · {SESSION_FILE}", C.GREEN))
    elif cmd == "/undo":
        if STATE["history"] and STATE["history"][-1]["role"] == "assistant":
            STATE["history"].pop()
        if STATE["history"] and STATE["history"][-1]["role"] == "user":
            STATE["history"].pop(); save_session()
            print(col("↩ Last sawal-jawab hata diya.", C.YELLOW))
        else:
            print(col("(undo karne ko kuch nahi)", C.DIM))
    elif cmd == "/new":
        STATE["history"].clear()
        STATE["pending"].clear()
        save_session()
        print(col("🆕 New chat started. Long-term memory is preserved.", C.GREEN))
    elif cmd == "/summary":
        if not STATE["history"]:
            print(col("Chat history is empty.", C.DIM))
        else:
            send_chat("Please summarize our conversation so far. Include key decisions, requirements, and unfinished tasks.")
    elif cmd == "/retry":
        while STATE["history"] and STATE["history"][-1]["role"] == "assistant":
            STATE["history"].pop()
        if not STATE["history"] or STATE["history"][-1]["role"] != "user":
            print(col("(retry karne ko kuch nahi)", C.DIM)); return None
        last = STATE["history"].pop()["content"]
        send_chat(last, raw=True)
    elif cmd == "/paste":
        text = read_paste()
        if text:
            if STATE["mode"] == "chat": send_chat(text)
            else: send_image(text)
        else:
            print(col("(cancel)", C.DIM))
    elif cmd == "/engine":
        d = ENGINE_CHOICES.index(STATE["engine"])
        STATE["engine"] = ENGINE_CHOICES[arrow_menu("Engine select karein:", ENGINE_CHOICES, d)]
        print(col(f"\n✅ Engine: {STATE['engine']}", C.GREEN))
    elif cmd == "/test":
        test_providers()
    elif cmd == "/imgmodel":
        if arg not in IMAGE_MODELS: print("Usage: /imgmodel " + " | ".join(IMAGE_MODELS))
        else:
            STATE["image_model"] = arg
            print(col(f"Image model: {arg}", C.GREEN))
    elif cmd in ("/engines", "/models"):
        print(col("\n🤖 No-key chat providers:", C.BOLD))
        for n in ENGINE_CHOICES:
            mark = "»" if n == STATE["engine"] else " "
            print(f"  {mark} {n}")
        print(col("\n🎨 Image models:", C.BOLD))
        for model in IMAGE_MODELS:
            print("  " + ("» " if model == STATE["image_model"] else "  ") + model)
    elif cmd == "/clear":
        STATE["history"].clear(); save_session()
        print(col("🧹 Chat history clear (long-term memory safe hai).", C.YELLOW))
    elif cmd == "/reset":
        STATE["history"].clear(); STATE["pending"].clear(); save_session()
        STATE["stats"] = {"messages": 0, "images": 0, "files": 0, "errors": 0}
        print(col("🔄 Session reset (long-term memory safe hai).", C.YELLOW))
    elif cmd == "/history":
        if not STATE["history"]: print(col("(empty)", C.DIM))
        for m in STATE["history"]:
            tag = col(m["role"].upper(), C.MAGENTA if m["role"] == "user" else C.CYAN)
            c = m["content"]
            if len(c) > 800: c = c[:800] + f"\n... [{len(c):,} chars total]"
            print(f"\n{tag}:\n{c}")
    elif cmd == "/save":
        if not arg: print("Usage: /save <file>"); return None
        with open(os.path.join(OUT_DIR, safe_name(arg, "chat.json")), "w", encoding="utf-8") as f:
            json.dump(STATE["history"], f, ensure_ascii=False, indent=2)
        print(col(f"💾 Saved → {os.path.join(OUT_DIR, safe_name(arg, 'chat.json'))}", C.GREEN))
    elif cmd == "/load":
        if not arg: print("Usage: /load <file>"); return None
        p = arg if os.path.exists(arg) else os.path.join(OUT_DIR, arg)
        if not os.path.exists(p): print(col(f"❌ File nahi mili: {arg}", C.RED)); return None
        try:
            with open(p, encoding="utf-8") as f: data = json.load(f)
            assert isinstance(data, list) and all("role" in m and "content" in m for m in data)
            STATE["history"] = data
            print(col(f"📂 Loaded ← {p}", C.GREEN))
        except Exception:
            print(col("❌ Ye valid chat JSON nahi hai.", C.RED))
    elif cmd == "/export":
        if not arg: print("Usage: /export <file>"); return None
        p = unique_path(arg)
        with open(p, "w", encoding="utf-8") as f:
            for m in STATE["history"]:
                f.write(f"{m['role'].upper()}: {m['content']}\n\n")
        print(col(f"📄 Exported → {p}", C.GREEN))
    elif cmd == "/sys":
        if not arg: print("Usage: /sys <text>"); return None
        STATE["system"] = arg; print(col("✅ System prompt updated.", C.GREEN))
    elif cmd in ("/out", "/pwd"):
        print(col(f"\n📁 Files/images yaha save hote hain:\n   {OUT_DIR}", C.CYAN))
    elif cmd in ("/stats", "/status"):
        s = STATE["stats"]; up = datetime.now() - STATE["start"]
        print(col("\n📊 Stats", C.BOLD))
        print(f"   Mode        : {STATE['mode']}")
        print(f"   Engine      : {STATE['engine']}")
        print(f"   Image model : {STATE['image_model']} ({STATE['size'][0]}x{STATE['size'][1]})")
        print(f"   Memory      : {len(STATE['memory'])} items ({'ON' if STATE['memory_on'] else 'OFF'})")
        print(f"   Messages    : {s['messages']}")
        print(f"   Images      : {s['images']}")
        print(f"   Files made  : {s['files']}")
        print(f"   Errors      : {s['errors']}")
        print(f"   Uptime      : {str(up).split('.')[0]}")
    elif cmd == "/about":
        print(col("\nℹ  FT-CODEX Smart AI Assistant (free only)", C.BOLD))
        print(f"   Version   : {VERSION}")
        print("   Developer : Shehryar Official")
        print("   Team      : FT")
    elif cmd == "/developer": dev_info()
    elif cmd == "/version": print(col(f"\n🏷  Version {VERSION}", C.GREEN))
    elif cmd == "/time": print(col(f"\n🕒 {datetime.now().strftime('%H:%M:%S')}", C.CYAN))
    elif cmd == "/date": print(col(f"\n📅 {datetime.now().strftime('%Y-%m-%d')}", C.CYAN))
    elif cmd == "/echo": print(arg)
    else: print(col(f"❓ Unknown command: {cmd}  (/help dekhein)", C.RED))
    return None


def main():
    clear_screen()
    print(BANNER)
    auto_install()
    clear_screen()
    print(BANNER)

    idx = arrow_menu("Mode select karein:", ["AI Chat", "Image Generation (free)"], 0)
    STATE["mode"] = "chat" if idx == 0 else "image"
    print(col(f"\n✅ {STATE['mode'].upper()} mode · /help se commands dekhein", C.GREEN))
    print(col(f"📁 Save folder: {OUT_DIR}", C.DIM))

    STATE["memory"] = load_memory()
    if STATE["memory"]:
        print(col(f"🧠 Memory: {len(STATE['memory'])} cheezein yaad hain (/memory)", C.MAGENTA))
    prev = load_session()
    if prev:
        n = len(prev)
        if arrow_menu(f"Pichli chat mili ({n} messages). Resume karein?", ["Haan, resume", "Nahi, nayi chat"], 0) == 0:
            STATE["history"] = prev
            print(col("↩ Pichli chat wapas load ho gayi.", C.GREEN))
        else:
            save_session()

    while True:
        tag = STATE["engine"] if STATE["mode"] == "chat" else STATE["image_model"]
        att = f" 📎{len(STATE['pending'])}" if STATE["pending"] else ""
        prompt_str = col(f"\n[{STATE['mode'].upper()} · {tag}{att}] You › ", C.BLUE + C.BOLD)
        try:
            line = input(prompt_str).strip()
        except (EOFError, KeyboardInterrupt):
            print(col("\nBye! 👋", C.YELLOW)); break

        if not line:
            continue
        if line.startswith("/"):
            try:
                if handle_command(line) == "exit":
                    print(col("Bye! 👋", C.YELLOW)); break
            except KeyboardInterrupt:
                print(col("\n(cancelled)", C.DIM))
            except Exception as e:
                STATE["stats"]["errors"] += 1
                print(col(f"❌ Command error: {_sanitize(e)}", C.RED))
            continue

        try:
            if STATE["mode"] == "chat": send_chat(line)
            else: send_image(line)
        except KeyboardInterrupt:
            show_cursor(); print(col("\n(cancelled)", C.DIM))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        show_cursor()
        print(col("\nBye! 👋", C.YELLOW))