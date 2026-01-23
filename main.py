import feedparser
import os
import asyncio
import edge_tts
import re
import glob
import json
import requests
import random
import google.generativeai as genai
from datetime import datetime, timedelta, timezone
from podgen import Podcast, Episode, Media, Person, Category
from pydub import AudioSegment

# 1. CONFIGURATION
# -----------------------------
try:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
except: pass

HKT = timezone(timedelta(hours=8))
GENERATION_MODEL = "gemini-1.5-flash" # Fast, cost-effective, capable of JSON

# VOICES
VOICE_GIRL = "zh-HK-HiuGaaiNeural" 
VOICE_BOY = "zh-HK-WanLungNeural"   

# ASSETS (We download these automatically)
ASSETS = {
    "bgm": "https://upload.wikimedia.org/wikipedia/commons/5/5b/Kevin_MacLeod_-_Local_Forecast_-_Elevator.ogg",
    "sfx_intro": "https://upload.wikimedia.org/wikipedia/commons/e/e6/Glitch_001.ogg", 
    "sfx_news": "https://upload.wikimedia.org/wikipedia/commons/7/76/Bubbles_001.ogg", 
    "sfx_tech": "https://upload.wikimedia.org/wikipedia/commons/9/91/Synthesized_001.ogg"
}

# --- RESTORED FEEDS ---
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

FEEDS_TECH = [
    "https://www.theverge.com/rss/index.xml",
    "https://techcrunch.com/feed/"
]

WEATHER_URL = "https://rss.weather.gov.hk/rss/LocalWeatherForecast_uc.xml"
REPO_BGM_URL = "https://github.com/hubchangit/daily-news-brief/raw/main/bgm.mp3"


# 2. JANITOR (Restored)
# -----------------------------
def run_janitor():
    """Cleans up old temp files and yesterday's podcast."""
    print("🧹 Janitor working...")
    now_hk = datetime.now(HKT)
    todays_file = f"brief_{now_hk.strftime('%Y%m%d')}.mp3"
    
    # Remove old mp3s that aren't today's final output
    for f in glob.glob("*.mp3"):
        if f != todays_file and not f.startswith("asset_"):
            try: os.remove(f)
            except: pass
            
    # Remove temp download files
    for p in ["temp_*.mp3", "temp.ogg", "dialogue_raw.mp3"]:
        for f in glob.glob(p):
            try: os.remove(f)
            except: pass

# 3. ASSET MANAGER
# -----------------------------
def download_asset(name, url):
    fname = f"asset_{name}.mp3"
    if os.path.exists(fname): return fname
    
    print(f"📥 Downloading {name}...")
    try:
        r = requests.get(url, headers={'User-Agent': 'Bot'})
        with open("temp.ogg", "wb") as f: f.write(r.content)
        seg = AudioSegment.from_ogg("temp.ogg")
        seg = seg.normalize()
        
        # Adjust BGM volume (Make it background level)
        if name == "bgm": seg = seg - 25 
        
        seg.export(fname, format="mp3")
        os.remove("temp.ogg")
        return fname
    except Exception as e:
        print(f"⚠️ Asset {name} failed: {e}")
        return None

def prepare_assets():
    assets = {}
    # First try to get the user's custom BGM from Github
    try:
        if not os.path.exists("asset_bgm.mp3"):
            print("📥 Fetching Custom BGM...")
            r = requests.get(REPO_BGM_URL)
            if r.status_code == 200:
                with open("asset_bgm.mp3", "wb") as f: f.write(r.content)
                assets["bgm"] = "asset_bgm.mp3"
    except: pass

    # Download defaults if custom failed or for other SFX
    for k, v in ASSETS.items():
        if k not in assets: # Don't overwrite if custom BGM exists
            assets[k] = download_asset(k, v)
    return assets

# 4. CONTENT BRAIN
# -----------------------------
def get_rss_content(urls, limit=3):
    text = ""
    count = 0
    if isinstance(urls, str): urls = [urls]
    
    for url in urls:
        if count >= limit: break
        try:
            f = feedparser.parse(url)
            for item in f.entries:
                if count >= limit: break
                summary = re.sub('<[^<]+?>', '', getattr(item, 'summary', ''))[:150]
                text += f"- {item.title} ({summary})\n"
                count += 1
        except: pass
    return text

def clean_text_for_tts(text):
    """
    The Normalizer: Fixes text BEFORE audio generation.
    """
    if not text: return ""
    
    # 1. Percentages: "50%" -> "50 percent" (English word)
    text = text.replace("%", " percent ")
    
    # 2. Currency: HKD/$ -> 港幣/蚊
    text = text.replace("HKD", "港幣")
    text = text.replace("HK$", "港幣")
    text = re.sub(r'\$(\d+)', r'\1蚊', text) 
    
    # 3. Dates/Time: "Jan 23" -> "1月23號"
    text = re.sub(r'Jan (\d+)', r'1月\1號', text)
    text = re.sub(r'Feb (\d+)', r'2月\1號', text)
    # Add more months if needed, or rely on AI to write it correctly.
    
    # 4. Pronunciation Fixes
    text = text.replace("聽朝", "聽日朝早") # Fix "Teng Ciu" error
    
    # 5. Clean Markdown
    text = re.sub(r'\*\*|__|##', '', text)
    
    return text.strip()

def generate_script_json(hk, gl, tech, we, tr):
    # This prompt enforces the JSON structure + Personality
    prompt = f"""
    You are the Producer of "香港早晨" (HK Morning).
    Generate a JSON script.
    
    **SOURCES:**
    HK Trend: {tr}
    HK News: {hk}
    Global: {gl}
    Tech: {tech}
    Weather: {we}

    **CHARACTERS:**
    1. **Tram Girl (girl):** Young, energetic but hates waking up. Loves food (dim sum). Uses HK Slang (e.g. 癲, 世一, 唔係掛).
    2. **Dekisugi (boy):** Calm, data-driven, polite. He corrects the girl's slang or logic.

    **STRUCTURE:**
    1. **Intro:** Girl complains about humidity/hunger. Boy introduces show.
    2. **Deep Dive (HK):** Pick ONE major story. Boy explains details. Girl reacts.
    3. **Global Headlines:** 2-3 quick stories.
    4. **Tech:** One cool innovation. Girl asks if it's expensive.
    5. **Outro:** "See you tomorrow!" (Use 聽日).

    **OUTPUT FORMAT (JSON ONLY):**
    {{
      "dialogue": [
        {{"speaker": "girl", "text": "嘩！好肚餓呀..."}},
        {{"speaker": "boy", "text": "早晨。今日天氣..."}},
        {{"speaker": "sfx", "type": "news"}}, 
        {{"speaker": "boy", "text": "今日重點新聞..."}}
      ]
    }}
    *Valid speakers: "girl", "boy", "sfx".*
    *Valid sfx types: "intro", "news", "tech", "weather".*
    """
    
    print(f"🤖 Brain active: {GENERATION_MODEL}...")
    try:
        model = genai.GenerativeModel(GENERATION_MODEL)
        res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(res.text)
    except Exception as e:
        print(f"⚠️ JSON Gen Failed: {e}")
        # Emergency Fallback JSON
        return {
            "dialogue": [
                {"speaker": "girl", "text": "今日個AI傻咗呀！"},
                {"speaker": "boy", "text": "系統故障，唯有聽日再見。"},
            ]
        }

# 5. AUDIO ENGINE
# -----------------------------
async def synthesize_segment(text, voice, filename):
    # Tune speed/pitch for variety
    if voice == VOICE_GIRL:
        rate = "+25%" 
        pitch = "+2Hz"
    else:
        rate = "+20%" 
        pitch = "+0Hz"
        
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(filename)

async def build_audio(script_data, assets, output_file):
    combined_audio = AudioSegment.empty()
    segments = []
    
    print("🎙️ Recording Segments...")
    
    for i, line in enumerate(script_data.get("dialogue", [])):
        speaker = line.get("speaker")
        
        # --- CASE A: SFX ---
        if speaker == "sfx":
            sfx_type = line.get("type", "news")
            asset_name = f"sfx_{sfx_type}"
            # Map logical names to asset keys
            if sfx_type == "intro": asset_name = "sfx_intro"
            if sfx_type == "tech": asset_name = "sfx_tech"
            
            if asset_name in assets:
                sfx = AudioSegment.from_mp3(assets[asset_name])
                segments.append(sfx)
            continue
            
        # --- CASE B: VOICE ---
        raw_text = line.get("text", "")
        text = clean_text_for_tts(raw_text) # Apply the Normalizer
        
        if not text: continue
        
        voice = VOICE_GIRL if speaker == "girl" else VOICE_BOY
        fname = f"temp_{i}.mp3"
        
        try:
            await synthesize_segment(text, voice, fname)
            seg = AudioSegment.from_mp3(fname)
            
            # Dynamic Pausing (Flow)
            pause_ms = 300
            if "?" in text: pause_ms = 500 # Pause after question
            if len(text) > 40: pause_ms = 600 # Breath after long sentence
            
            segments.append(seg + AudioSegment.silent(duration=pause_ms))
            os.remove(fname)
        except Exception as e:
            print(f"Error line {i}: {e}")

    # Stitch
    full_track = sum(segments)
    
    # Mix BGM
    print("🎚️ Mixing...")
    if "bgm" in assets:
        bgm = AudioSegment.from_mp3(assets["bgm"])
        # Loop BGM
        loops = len(full_track) // len(bgm) + 2
        bgm_long = bgm * loops
        bgm_final = bgm_long[:len(full_track) + 3000].fade_out(2000)
        
        # Overlay with ducking (Voice louder than BGM)
        final_mix = bgm_final.overlay(full_track, position=500)
    else:
        final_mix = full_track

    final_mix.export(output_file, format="mp3")

# 6. PUBLISH
# -----------------------------
def update_rss(audio_file, script_json):
    repo = os.environ.get("GITHUB_REPOSITORY", "local/test")
    base_url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}"
    
    # Generate text summary from JSON
    summary = ""
    for line in script_json.get("dialogue", []):
        if line.get("speaker") in ["girl", "boy"]:
            name = "Tram Girl" if line.get("speaker") == "girl" else "Dekisugi"
            summary += f"{name}: {line.get('text')}\n\n"
            
    p = Podcast(
        name="香港早晨 HK Morning",
        description="Daily Deep Dive & Tech News. AI Generated.",
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
        title=f"早晨！Deep Dive ({now.strftime('%m/%d')})",
        media=Media(f"{base_url}/{audio_file}", 9000000, type="audio/mpeg"),
        summary=summary[:1500],
        publication_date=now,
    ))
    p.rss_file('feed.xml')

# 7. MAIN
# -----------------------------
if __name__ == "__main__":
    run_janitor() # Clean start
    
    now_str = datetime.now(HKT).strftime('%Y%m%d')
    outfile = f"brief_{now_str}.mp3"
    
    print("1. Preparing Assets...")
    assets = prepare_assets()
    
    print("2. Fetching Data...")
    hk = get_rss_content(FEEDS_HK)
    gl = get_rss_content(FEEDS_GLOBAL)
    te = get_rss_content(FEEDS_TECH, limit=2)
    tr = get_rss_content(FEED_TRENDS, limit=5)
    we = get_rss_content(WEATHER_URL, limit=1)
    
    print("3. Generating JSON Script...")
    script = generate_script_json(hk, gl, te, we, tr)
    
    print("4. Audio Production...")
    asyncio.run(build_audio(script, assets, outfile))
    
    print("5. Publishing...")
    update_rss(outfile, script)
    
    print("✅ Done!")
