# 🎙️ Hong Kong Morning News Podcast (AI Automated)

An automated daily podcast generator that creates a conversational news briefing in Hong Kong Cantonese.

**RSS Feed URL:**   https://hubchangit.github.io/daily-news-brief/feed.xml

*Add this URL to Apple Podcasts, Pocket Casts, or any RSS player.*

## ✨ Key Features

### 🧠 Dual AI "Brains" (Zero Downtime)
This system uses a robust fallback mechanism to ensure the podcast is generated every single day, even if one service goes down.
1.  **Primary Brain:** **Google Gemini (2.5 Flash / 1.5 Pro)** - Fast, high-quality script generation.
2.  **Safety Net:** **Hugging Face (Qwen 2.5-72B)** - If Google fails (404/Quota), the system automatically switches to the open-source Qwen model via Hugging Face Inference.
3.  **Transparency:** The host (`電車少女`) explicitly announces at the end of the episode which AI powered that day's script.

### 🎭 Dynamic Characters
* **Tram Girl (電車少女):** The energetic main host. Uses authentic HK slang.
* **Dekisugi (出木杉):** The calm, analytical co-host.
* **Voices:** Powered by Microsoft Edge TTS (`zh-HK-HiuGaaiNeural` & `zh-HK-WanLungNeural`).

### 🧹 The "Janitor" (Auto-Maintenance)
* **Storage Saver:** Automatically detects and deletes MP3 files from previous days.
* **Cleanup:** Removes temporary audio fragments (`temp_line_*.mp3`) after mixing is complete.
* **Result:** Keeps your GitHub repository clean and prevents storage bloat.

### 📝 Content Segments
1.  **Weather Report:** Real-time data from HK Observatory.
2.  **HK News Deep Dive:** Analysis of local headlines.
3.  **Global Snapshots:** BBC/Guardian headlines.
4.  **📚 English Corner:** A dedicated segment teaching one useful English idiom per day, explained in Cantonese.

---

## 🛠️ Setup & Configuration

### 1. Requirements
The project requires Python 3.10+ and the following libraries (see `requirements.txt`):
* `feedparser` (News fetching)
* `edge-tts` (Voice synthesis)
* `podgen` (RSS feed generation)
* `pydub` (Audio mixing)
* `google-generativeai` (Primary AI)
* `huggingface_hub` (Backup AI)

### 2. Environment Variables (Secrets)
To run this in GitHub Actions, set these in **Settings > Secrets and variables > Actions**:

| Secret Name | Description | Required? |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | Your Google AI Studio API Key. | **Yes** (Primary) |
| `HF_TOKEN` | Hugging Face Access Token (Read). | **Yes** (Backup) |

### 3. How It Works (Workflow)
1.  **Fetch:** The script pulls RSS feeds from SCMP, RTHK, and BBC.
2.  **Write:** It constructs a prompt for the AI to write a dialogue script, enforcing strict formatting (`Name: Line`).
3.  **Synthesize:** It iterates through the script line-by-line, generating audio for the correct character.
4.  **Mix:** Background music (`bgm.mp3`) is looped and mixed under the dialogue.
5.  **Publish:** The `feed.xml` is updated, and the new MP3 is committed to the repository.

---

## ⚠️ Credits & Licenses
* **News Sources:** Content derived from publicly available RSS feeds (RTHK, SCMP, BBC, Guardian).
* **AI Models:**
    * Google Gemini 1.5/2.5
    * Qwen 2.5-72B (via Hugging Face)
* **Audio:** TTS provided by Microsoft Edge Cloud.

---
*Automated by GitHub Actions*
