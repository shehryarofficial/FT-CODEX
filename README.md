<div align="center">

<img src="https://ft-team.pages.dev/ft-codex-preview/" alt="FT-CODEX Preview" width="100%" />

# 🤖 FT-CODEX

### Simple · Free · No API Key · Built for Termux

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Termux%20%7C%20Linux%20%7C%20Windows-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)
![Version](https://img.shields.io/badge/version-1.0.0-orange)
![API Key](https://img.shields.io/badge/API%20Key-Not%20Required-success)
![Cost](https://img.shields.io/badge/Cost-100%25%20Free-brightgreen)

[![Website](https://img.shields.io/badge/Website-ft--shehryar.pages.dev-blueviolet?logo=googlechrome&logoColor=white)](https://ft-shehryar.pages.dev)
[![GitHub](https://img.shields.io/badge/GitHub-shehryarofficial-black?logo=github&logoColor=white)](https://github.com/shehryarofficial)

> **A simple, free AI chatbot built for Termux. No API keys, no setup headaches, no bills. Just run and chat.**

**Made By [Shehryar Official](https://ft-shehryar.pages.dev) · FT TEAM**

</div>

---

## 💡 What Is This?

**FT-CODEX** is a lightweight, terminal-based AI assistant made for **Termux** on Android and any system that runs Python. It's designed for people who just want AI to work — without API keys, without confusing setup, and without paying monthly bills.

This is **not** a "real Codex," not an OpenAI product, and not a paid enterprise AI. It's a simple, honest, low-resource chatbot that does a few things well.

---

## 📸 Demo

<div align="center">
<img src="https://ft-team.pages.dev/ft-codex-preview/" alt="FT-CODEX Demo" width="100%" />
<br>
<i>FT-CODEX running on Termux — chat, image generation, and file saving in one terminal.</i>
</div>

---

## ✨ Features

- 💬 **AI Chat:** Talk to an AI directly in your terminal.
- 🖼 **Image Generation:** Generate images from text (4 styles: standard, turbo, realistic, anime).
- 💾 **File Saving:** Ask AI to create files (HTML, Python, JSON) and they save instantly.
- 🧠 **Long-Term Memory:** Tell it "remember my name is Ali" — it saves facts across sessions.
- 📄 **File Attach:** Attach text, PDF, or DOCX files and ask AI questions about them.
- 🔁 **Auto Resume:** Close Termux — your chat is still there next time.
- 🎨 **Colored UI:** Arrow-key menus and spinner animations.

---

## ⚙️ System Requirements

> ⚠️ **Important:** FT-CODEX auto-installs Python packages (like `g4f`, `Pillow`) on first run, but **system-level packages must be installed manually first**.

### 📲 Termux (Android) — System Packages
```bash
pkg update && pkg upgrade -y
pkg install python git rust binutils build-essential clang make -y
pkg install libjpeg-turbo libpng openssl libffi libxml2 libxslt -y
