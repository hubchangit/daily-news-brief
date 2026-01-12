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
# Configure Google Gemini
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

HKT = timezone(timedelta(hours=8))

# VOICES (Edge TTS)
# We tune them slightly in the generate function
VOICE_FEMALE = "zh-HK-HiuGaaiNeural" # Tram Girl
VOICE_MALE = "zh-HK-WanLungNeural"   # Dekisugi

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

# 2. AUDIO PROCESSING ENGINE
# -----------------------------
async def generate_line(text, voice, filename):
    # TUNING: 
    # Girls speak slightly faster (+10%) for energy.
    # Dekisugi speaks at normal speed (+0%) but slightly lower pitch if possible
    # (Note: edge-tts pitch adjustment is tricky, so we rely on rate)
    
    if voice == VOICE_FEMALE:
        rate = "+10%" 
    else:
        rate = "+0%" # Slower, more analytical/calm for Dekisugi
        
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(filename)

async def generate_dialogue_audio(script_text, output_file):
    print("Generating Dialogue Audio...")
    
    lines = script_text.split("|")
    combined_audio = AudioSegment.empty()
    temp_files = []
    
    valid_audio_count = 0

    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue
        
        # Determine speaker
        if "Dekisugi:" in line:
            voice = VOICE_MALE
            text = line.replace("Dekisugi:", "").strip()
        else:
            voice = VOICE_FEMALE
            text = line.replace("Girl:", "").strip()
        
        # Cleanup symbols that choke TTS
        text = re.sub(r'[^\w\s\u4e00-\u9fff,.?!，。？！]', '', text)
        if not text or len(text) < 1: continue

        temp_filename = f"temp_line_{i}.mp3"
        
        try:
            print(f"Speaking ({voice}): {text[:15]}...")
            await generate_line(text, voice, temp_filename)
            
            if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 0:
                segment = AudioSegment.from_mp3(temp_filename)
                combined_audio += segment
                # 350ms pause for better pacing
                combined_audio += AudioSegment.silent(duration=350)
                temp_files.append(temp_filename)
                valid_audio_count += 1
            else:
                print("⚠️ Generated file was empty.")

        except Exception as e:
            print(f"⚠️ TTS Error on line '{text}': {e}")
            continue

    if valid_audio_count == 0:
        raise Exception("No valid audio was generated!")

    combined_audio.export(output_file, format="mp3")
    
    # Cleanup
    for f in temp_files:
        if os.path.exists(f): os.remove(f)

def mix_music(voice_file, output_file):
    print("Mixing with Music...")
    bgm_path = "bgm.mp3"
    
    if not os.path.exists(bgm_path):
        print("Music missing. Using voice only.")
        if os.path.exists(output_file): os.remove(output_file)
        os.rename(voice_file, output_file)
        return

    try:
        voice = AudioSegment.from_mp3(voice_file)
        bgm = AudioSegment.from_mp3(bgm_path)
        bgm = bgm - 22 
        
        looped_bgm = bgm * (len(voice) // len(bgm) + 1)
        final_bgm = looped_bgm[:len(voice) + 4000].fade_out(3000)
        
        final_mix = final_bgm.overlay(voice, position=500)
        final_mix.export(output_file, format="mp3")
        
        if os.path.exists(voice_file): os.remove(voice_file)
            
    except Exception as e:
        print(f"Mixing failed: {e}")
        if os.path.exists(output_file): os.remove(output_file)
        os.rename(voice_file, output_file)

# 3. SUPER JANITOR
# -----------------------------
def run_super_janitor():
    print("🧹 Super Janitor starting...")
    now_hk = datetime.now(HKT)
    todays_filename = f"brief_{now_hk.strftime('%Y%m%d')}.mp3"
    
    # Delete old episodes (except today's if it exists)
    for f in glob.glob("brief_*.mp3"):
        if f != todays_filename:
            try: os.remove(f)
            except: pass
            
    # Delete junk
    junk_patterns = ["temp_line_*.mp3", "temp_voice.mp3", "dialogue_raw.mp3"]
    for pattern in junk_patterns:
        for j in glob.glob(pattern):
            try: os.remove(j)
            except: pass

# 4. GEMINI SCRIPT GENERATION
# -----------------------------
def get_weather():
    try:
        feed = feedparser.parse(WEATHER_URL)
        if feed.entries:
            return feed.entries[0].description.replace('<br/>', ' ')[:300]
    except: return "Weather unavailable."

def get_feeds_content(urls, limit=4):
    content = ""
    count = 0
    for url in urls:
        if count >= limit: break
        try:
            feed = feedparser.parse(url)
            for item in feed.entries:
                if count >= limit: break
                title = item.title
                desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:200]
                content += f"- {title}: {desc}\n"
                count += 1
        except: pass
    return content

def write_script(hk_news, global_news, weather):
    # Use Gemini 1.5 Flash (Free & Fast)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    now = datetime.now(HKT)
    date_speak = f"{now.month}月{now.day}日"
    
    prompt = f"""
    You are the scriptwriter for "Tram Girl & Dekisugi", a Hong Kong morning news podcast.

    **Characters:**
    1. **Girl (Tram Girl):** Energetic, cheerful, relatable. She asks the questions normal people have.
    2. **Dekisugi (出木杉):** Calm, intelligent, analytical. He explains complex news simply and logically.

    **LANGUAGE REQUIREMENTS (STRICT):**
    - **Language:** Authentic Hong Kong Cantonese (廣東話口語).
    - **Keywords:** Use "嘅" (not 的), "係" (not 是), "佢" (not 他), "咁" (not 這樣).
    - **Tone:** Conversational. They should banter slightly.

    **Format Requirements:**
    - Format: `Girl: [Text] | Dekisugi: [Text] | Girl: [Text]`
    - **ONE SINGLE LINE.** Do not use newlines. Use "|" to separate speakers.
    
    **Show Structure:**
    1. **Intro:** Girl greets energeticly. Dekisugi greets calmly.
    2. **Weather:** {weather} (Dekisugi gives practical advice, e.g., umbrella/air con).
    3. **HK News Analysis:** - News: {hk_news}
       - Girl mentions a headline. Dekisugi explains the *implication* (e.g., impact on property/prices/daily life).
    4. **Global News:** - News: {global_news}
       - Brief mention of 1-2 major stories.
    5. **Outro:** Quick positive sign-off.

    **Script:**
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text
        # Safety cleanups
        text = text.replace("\n", " ").replace("**", "")
        return text
    except Exception as e:
        print(f"Gemini Error: {e}")
        return "Girl: 系統故障。 | Dekisugi: 請稍後再試。"

def update_rss(audio_filename, episode_text):
    repo_name = os.environ.get("GITHUB_REPOSITORY", "local/test")
    if not repo_name: repo_name = "local/test"
    
    parts = repo_name.split('/')
    if len(parts) >= 2:
        base_url = f"https://{parts[0]}.github.io/{parts[1]}"
    else:
        base_url = "https://example.com"

    p = Podcast(
        name="電車少女 vs 出木杉 (Gemini Ed.)",
        description="Daily HK News Analysis. Powered by Google Gemini.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Tram Girl", "news@example.com")],
        owner=Person("Tram Girl", "news@example.com"),
        category=Category("News", "Daily News"),
    )
    
    now_hk = datetime.now(HKT)
    summary_clean = episode_text.replace("|", "\n\n").replace("Girl:", "👧").replace("Dekisugi:", "🤓")[:500] + "..."
    
    p.add_episode(Episode(
        title=f"晨早新聞: {now_hk.strftime('%Y-%m-%d')}",
        media=Media(f"{base_url}/{audio_filename}", 9000000, type="audio/mpeg"),
        summary=summary_clean,
        publication_date=now_hk,
    ))
    p.rss_file('feed.xml')

# 5. MAIN
# -----------------------------
if __name__ == "__main__":
    run_super_janitor()

    now_hk = datetime.now(HKT)
    final_mp3 = f"brief_{now_hk.strftime('%Y%m%d')}.mp3"
    temp_voice = "dialogue_raw.mp3"
    
    print("Fetching content...")
    weather = get_weather()
    hk_news = get_feeds_content(FEEDS_HK, limit=4)
    global_news = get_feeds_content(FEEDS_GLOBAL, limit=4)
    
    print("Writing script with Google Gemini...")
    script = write_script(hk_news, global_news, weather)
    
    # Fallback if AI fails to format correctly
    if "|" not in script: script = f"Girl: {script}"

    try:
        print("Generating Voice...")
        asyncio.run(generate_dialogue_audio(script, temp_voice))
        
        print("Mixing...")
        mix_music(temp_voice, final_mp3)
        
        print("Updating RSS...")
        update_rss(final_mp3, script)
        print("Done!")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        exit(1)
