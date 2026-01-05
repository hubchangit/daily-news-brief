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
VOICE_FEMALE = "zh-HK-HiuGaaiNeural" # Tram Girl
VOICE_MALE = "zh-HK-WanLungNeural"   # Dekisugi (Young, smart male voice)

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
    # Both speakers at 1.25x speed for snappy "Radio" feel
    communicate = edge_tts.Communicate(text, voice, rate="+25%")
    await communicate.save(filename)

async def generate_dialogue_audio(script_text, output_file):
    print("Generating Dialogue Audio...")
    
    lines = script_text.split("|")
    combined_audio = AudioSegment.empty()
    temp_files = []
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue
        
        # Determine speaker
        if line.startswith("Dekisugi:"):
            voice = VOICE_MALE
            text = line.replace("Dekisugi:", "").strip()
        else:
            voice = VOICE_FEMALE
            text = line.replace("Girl:", "").strip()
        
        if not text: continue

        temp_filename = f"temp_line_{i}.mp3"
        await generate_line(text, voice, temp_filename)
        
        segment = AudioSegment.from_mp3(temp_filename)
        combined_audio += segment
        combined_audio += AudioSegment.silent(duration=300)
        temp_files.append(temp_filename)
    
    combined_audio.export(output_file, format="mp3")
    
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
        bgm = bgm - 23 
        
        looped_bgm = bgm * (len(voice) // len(bgm) + 1)
        final_bgm = looped_bgm[:len(voice) + 4000].fade_out(3000)
        
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
    
    prompt = f"""
    You are writing a script for a HK News Podcast.
    
    **Characters:**
    1. **Girl:** (Host) Energetic, curious, asks questions.
    2. **Dekisugi:** (出木杉 - Co-host) Young, highly intelligent, calm, and analytical. 
       - He sounds like a top student or a young expert.
       - He explains complex news simply and logically.
       - He is polite but very sharp.

    **LANGUAGE RULES (CRITICAL):**
    - You MUST use **Cantonese Colloquialism (廣東話口語)**.
    - NEVER use "的", use "嘅".
    - NEVER use "是", use "係".
    - NEVER use "他", use "佢".
    - NEVER use "什麼", use "咩".
    - Make it sound like two young HK people chatting naturally.

    **Format Rule:**
    - Start lines with "Girl:" or "Dekisugi:".
    - Separate lines with "|".
    - No newlines.

    **Show Flow:**
    1. **Intro:** Girl greets. Dekisugi gives a polite, smart greeting.
    2. **Weather:** Girl reads. Dekisugi analyzes (e.g., "The humidity implies we should...").
    3. **HK News (4 items):** Girl reads. Dekisugi adds logical analysis or context.
    4. **Global News (4 items):** Girl reads. Dekisugi explains the global impact.
    5. **English Corner:** Girl teaches a phrase. Dekisugi explains its origin or proper grammatical usage perfectly.
    6. **Outro:** Smart sign-off.

    **Data:**
    Date: {date_speak}
    Weather: {weather}
    HK News: 
    {hk_news}
    Global News: 
    {global_news}

    **Example:**
    Girl: 哇，今日個市跌得好勁呀！ | Dekisugi: 其實係受外圍因素影響嘅，投資者唔洗太過恐慌，基本面仲係好穩健。
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
        return "Girl: Error generating script. | Dekisugi: System malfunction."

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
        name="電車少女 vs 出木杉",
        description="Daily News. Energetic Host vs The Smart Analyst.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Tram Girl", "news@example.com")],
        owner=Person("Tram Girl", "news@example.com"),
        category=Category("News", "Daily News"),
    )
    
    now_hk = datetime.now(HKT)
    # Update RSS summary format
    summary_clean = episode_text.replace("|", "\n\n").replace("Girl:", "👧").replace("Dekisugi:", "🤓")[:500] + "..."
    
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
    hk_news = get_feeds_content(FEEDS_HK, limit=4)
    global_news = get_feeds_content(FEEDS_GLOBAL, limit=4)
    
    print("Writing script (Colloquial Cantonese)...")
    script = write_script(hk_news, global_news, weather)
    
    if "|" not in script:
        script = f"Girl: {script}"

    print("Generating Dialogue Voice...")
    asyncio.run(generate_dialogue_audio(script, temp_voice))
    
    print("Mixing with Music...")
    mix_music(temp_voice, final_mp3)
    
    print("Updating RSS...")
    update_rss(final_mp3, script)
    print("Done!")
