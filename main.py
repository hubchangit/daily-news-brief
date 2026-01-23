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

# VOICES
VOICE_FEMALE = "zh-HK-HiuGaaiNeural" 
VOICE_MALE = "zh-HK-WanLungNeural"   

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
FEEDS_TECH = [
    "https://www.theverge.com/rss/index.xml",
    "https://techcrunch.com/feed/"
]
WEATHER_URL = "https://rss.weather.gov.hk/rss/LocalWeatherForecast_uc.xml"
REPO_BGM_URL = "https://github.com/hubchangit/daily-news-brief/raw/main/bgm.mp3"

# 2. AUDIO ENGINE
# -----------------------------
async def generate_line(text, voice, filename):
    # SPEED: 1.2x for both (Standard HK fast pace)
    if voice == VOICE_FEMALE:
        rate = "+20%" 
        pitch = "+2Hz"
    else:
        rate = "+20%" 
        pitch = "+0Hz"
        
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(filename)

async def generate_dialogue_audio(script_text, output_file):
    print("Generating Dialogue Audio...")
    
    # 1. Super Clean First
    # Remove bolding (**), italics (__), and weird invisible chars
    clean_text = script_text.replace("**", "").replace("__", "").replace("##", "")
    lines = clean_text.split("|")
    
    combined_audio = AudioSegment.empty()
    temp_files = []
    
    # Default start (just in case)
    current_voice = VOICE_FEMALE 

    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue
        
        # 2. ROBUST SPEAKER DETECTION
        # We search for the name *anywhere* in the first 20 characters
        # This fixes the issue where " **Tram Girl**:" or "1. Tram Girl:" broke the parser.
        
        lower_line = line[:30].lower() # Look at start of line
        
        is_boy = "出木杉" in line or "dekisugi" in lower_line
        is_girl = "電車少女" in line or "tram girl" in lower_line or "girl" in lower_line

        if is_boy:
            current_voice = VOICE_MALE
            # REMOVE THE NAME LABEL (Aggressive)
            # Regex removes "Name" + any characters until the colon/space
            text = re.sub(r'^.*?(出木杉|Dekisugi).*?[:：]', '', line, flags=re.IGNORECASE)
        elif is_girl:
            current_voice = VOICE_FEMALE
            text = re.sub(r'^.*?(電車少女|Tram Girl|Girl).*?[:：]', '', line, flags=re.IGNORECASE)
        else:
            # No name found? It's a continuation line.
            # Keep the SAME voice as before.
            text = line

        # 3. TEXT FIXES (HK Style)
        
        # Fix: % -> "percent" (English pronunciation)
        text = text.replace("%", " percent ")
        
        # Fix: 聽朝 -> 聽日朝早 (Fixes "Teng Ciu" misread)
        text = text.replace("聽朝", "聽日朝早")
        
        # Cleanup: Remove instructions like (laughs) or [sigh]
        text = re.sub(r'[\(\[].*?[\)\]]', '', text).strip()
        
        if len(text) < 1: continue

        temp_filename = f"temp_line_{i}.mp3"
        try:
            # print(f"Speaking ({current_voice}): {text[:15]}...")
            await generate_line(text, current_voice, temp_filename)
            
            if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 0:
                segment = AudioSegment.from_mp3(temp_filename)
                combined_audio += segment
                
                # Pause Logic
                pause_ms = 400 if len(segment) > 2500 else 200
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
    try:
        r = requests.get(REPO_BGM_URL)
        if r.status_code == 200:
            with open("bgm.mp3", "wb") as f:
                f.write(r.content)
            return True
    except: pass
    try:
        url = "https://upload.wikimedia.org/wikipedia/commons/5/5b/Kevin_MacLeod_-_Local_Forecast_-_Elevator.ogg"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        with open("bgm.ogg", "wb") as f:
            f.write(r.content)
        song = AudioSegment.from_ogg("bgm.ogg")[:45000]
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
        bgm = AudioSegment.from_mp3("bgm.mp3") - 28 # Soft Background
        
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

def get_feeds(urls, limit=5):
    content = ""
    count = 0
    for url in urls:
        if count >= limit: break
        try:
            f = feedparser.parse(url)
            for item in f.entries:
                if count >= limit: break
                desc = re.sub('<[^<]+?>', '', getattr(item, 'summary', ''))[:100]
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
    # Hugging Face Fallback
    try:
        print("🚨 Using HuggingFace Backup...")
        client = InferenceClient(api_key=os.environ["HF_TOKEN"])
        msgs = [{"role": "user", "content": prompt}]
        res = client.chat_completion(model="Qwen/Qwen2.5-72B-Instruct", messages=msgs, max_tokens=3000)
        return res.choices[0].message.content.replace("\n", " ")
    except:
        return "出木杉: 系統故障。 | 電車少女: 聽日再見！"

def write_script(hk, gl, tech, we, tr):
    prompt = f"""
    You are the producer of the podcast "**香港早晨**" (Hong Kong Morning).
    Write the script for "電車少女" (Tram Girl) and "出木杉" (Dekisugi).
    
    **Language & Style:**
    - **Authentic HK Cantonese (廣東話口語)**. 
    - **VITAL:** Use "percent" (English) for %. Write % symbol in script.
    - **Tone:** - Girl: High energy, uses slang (勁, 癲, 唔係掛), asks questions.
       - Boy: Smart, calm, professional explanations.

    **Format (Strictly Follow):**
    - Use '|' to separate dialogue. NO NEWLINES.
    - Format: "Name: Text | Name: Text".
    - Do NOT use asterisks (**Name**) for names. Just plain text.
    
    **Script Sections:**
    1. **Intro:** Quick energetic hello to "香港早晨".
    2. **Weather:** Update ({we}).
    3. **HK News (3 Stories):** - 1st: Discuss Top Trend ({tr}).
       - 2nd & 3rd: From ({hk}).
    4. **Global News (3 Stories):** From ({gl}).
    5. **Innovation & Ideas (Tech):** - Boy introduces ONE cool tech from: {tech}.
       - Girl asks: "Does it really work?" or jokes.
    6. **Outro:** "See you tomorrow!" (Use "聽日" instead of "聽朝").
    
    **Content to cover:**
    HK: {hk}
    Global: {gl}
    Tech: {tech}
    """
    return generate_script_robust(prompt)

def update_rss(audio_file, script):
    repo = os.environ.get("GITHUB_REPOSITORY", "local/test")
    base_url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}"
    
    p = Podcast(
        name="香港早晨",
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
        title=f"香港早晨: {now.strftime('%Y-%m-%d')}",
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
    
    # Safety Check
    if "電車少女:" not in script:
        script = "電車少女: Hello! | " + script

    try:
        asyncio.run(generate_dialogue_audio(script, "dialogue_raw.mp3"))
        mix_music("dialogue_raw.mp3", final_mp3)
        update_rss(final_mp3, script)
        print("Done!")
    except Exception as e:
        print(f"ERROR: {e}")
        exit(1)
