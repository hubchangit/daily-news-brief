# 🚋 Tram Girl (電車少女) - Automated AI Daily Podcast

![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/YOUR_USERNAME/YOUR_REPO_NAME/daily_news.yml?label=Daily%20Brief)
![Podcast Language](https://img.shields.io/badge/Language-Cantonese%20(HK)-red)
![Cost](https://img.shields.io/badge/Cost-%240%20(Free)-green)

**Tram Girl** is a fully automated, serverless podcast generator that runs entirely on GitHub Actions. Every morning at 6:00 AM (HKT), it wakes up, reads the news, checks the weather, writes a script, speaks it out, mixes it with Lo-Fi music, and publishes a new episode to your podcast feed.
I created Tram Girl since I lack of a channel to listen to neutral Cantonese news (without self-censorship nor political stance). Hope you can also enjoy the podcast service.

## 🎧 Listen
https://hubchangit.github.io/daily-news-brief/feed.xml
**RSS Feed URL:**   https://hubchangit.github.io/daily-news-brief/feed.xml
*Add this URL to Apple Podcasts, Pocket Casts, or any RSS player.*

---

## ✨ Features

* **🌍 Multi-Source Intelligence:** Aggregates news from **The Guardian, BBC (World)** and **SCMP, RTHK (Local HK)**.
* **🌦️ Real-Time Weather:** Pulls the official **Hong Kong Observatory** forecast.
* **🧠 AI Scriptwriting:** Uses **Qwen 2.5-72B** (via Hugging Face) to write a natural, colloquially Cantonese script with a "Daily English Corner" segment.
* **🗣️ Natural TTS:** Uses Microsoft Edge's **"HiuGaai"** Neural voice (optimized at +25% speed for natural flow).
* **🎵 Audio Engineering:** Automatically downloads royalty-free Lo-Fi music, lowers the volume, and mixes it behind the voice using **FFmpeg**.
* **🧹 Auto-Janitor:** Automatically manages storage by deleting episodes older than 3 days to keep the repository light.
* **⏰ Time-Zone Aware:** Correctly handles the "Server Time vs. Hong Kong Time" difference to ensure dates are always accurate.

---

## 🛠️ How It Works (The Pipeline)

1.  **Trigger:** GitHub Actions wakes up at **22:00 UTC** (06:00 HKT).
2.  **Environment:** Installs `Python`, `FFmpeg` (for audio mixing), and `wget`.
3.  **Fetch:** `wget` downloads the background music (`bgm.ogg`) from Wikimedia (bypassing bot blocks).
4.  **Execute:** `main.py` runs:
    * Fetches RSS feeds & Weather XML.
    * Sends data to Hugging Face Inference API.
    * Generates raw voice audio.
    * Mixes voice + music into a final MP3.
    * Updates `feed.xml`.
5.  **Publish:** The workflow pushes the new MP3 and XML back to the repository. GitHub Pages serves the feed to listeners.

---

## 🚀 Setup Guide (Zero Cost)

### 1. Fork this Repository
Click the **Fork** button at the top right of this page to create your own copy.

### 2. Get an AI Key
1.  Go to [Hugging Face](https://huggingface.co/).
2.  Sign up (Free).
3.  Go to **Settings** -> **Access Tokens** -> **Create New Token** (Read permissions).
4.  Copy the token (starts with `hf_...`).

### 3. Add Secrets to GitHub
1.  In your new repo, go to **Settings** -> **Secrets and variables** -> **Actions**.
2.  Click **New repository secret**.
3.  **Name:** `HF_TOKEN`
4.  **Value:** (Paste your Hugging Face token).

### 4. Enable GitHub Pages
1.  Go to **Settings** -> **Pages**.
2.  Under **Source**, select `main` (or `master`) branch.
3.  Click **Save**.
4.  Copy the URL displayed at the top (e.g., `https://username.github.io/repo/`).

### 5. First Run
1.  Go to the **Actions** tab.
2.  Select **Daily News Generator** on the left.
3.  Click **Run workflow**.
4.  Wait ~2 minutes. Once green, your podcast is live!

---

## ⚙️ Customization

### Changing News Sources
Edit `FEEDS` in `main.py`:
```python
FEEDS = [
    "[https://your-new-rss-feed.com/rss](https://your-new-rss-feed.com/rss)",
    ...
]
