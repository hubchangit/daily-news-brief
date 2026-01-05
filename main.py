import feedparser
import os
import asyncio
import edge_tts
import re
import glob
from datetime import datetime, timedelta, timezone
from podgen import Podcast, Episode, Media, Person, Category
from huggingface_hub import InferenceClient

# 1. SETUP
# -----------------------------
REPO_ID = "Qwen/Qwen2.5-72B-Instruct" 
HF_TOKEN = os.environ.get("HF_TOKEN")

# DEFINING HONG KONG TIME (UTC+8)
HKT = timezone(timedelta(hours=8))

FEEDS = [
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",      # HK News
    "https://www.scmp.com/rss/2/feed",                             # HK English
    "https://feeds.bbci.co.uk/news/world/rss.xml",                 # BBC
    "https://www.theguardian.com/world/rss"                        # Guardian
]
WEATHER_URL = "https://rss.weather.gov.hk/rss/LocalWeatherForecast_uc.xml"

# 2. JANITOR: DELETE OLD FILES
# -----------------------------
def cleanup_old_files():
    # Find all mp3 files starting with "brief_"
    files = sorted(glob.glob("brief_*.mp3"))
    
    # If we have more than 3 files, delete the oldest ones
    if len(files) > 3:
        for f in files[:-3]: # Keep the last 3, delete the rest
            try:
                os.remove(f)
                print(f"cleaned up old episode: {f}")
            except Exception as e:
                print(f"Could not delete {f}: {e}")

# 3. FETCH DATA
# -----------------------------
def get_weather():
    try:
        feed = feedparser.parse(WEATHER_URL)
        if feed.entries:
            raw = feed.entries[0].description
            return raw.replace('<br/>', ' ').replace('\n', ' ')[:300]
    except:
        return "Weather unavailable."

def get_news():
    full_text = ""
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for item in feed.entries[:3]:
                clean_desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:250]
                tag = "HK News" if "scmp" in url or "rthk" in url else "Global News"
                full_text += f"[{tag}] {item.title}: {clean_desc}\n"
        except Exception as e:
            print(f"Error {url}: {e}")
    return full_text

# 4. SCRIPT & AUDIO
# -----------------------------
def clean_script_for_speech(text):
    text = re.sub(r'[*#_`~]', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    return re.sub(r'\n+', '\n', text).strip()

def get_natural_date():
    # Use HK Time for the spoken date
    now = datetime.now(HKT)
    return f"{now.month}月{now.day}日"

def write_script(raw_news, weather):
    client = InferenceClient(token=HF_TOKEN)
    date_speak = get_natural_date()
    
    prompt = f"""
    You are "Tram Girl" (電車少女). Write a 5-7 minute news script in Cantonese.
    
    Current Date: {date_speak}
    Weather: {weather}
    
    Rules:
    1. NO MARKDOWN. Plain text only.
    2. Translate ALL English news to Cantonese.
    3. Tone: Casual, friendly deep-dive.
    4. Structure:
       - Intro: "哈囉大家好，今日係 {date_speak}..."
       - Weather Summary.
       - HK News Deep Dive.
       - Global News Deep Dive.
       - Outro.

    News:
    {raw_news}
    """
    try:
        response = client.chat_completion(
            model=REPO_ID, 
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3500, temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Error: {e}")
        return "Error generating script."

async def generate_audio(text, filename):
    clean = clean_script_for_speech(text)
    communicate = edge_tts.Communicate(clean, "zh-HK-HiuGaaiNeural", rate="+50%")
    await communicate.save(filename)

# 5. RSS UPDATE
# -----------------------------
def update_rss(audio_filename, episode_text):
    repo_name = os.environ.get("GITHUB_REPOSITORY", "local/test")
    base_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}"

    p = Podcast(
        name="電車少女 (Tram Girl)",
        description="Daily HK & Global news deep dive.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Tram Girl", "news@example.com")],
        owner=Person("Tram Girl", "news@example.com"),
        category=Category("News", "Daily News"),
    )
    
    # Use HK Time for publication date
    now_hk = datetime.now(HKT)
    
    p.add_episode(Episode(
        title=f"電車日記: {now_hk.strftime('%Y-%m-%d')}",
        media=Media(f"{base_url}/{audio_filename}", 9000000, type="audio/mpeg"),
        summary=episode_text[:150] + "...",
        publication_date=now_hk, # Critical: Sets pub date to HK time
    ))
    
    p.rss_file('feed.xml')

# MAIN
if __name__ == "__main__":
    # 1. Cleanup Old Files First
    cleanup_old_files()

    # 2. Generate New Filename using HK TIME
    now_hk = datetime.now(HKT)
    date_str = now_hk.strftime('%Y%m%d') # e.g., 20260105
    mp3_filename = f"brief_{date_str}.mp3"
    
    print(f"Today is (HKT): {date_str}")
    
    print("Fetching content...")
    weather = get_weather()
    news = get_news()
    
    print("Writing script...")
    script = write_script(news, weather)
    
    print(f"Generating audio: {mp3_filename}...")
    asyncio.run(generate_audio(script, mp3_filename))
    
    print("Updating RSS...")
    update_rss(mp3_filename, script)
    print("Done!")
