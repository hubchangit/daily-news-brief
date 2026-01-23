import feedparser
import os
import asyncio
import edge_tts
import re
import glob
import requests
import google.generativeai as genai
from datetime import datetime, timedelta, timezone
from podgen import Podcast, Episode, Media, Person, Category
from pydub import AudioSegment
from huggingface_hub import InferenceClient

# 1. SETUP
# -----------------------------
try:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
except: pass

HKT = timezone(timedelta(hours=8))

# VOICES (The Duo)
VOICE_FEMALE = "zh-HK-HiuGaaiNeural" # Tram Girl
VOICE_MALE = "zh-HK-WanLungNeural"   # Dekisugi

# NEWS SOURCES
FEED_TRENDS = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=HK"
FEEDS_HK = [
    "https://www.scmp.com/rss/2/feed",
    "https://rss.stheadline.com/rss/realtime/hk.xml",
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"
]
FEEDS_GLOBAL = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.theguardian.com/world/rss"
]
FEEDS_TECH = ["https://www.theverge.com/rss/index.xml"]

WEATHER_URL = "https://rss.weather.gov.hk/rss/LocalWeatherForecast_uc.xml"

# CUSTOM BGM URL (From your repo)
REPO_BGM_URL = "https://github.com/hubchangit/daily-news-brief/raw/main/bgm.mp3"

# 2. AUDIO ENGINE
# -----------------------------
async def generate_line(text, voice, filename):
    # Both voices tuned to 1.2x speed (+20%)
    if voice == VOICE_FEMALE:
        rate = "+20%" 
        pitch = "+2Hz"
    else:
        rate = "+20%" # Tuned up for WanLung too
        pitch = "+0Hz"
        
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(filename)

async def generate_dialogue_audio(script_text, output_file):
    print("Generating Dialogue Audio...")
    
    # 1. Cleaning: Remove bolding and markdown
    clean_text = re.sub(r'\*\*|##', '', script_text)
    lines = clean_text.split("|")
    
    combined_audio = AudioSegment.empty()
    temp_files = []
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue
        
        # 2. Detect Speaker & STRIP NAMES
        # We use regex to remove "Name:" or "Name：" from the start of the line
        if "出木杉" in line or "Dekisugi" in line:
            voice = VOICE_MALE
            # Remove the name label
            text = re.sub(r'^(出木杉|Dekisugi)[:：]?', '', line).strip()
        elif "電車少女" in line or "Tram Girl" in line:
            voice = VOICE_FEMALE
            # Remove the name label
            text = re.sub(r'^(電車少女|Tram Girl)[:：]?', '', line).strip()
        else:
            voice = VOICE_MALE if len(line) > 30 else VOICE_FEMALE
            text = line
            
        # 3. Final cleanup of instructions (e.g. "(laugh)")
        text = re.sub(r'\(.*?\)', '', text).strip()
        
        # If text is empty after cleaning, skip it
        if len(text) < 1: continue

        temp_filename = f"temp_line_{i}.mp3"
        try:
            print(f"Speaking ({voice}): {text[:15]}...")
            await generate_line(text, voice, temp_filename)
            
            if os.path.exists(temp_filename):
                segment = AudioSegment.from_mp3(temp_filename)
                combined_audio += segment
                
                # Dynamic Pausing
                pause_ms = 450 if len(segment) > 2500 else 250
                combined_audio += AudioSegment.silent(duration=pause_ms)
                
                temp_files.append(temp_filename)
        except Exception as e:
            print(f"Skipping line: {e}")
            continue

    if len(temp_files) == 0: raise Exception("Audio generation failed.")
    combined_audio.export(output_file, format="mp3")
    
    for f in temp_files:
        try: os.remove(f)
        except: pass

def ensure_bgm():
    if os.path.exists("bgm.mp3"): return True
    print("Downloading BGM...")
    
    # Try User Repo First
    try:
        print(f"Attempting custom BGM from: {REPO_BGM_URL}")
        r = requests.get(REPO_BGM_URL)
        if r.status_code == 200:
            with open("bgm.mp3", "wb") as f:
                f.write(r.content)
            return True
    except:
        print("Custom BGM not found. Trying fallback...")

    # Fallback to Kevin MacLeod
    try:
        url = "https://upload.wikimedia.org/wikipedia/commons/5/5b/Kevin_MacLeod_-_Local_Forecast_-_Elevator.ogg"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        with open("bgm.ogg", "wb") as f:
            f.write(r.content)
        song = AudioSegment.from_ogg("bgm.ogg")[:45000] # 45 sec loop
        song.export("bgm.mp3", format="mp3")
        os.remove("bgm.ogg")
        return True
    except: return False

def mix_music(voice_file, output_file):
    print("Mixing music...")
    if not ensure_bgm():
        if os.path.exists(output_file): os.remove(output_file)
        os.rename(voice_file, output_file)
        return

    try:
        voice = AudioSegment.from_mp3(voice_file)
        bgm = AudioSegment.from_mp3("bgm.mp3") 
        
        # Volume: 30% softer than before (-18dB -> -25dB)
        bgm = bgm - 25
        
        loop_count = len(voice) // len(bgm) + 2
        bgm_looped = bgm * loop_count
        final_bgm = bgm_looped[:len(voice) + 5000].fade_out(4000)
        
        final_mix = final_bgm.overlay(voice, position=1000)
        final_mix.export(output_file, format="mp3")
        if os.path.exists(voice_file): os.remove(voice_file)
    except:
        if os.path.exists(output_file): os.remove(output_file)
        os.rename(voice_file, output_file)

# 3. JANITOR
# -----------------------------
def run_janitor():
    now_hk = datetime.now(HKT)
    todays = f"brief_{now_hk.strftime('%Y%m%d')}.mp3"
    for f in glob.glob("brief_*.mp3"):
        if f != todays:
            try: os.remove(f)
            except: pass
    for p in ["temp_*.mp3", "dialogue_raw.mp3", "bgm.ogg"]:
        for f in glob.glob(p):
            try: os.remove(f)
            except: pass

# 4. BRAIN
# -----------------------------
def get_weather():
    try:
        f = feedparser.parse(WEATHER_URL)
        return f.entries[0].description.replace('<br/>', ' ')[:300] if f.entries else "N/A"
    except: return "N/A"

def get_trends():
    try:
        f = feedparser.parse(FEED_TRENDS)
        return ", ".join([t.title for t in f.entries[:5]])
    except: return "No Trends"

def get_feeds(urls, limit=6):
    content = ""
    count = 0
    for url in urls:
        if count >= limit: break 
        try:
            f = feedparser.parse(url)
            for item in f.entries:
                if count >= limit: break
                desc = re.sub('<[^<]+?>', '', getattr(item, 'summary', ''))[:120]
                content += f"- {item.title} ({desc})\n"
                count += 1
        except: pass
    return content

def generate_script_robust(prompt):
    models = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-pro"]
    for m in models:
        try:
            print(f"🤖 Attempting {m}...")
            model = genai.GenerativeModel(m)
            response = model.generate_content(prompt)
            return response.text.replace("\n", " ")
        except Exception as e:
            print(f"⚠️ {m} Failed: {e}")
            continue

    try:
        print("🚨 Using HuggingFace Backup...")
        client = InferenceClient(api_key=os.environ["HF_TOKEN"])
        msgs = [{"role": "user", "content": prompt}]
        res = client.chat_completion(model="Qwen/Qwen2.5-72B-Instruct", messages=msgs, max_tokens=2500)
        return res.choices[0].message.content.replace("\n", " ")
    except:
        return "出木杉: 系統故障。 | 電車少女: 聽日再見！"

def write_script(hk, gl, tech, we, tr):
    prompt = f"""
    Write a podcast script for "Tram Girl" (電車少女) and "Dekisugi" (出木杉).
    
    **Format Requirements:**
    - Use '|' to separate every single line. 
    - Structure: "Character: Text | Character: Text".
    - Language: **Authentic Hong Kong Cantonese Colloquialism (廣東話口語)**.
    - Tone: Lively banter. Girl is curious/energetic, Boy is smart/calm.

    **Script Sections (Follow Strictly):**
    
    1. **Intro:** Quick energetic hello.
    2. **Weather:** Brief update ({we}).
    3. **HK News (Select 3 Stories):**
       - Discuss the Top Trend first ({tr}).
       - Then cover 2 other headlines from: {hk}
       - Format: Boy explains the news, Girl reacts with slang.
    4. **Global News (Select 3 Stories):**
       - Pick 3 major stories from: {gl}
       - Quick fire discussion.
    5. **Innovation & Ideas (Tech Segment):**
       - Boy introduces ONE interesting new tech or idea from: {tech}
       - Girl asks "Does it really work?" or makes a joke.
    6. **Outro:** "See you tomorrow!"
    
    **Important:** ensure the total script covers 3 HK stories and 3 Global stories distinctively.
    """
    return generate_script_robust(prompt)

def update_rss(audio_file, script):
    repo = os.environ.get("GITHUB_REPOSITORY", "local/test")
    base_url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}"
    
    p = Podcast(
        name="HK Morning Brief",
        description="Daily News: HK, Global & Tech.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("AI Team", "news@ex.com")],
        owner=Person("AI Team", "news@ex.com"),
        category=Category("News"),
    )
    
    now = datetime.now(HKT)
    p.add_episode(Episode(
        title=f"早晨新聞: {now.strftime('%Y-%m-%d')}",
        media=Media(f"{base_url}/{audio_file}", 9000000, type="audio/mpeg"),
        summary=script.replace("|", "\n\n")[:600],
        publication_date=now,
    ))
    p.rss_file('feed.xml')

# 5. MAIN
if __name__ == "__main__":
    run_janitor()
    
    now_str = datetime.now(HKT).strftime('%Y%m%d')
    final_mp3 = f"brief_{now_str}.mp3"
    
    print("Fetching feeds...")
    hk = get_feeds(FEEDS_HK, limit=8)
    gl = get_feeds(FEEDS_GLOBAL, limit=8)
    te = get_feeds(FEEDS_TECH, limit=5)
    we = get_weather()
    tr = get_trends()
    
    print("Writing script...")
    script = write_script(hk, gl, te, we, tr)
    
    try:
        asyncio.run(generate_dialogue_audio(script, "dialogue_raw.mp3"))
        mix_music("dialogue_raw.mp3", final_mp3)
        update_rss(final_mp3, script)
        print("Done!")
    except Exception as e:
        print(f"ERROR: {e}")
        exit(1)
