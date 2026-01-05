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
VOICE_FEMALE = "zh-HK-HiuGaaiNeural" # Tram Girl (Professional, Cheerful)
VOICE_MALE = "zh-HK-WanLungNeural"   # Victoria Park Uncle (Grumpy, Low pitched)

FEEDS = [
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",
    "https://www.scmp.com/rss/2/feed",
    "https://feeds.bbci.co.uk/news/world/rss.xml"
]
WEATHER_URL = "https://rss.weather.gov.hk/rss/LocalWeatherForecast_uc.xml"

# 2. AUDIO PROCESSING ENGINE
# -----------------------------
async def generate_line(text, voice, filename):
    # Uncle talks slightly slower and louder (simulated by engine)
    rate = "+10%" if voice == VOICE_MALE else "+20%"
    communicate = edge_tts.Communicate(text, voice, rate=rate)
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
        
        # Determine speaker based on tags
        if line.startswith("Uncle:"):
            voice = VOICE_MALE
            text = line.replace("Uncle:", "").strip()
        else:
            voice = VOICE_FEMALE
            text = line.replace("Girl:", "").strip() # Default to Girl
        
        if not text: continue

        # Generate audio for this specific line
        temp_filename = f"temp_line_{i}.mp3"
        await generate_line(text, voice, temp_filename)
        
        # Load and append
        segment = AudioSegment.from_mp3(temp_filename)
        combined_audio += segment
        
        # Add a pause. 
        # Shorter pause if Uncle interrupts (optional logic), but 300ms is standard natural gap.
        combined_audio += AudioSegment.silent(duration=300)
        
        temp_files.append(temp_filename)
    
    # Export the full dialogue track
    combined_audio.export(output_file, format="mp3")
    
    # Cleanup individual line files
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
        bgm = bgm - 23 # Lower music volume
        
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

def get_news():
    full_text = ""
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for item in feed.entries[:3]:
                desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:200]
                full_text += f"{item.title}: {desc}\n"
        except: pass
    return full_text

def get_natural_date():
    now = datetime.now(HKT)
    return f"{now.month}月{now.day}日"

def write_script(raw_news, weather):
    client = InferenceClient(token=HF_TOKEN)
    date_speak = get_natural_date()
    
    # UPDATED PROMPT FOR "VICTORIA PARK UNCLE"
    prompt = f"""
    You are writing a script for a HK Morning Radio Show (Talk Show style).
    
    **Characters:**
    1. **Girl**: "Tram Girl" (電車少女). Young, energetic, polite, tries to report news professionally.
    2. **Uncle**: "Victoria Park Uncle" (維園阿伯). Old, loud, very critical, opinionated. 
       - He uses heavy HK slang (e.g., "搞錯", "離譜", "食塞米").
       - He constantly interrupts or complains about the government/weather/prices, but he loves HK deep down.

    **Format Rule (STRICT):**
    - Start every line with exactly "Girl:" or "Uncle:".
    - Separate every spoken line with a "|" character. 
    - NO newlines between dialogue. Keep it one long string separated by "|".

    **Structure:**
    1. **Intro:** Girl says hello. Uncle complains about waking up early or the humidity.
    2. **Weather:** Girl reads forecast. Uncle reacts (e.g., "又落雨？天文台信唔信得過架？").
    3. **News:** Girl reads ~3 headlines. Uncle gives a "hot take" or critical comment on each.
    4. **English Corner:** Girl teaches a modern slang. Uncle tries to use it but fails or mocks it.
    5. **Outro:** Girl signs off. Uncle says he's going to drink Yam Cha.

    **Data:**
    Date: {date_speak}
    Weather: {weather}
    News: {raw_news}

    **Example Output:**
    Girl: 早晨大家早！今日係 {date_speak}。 | Uncle: 唉，又係朝早，條腰好痛呀！ | Girl: 睇黎今日會有雨喎。 | Uncle: 哼！天文台講野邊度準架！
    """
    
    try:
        response = client.chat_completion(
            model=REPO_ID, 
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000, temperature=0.7
        )
        content = response.choices[0].message.content
        # Safety cleanup: remove newlines so the splitter works perfectly
        return content.replace("\n", " ")
    except Exception as e:
        print(f"AI Error: {e}")
        return "Girl: Error generating script. | Uncle: 機器壞咗啦！"

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
        name="電車少女 vs 維園阿伯",
        description="Daily HK News. Energetic Host vs Grumpy Victoria Park Uncle.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Tram Girl", "news@example.com")],
        owner=Person("Tram Girl", "news@example.com"),
        category=Category("News", "Daily News"),
    )
    
    now_hk = datetime.now(HKT)
    # Make the summary readable in the RSS app
    summary_clean = episode_text.replace("|", "\n\n").replace("Girl:", "👧").replace("Uncle:", "👴")[:500] + "..."
    
    p.add_episode(Episode(
        title=f"早晨！{now_hk.strftime('%Y-%m-%d')} (維園版)",
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
    news = get_news()
    
    print("Writing script...")
    script = write_script(news, weather)
    
    # Fallback safety for the tag
    if "|" not in script:
        script = f"Girl: {script}"

    print("Generating Dialogue Voice...")
    asyncio.run(generate_dialogue_audio(script, temp_voice))
    
    print("Mixing with Music...")
    mix_music(temp_voice, final_mp3)
    
    print("Updating RSS...")
    update_rss(final_mp3, script)
    print("Done!")
