import feedparser
import os
import asyncio
import edge_tts
import re
import glob
import google.generativeai as genai
from datetime import datetime, timedelta, timezone
from podgen import Podcast, Episode, Media, Person, Category
from pydub import AudioSegment

# 1. SETUP
# -----------------------------
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
HKT = timezone(timedelta(hours=8))

# VOICES
VOICE_FEMALE = "zh-HK-HiuGaaiNeural" 
VOICE_MALE = "zh-HK-WanLungNeural"   

# NEWS SOURCES
FEEDS_HK = [
    "https://www.scmp.com/rss/2/feed",
    "https://rss.stheadline.com/rss/realtime/hk.xml",
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"
]

FEEDS_GLOBAL = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.theguardian.com/world/rss"
]

WEATHER_URL = "https://rss.weather.gov.hk/rss/LocalWeatherForecast_uc.xml"

# 2. AUDIO ENGINE
# -----------------------------
async def generate_line(text, voice, filename):
    # Tuning: Girl slightly faster, Dekisugi neutral
    rate = "+10%" if voice == VOICE_FEMALE else "+0%"
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(filename)

async def generate_dialogue_audio(script_text, output_file):
    print("Generating Dialogue Audio...")
    lines = script_text.split("|")
    combined_audio = AudioSegment.empty()
    temp_files = []
    valid_count = 0

    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue
        
        # LOGIC FIX: Check for Chinese names OR English names
        if "Dekisugi:" in line or "出木杉:" in line:
            voice = VOICE_MALE
            # Remove both possible prefixes
            text = line.replace("Dekisugi:", "").replace("出木杉:", "").strip()
        else:
            # Default to Girl if unsure
            voice = VOICE_FEMALE
            text = line.replace("Girl:", "").replace("電車少女:", "").strip()
        
        # Cleanup bad symbols
        text = re.sub(r'[^\w\s\u4e00-\u9fff,.?!，。？！]', '', text)
        if len(text) < 1: continue

        temp_filename = f"temp_line_{i}.mp3"
        try:
            print(f"Speaking ({voice}): {text[:10]}...")
            await generate_line(text, voice, temp_filename)
            
            if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 0:
                segment = AudioSegment.from_mp3(temp_filename)
                combined_audio += segment
                combined_audio += AudioSegment.silent(duration=350)
                temp_files.append(temp_filename)
                valid_count += 1
        except Exception as e:
            print(f"Skipping line: {e}")
            continue

    if valid_count == 0: raise Exception("Audio generation failed.")
    combined_audio.export(output_file, format="mp3")
    for f in temp_files:
        if os.path.exists(f): os.remove(f)

def mix_music(voice_file, output_file):
    print("Mixing music...")
    if not os.path.exists("bgm.mp3"):
        if os.path.exists(output_file): os.remove(output_file)
        os.rename(voice_file, output_file)
        return

    try:
        voice = AudioSegment.from_mp3(voice_file)
        bgm = AudioSegment.from_mp3("bgm.mp3") - 22
        looped_bgm = bgm * (len(voice) // len(bgm) + 1)
        final_bgm = looped_bgm[:len(voice) + 4000].fade_out(3000)
        final_mix = final_bgm.overlay(voice, position=500)
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
    for pat in ["temp_*.mp3", "dialogue_raw.mp3"]:
        for f in glob.glob(pat):
            try: os.remove(f)
            except: pass

# 4. CONTENT (WITH FALLBACK)
# -----------------------------
def get_weather():
    try:
        f = feedparser.parse(WEATHER_URL)
        return f.entries[0].description.replace('<br/>', ' ')[:300] if f.entries else "N/A"
    except: return "N/A"

def get_feeds(urls):
    content = ""
    count = 0
    for url in urls:
        if count >= 4: break
        try:
            f = feedparser.parse(url)
            for item in f.entries:
                if count >= 4: break
                content += f"- {item.title}\n"
                count += 1
        except: pass
    return content

def generate_script_safe(prompt):
    """Tries multiple models to avoid 404 errors"""
    models_to_try = ["gemini-1.5-flash", "gemini-pro", "gemini-1.0-pro"]
    
    for model_name in models_to_try:
        print(f"🤖 Attempting to generate script with model: {model_name}...")
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text.replace("\n", " ").replace("**", "")
        except Exception as e:
            print(f"⚠️ Model {model_name} failed: {e}")
            continue
            
    # If all fail
    print("❌ All Gemini models failed.")
    return "電車少女: 今日系統發生嚴重故障。 | 出木杉: 我地聽日再嘗試啦。"

def write_script(hk_news, global_news, weather):
    prompt = f"""
    You are writing a script for "Tram Girl & Dekisugi" (Hong Kong News Podcast).
    
    **Language:** Authentic Hong Kong Cantonese (廣東話口語).
    **Format:** One single line. Use "|" to separate speakers. No newlines.
    
    **Content:**
    1. Girl & Dekisugi Intro.
    2. Weather: {weather}
    3. HK News: {hk_news} (Dekisugi analyzes).
    4. Global News: {global_news}.
    5. Outro.

    **Example:**
    電車少女: 早晨！今日天氣點呀？ | 出木杉: 今日有雨，記得帶遮啦。
    """
    return generate_script_safe(prompt)

def update_rss(audio_file, script):
    repo = os.environ.get("GITHUB_REPOSITORY", "local/test")
    base_url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}"
    
    p = Podcast(
        name="香港早晨",
        description="HK News Analysis via Gemini AI.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Tram Girl", "news@ex.com")],
        owner=Person("Tram Girl", "news@ex.com"),
        category=Category("News"),
    )
    
    now = datetime.now(HKT)
    p.add_episode(Episode(
        title=f"晨早新聞: {now.strftime('%Y-%m-%d')}",
        media=Media(f"{base_url}/{audio_file}", 9000000, type="audio/mpeg"),
        summary=script.replace("|", "\n\n")[:500],
        publication_date=now,
    ))
    p.rss_file('feed.xml')

# 5. MAIN
# -----------------------------
if __name__ == "__main__":
    run_janitor()
    
    now_str = datetime.now(HKT).strftime('%Y%m%d')
    final_mp3 = f"brief_{now_str}.mp3"
    
    print("Fetching news...")
    hk = get_feeds(FEEDS_HK)
    gl = get_feeds(FEEDS_GLOBAL)
    we = get_weather()
    
    print("Generating script...")
    script = write_script(hk, gl, we)
    
    # Fallback to ensure "Girl" speaks if format is broken
    if "|" not in script: script = f"電車少女: {script}"
    
    try:
        asyncio.run(generate_dialogue_audio(script, "dialogue_raw.mp3"))
        mix_music("dialogue_raw.mp3", final_mp3)
        update_rss(final_mp3, script)
        print("Done!")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        exit(1)
