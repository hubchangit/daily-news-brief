import feedparser
import os
import asyncio
import edge_tts
import re
import glob
import requests
from datetime import datetime, timedelta, timezone
from podgen import Podcast, Episode, Media, Person, Category
from huggingface_hub import InferenceClient
from pydub import AudioSegment

# 1. SETUP
# -----------------------------
REPO_ID = "Qwen/Qwen2.5-72B-Instruct" 
HF_TOKEN = os.environ.get("HF_TOKEN")
HKT = timezone(timedelta(hours=8))

# BGM SOURCE (Erik Satie - Gymnopedie No.1 - Very relaxing/Classy)
BGM_URL = "https://upload.wikimedia.org/wikipedia/commons/e/ea/Gymnopedie_No_1.ogg"

FEEDS = [
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",
    "https://www.scmp.com/rss/2/feed",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.theguardian.com/world/rss"
]
WEATHER_URL = "https://rss.weather.gov.hk/rss/LocalWeatherForecast_uc.xml"

# 2. AUDIO MIXING ENGINE
# -----------------------------
def download_bgm():
    if not os.path.exists("bgm.ogg"):
        print("Downloading Background Music...")
        response = requests.get(BGM_URL)
        with open("bgm.ogg", "wb") as f:
            f.write(response.content)

def mix_audio(voice_file, output_file):
    print("Mixing Audio with Music...")
    
    # Load Voice
    voice = AudioSegment.from_mp3(voice_file)
    
    # Load BGM
    download_bgm()
    bgm = AudioSegment.from_ogg("bgm.ogg")
    
    # Lower BGM volume by 20dB so it doesn't overpower the voice
    bgm = bgm - 22 
    
    # Loop BGM to match voice length
    looped_bgm = bgm * (len(voice) // len(bgm) + 1)
    
    # Trim BGM to exact voice length + 2 seconds fade out
    final_bgm = looped_bgm[:len(voice) + 2000]
    final_bgm = final_bgm.fade_out(2000)
    
    # Overlay Voice on BGM
    # (position=1000 means voice starts 1 second after music starts)
    final_mix = final_bgm.overlay(voice, position=1000)
    
    # Export
    final_mix.export(output_file, format="mp3")
    
    # Clean up temp voice file
    if os.path.exists(voice_file):
        os.remove(voice_file)

# 3. CONTENT GENERATION
# -----------------------------
def get_weather():
    try:
        feed = feedparser.parse(WEATHER_URL)
        if feed.entries:
            return feed.entries[0].description.replace('<br/>', ' ')[:300]
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

def clean_script_for_speech(text):
    text = re.sub(r'[*#_`~]', '', text)
    return re.sub(r'\n+', '\n', text).strip()

def get_natural_date():
    now = datetime.now(HKT)
    return f"{now.month}月{now.day}日"

def write_script(raw_news, weather):
    client = InferenceClient(token=HF_TOKEN)
    date_speak = get_natural_date()
    
    prompt = f"""
    You are "Tram Girl" (電車少女). Write a 5-7 minute news script in Cantonese.
    
    **NEW SEGMENT:** Include a "Daily English Corner" at the end.
    
    Structure:
    1. **Intro:** "哈囉大家好，今日係 {date_speak}..."
    2. **Weather:** Brief summary.
    3. **News Deep Dive:** HK & Global News.
    4. **Daily English Corner (IMPORTANT):** - Teach ONE cool English Slang (e.g., "Spill the tea", "Rent free") OR a 2-line Poem.
       - Explain the meaning in Cantonese.
       - Use it in a sentence.
    5. **Outro:** "Okay, time to get off the tram. See you tomorrow!"

    News Data:
    {raw_news}
    weather Data:
    {weather}
    
    Rules: NO Markdown. Speak naturally.
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

async def generate_raw_voice(text, filename):
    clean = clean_script_for_speech(text)
    communicate = edge_tts.Communicate(clean, "zh-HK-HiuGaaiNeural", rate="+50%")
    await communicate.save(filename)

# 4. RSS & CLEANUP
# -----------------------------
def cleanup_old_files():
    files = sorted(glob.glob("brief_*.mp3"))
    if len(files) > 3:
        for f in files[:-3]:
            try:
                os.remove(f)
            except: pass

def update_rss(audio_filename, episode_text):
    repo_name = os.environ.get("GITHUB_REPOSITORY", "local/test")
    base_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}"

    p = Podcast(
        name="電車少女 (Tram Girl)",
        description="Daily HK News, Weather & English Corner.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Tram Girl", "news@example.com")],
        owner=Person("Tram Girl", "news@example.com"),
        category=Category("News", "Daily News"),
    )
    
    now_hk = datetime.now(HKT)
    p.add_episode(Episode(
        title=f"電車日記: {now_hk.strftime('%Y-%m-%d')}",
        media=Media(f"{base_url}/{audio_filename}", 9000000, type="audio/mpeg"),
        summary="Featuring: Daily News + English Corner (Slang/Poetry)",
        publication_date=now_hk,
    ))
    p.rss_file('feed.xml')

# MAIN
if __name__ == "__main__":
    cleanup_old_files()

    now_hk = datetime.now(HKT)
    date_str = now_hk.strftime('%Y%m%d')
    final_mp3 = f"brief_{date_str}.mp3"
    temp_voice = "temp_voice.mp3"
    
    print("Fetching content...")
    weather = get_weather()
    news = get_news()
    
    print("Writing script...")
    script = write_script(news, weather)
    
    print("Generating Raw Voice...")
    asyncio.run(generate_raw_voice(script, temp_voice))
    
    print("Mixing with Music...")
    mix_audio(temp_voice, final_mp3)
    
    print("Updating RSS...")
    update_rss(final_mp3, script)
    print("Done!")
