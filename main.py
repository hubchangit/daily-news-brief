import feedparser
import os
import asyncio
import edge_tts
import re
import glob
from datetime import datetime, timedelta, timezone
from podgen import Podcast, Episode, Media, Person, Category
from huggingface_hub import InferenceClient
from pydub import AudioSegment

# 1. SETUP
# -----------------------------
REPO_ID = "Qwen/Qwen2.5-72B-Instruct" 
HF_TOKEN = os.environ.get("HF_TOKEN")
HKT = timezone(timedelta(hours=8))

# VOICES
# Girl: Cheerful, clear, professional.
VOICE_FEMALE = "zh-HK-HiuGaaiNeural" 
# Uncle: Lower pitch, mature, authoritative.
VOICE_MALE = "zh-HK-WanLungNeural"   

# NEWS SOURCES
# Split into Local and Global to ensure we get a balanced mix
FEEDS_HK = [
    "https://www.scmp.com/rss/2/feed",
    "https://rss.stheadline.com/rss/realtime/hk.xml", # Sing Tao Realtime HK
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
    # Both set to +25% speed (1.25x) as requested
    communicate = edge_tts.Communicate(text, voice, rate="+25%")
    await communicate.save(filename)

async def generate_dialogue_audio(script_text, output_file):
    print("Generating Dialogue Audio...")
    
    # Split script into lines based on the "|" separator
    lines = script_text.split("|")
    combined_audio = AudioSegment.empty()
    
    temp_files = []
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue
        
        # Determine speaker
        if line.startswith("Uncle:"):
            voice = VOICE_MALE
            text = line.replace("Uncle:", "").strip()
        else:
            voice = VOICE_FEMALE
            text = line.replace("Girl:", "").strip()
        
        if not text: continue

        # Generate audio for this line
        temp_filename = f"temp_line_{i}.mp3"
        await generate_line(text, voice, temp_filename)
        
        # Load and append
        segment = AudioSegment.from_mp3(temp_filename)
        combined_audio += segment
        
        # 300ms natural pause between speakers
        combined_audio += AudioSegment.silent(duration=300)
        
        temp_files.append(temp_filename)
    
    # Export full track
    combined_audio.export(output_file, format="mp3")
    
    # Cleanup
    for f in temp_files:
        if os.path.exists(f): os.remove(f)

def mix_music(voice_file, output_file):
    print("Mixing with Music...")
    
    has_music = os.path.exists("bgm.mp3") and os.path.getsize("bgm.mp3") > 1024

    if not has_music:
        if os.path.exists(output_file): os.remove(output_file)
        os.rename(voice_file, output_file)
        return

    try:
        voice = AudioSegment.from_mp3(voice_file)
        bgm = AudioSegment.from_mp3("bgm.mp3")
        bgm = bgm - 23 # Lower volume for background
        
        # Loop music
        looped_bgm = bgm * (len(voice) // len(bgm) + 1)
        final_bgm = looped_bgm[:len(voice) + 4000].fade_out(3000)
        
        # Overlay voice (start 0.5s in)
        final_mix = final_bgm.overlay(voice, position=500)
        final_mix.export(output_file, format="mp3")
        
        if os.path.exists(voice_file): os.remove(voice_file)
            
    except Exception as e:
        print(f"Mixing failed: {e}")
        os.rename(voice_file, output_file)

# 3. CONTENT & SCRIPT
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
                # Clean up description
                desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:200]
                content += f"- {title}: {desc}\n"
                count += 1
        except: pass
    return content

def get_natural_date():
    now = datetime.now(HKT)
    return f"{now.month}月{now.day}日"

def write_script(hk_news, global_news, weather):
    client = InferenceClient(token=HF_TOKEN)
    date_speak = get_natural_date()
    
    # UPDATED PROMPT: INTELLIGENT ANALYST PERSONA
    prompt = f"""
    You are writing a script for a HK Current Affairs Radio Show.
    
    **Characters:**
    1. **Girl:** (Host) Professional, clear, presents the facts.
    2. **Uncle:** (Commentator, "Uncle Wah") Experienced, seasoned Hong Konger.
       - Instead of complaining, he provides **insight, historical context, or economic logic**.
       - He is skeptical but rational. He sounds like a wise mentor or an experienced analyst.
       - He speaks natural Cantonese (口語).

    **Format Rule (STRICT):**
    - Start every line with exactly "Girl:" or "Uncle:".
    - Separate every spoken line with a "|" character. 
    - NO newlines. Keep it one long string.

    **Show Flow:**
    1. **Intro:** Brief greeting.
    2. **Weather:** Girl reports. Uncle advises based on weather (e.g., "Bring umbrella" or "Good for hiking").
    3. **HK News (Cover 4 items):** Girl reads headline. Uncle adds a short, sharp insight (1 sentence).
    4. **Global News (Cover 4 items):** Girl reads headline. Uncle compares it to HK or explains why it matters.
    5. **English Corner:** Girl teaches a phrase. Uncle explains how to use it in business or daily life.
    6. **Outro:** Sign off.

    **Data:**
    Date: {date_speak}
    Weather: {weather}
    HK News: 
    {hk_news}
    Global News: 
    {global_news}

    **Example Style:**
    Girl: 股市今日跌咗三百點。 | Uncle: 其實好正常，因為外圍息口未定，大家都採取觀望態度，唔洗太驚。
    """
    
    try:
        response = client.chat_completion(
            model=REPO_ID, 
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4500, temperature=0.7
        )
        content = response.choices[0].message.content
        return content.replace("\n", " ")
    except Exception as e:
        print(f"AI Error: {e}")
        return "Girl: Error generating script. | Uncle: Technical difficulties."

# 4. MAIN FLOW
# -----------------------------
def cleanup_old_files():
    files = sorted(glob.glob("brief_*.mp3"))
    if len(files) > 3:
        for f in files[:-3]: os.remove(f)

def update_rss(audio_filename, episode_text):
    repo_name = os.environ.get("GITHUB_REPOSITORY", "local/test")
    base_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}"

    p = Podcast(
        name="電車晨報 (Tram Morning Brief)",
        description="Daily News Analysis. HK & Global headlines with insight.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Tram Girl", "news@example.com")],
        owner=Person("Tram Girl", "news@example.com"),
        category=Category("News", "Daily News"),
    )
    
    now_hk = datetime.now(HKT)
    summary_clean = episode_text.replace("|", "\n\n").replace("Girl:", "👧").replace("Uncle:", "👨‍💼")[:500] + "..."
    
    p.add_episode(Episode(
        title=f"晨早新聞分析: {now_hk.strftime('%Y-%m-%d')}",
        media=Media(f"{base_url}/{audio_filename}", 9000000, type="audio/mpeg"),
        summary=summary_clean,
        publication_date=now_hk,
    ))
    p.rss_file('feed.xml')

if __name__ == "__main__":
    cleanup_old_files()

    now_hk = datetime.now(HKT)
    date_str = now_hk.strftime('%Y%m%d')
    final_mp3 = f"brief_{date_str}.mp3"
    temp_voice = "dialogue_raw.mp3"
    
    print("Fetching content...")
    weather = get_weather()
    
    print("Fetching HK News (SCMP/SingTao/RTHK)...")
    hk_news = get_feeds_content(FEEDS_HK, limit=4)
    
    print("Fetching Global News (BBC/Guardian)...")
    global_news = get_feeds_content(FEEDS_GLOBAL, limit=4)
    
    print("Writing script...")
    script = write_script(hk_news, global_news, weather)
    
    # Safety Check
    if "|" not in script:
        script = f"Girl: {script}"

    print("Generating Dialogue Voice (1.25x)...")
    asyncio.run(generate_dialogue_audio(script, temp_voice))
    
    print("Mixing with Music...")
    mix_music(temp_voice, final_mp3)
    
    print("Updating RSS...")
    update_rss(final_mp3, script)
    print("Done!")
