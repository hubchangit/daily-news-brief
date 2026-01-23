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
except:
    pass

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

# CUSTOM BGM URL
REPO_BGM_URL = "https://github.com/hubchangit/daily-news-brief/raw/main/bgm.mp3"

# 2. AUDIO ENGINE
# -----------------------------
async def generate_line(text, voice, filename):
    # FIXED: Both voices set to 1.2x speed (+20%)
    if voice == VOICE_FEMALE:
        rate = "+20%" 
        pitch = "+2Hz" # Girl slightly higher pitch for energy
    else:
        rate = "+20%"  # WanLung also faster
        pitch = "+0Hz"
        
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(filename)

async def generate_dialogue_audio(script_text, output_file):
    print("Generating Dialogue Audio...")
    
    # 1. Clean Script Artifacts
    clean_text = re.sub(r'\*\*|##', '', script_text)
    lines = clean_text.split("|")
    
    combined_audio = AudioSegment.empty()
    temp_files = []
    
    # Track the current speaker to prevent mix-ups on lines without tags
    current_voice = VOICE_FEMALE 

    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue
        
        # 2. STRICT REGEX SPEAKER DETECTION & REMOVAL
        # Checks for Name at the START (^) followed by colon (: or ：)
        
        # Check for Boy
        if re.match(r'^\s*(?:出木杉|Dekisugi)\s*[:：]', line):
            current_voice = VOICE_MALE
            # Remove the name tag using regex
            text = re.sub(r'^\s*(?:出木杉|Dekisugi)\s*[:：]\s*', '', line)
            
        # Check for Girl
        elif re.match(r'^\s*(?:電車少女|Girl|Tram Girl)\s*[:：]', line):
            current_voice = VOICE_FEMALE
            text = re.sub(r'^\s*(?:電車少女|Girl|Tram Girl)\s*[:：]\s*', '', line)
            
        else:
            # No name tag found? Keep using the CURRENT voice (don't switch)
            text = line
        
        # 3. Clean Content
        # Remove instructions like (laughs)
        text = re.sub(r'\(.*?\)', '', text).strip()
        # Remove weird symbols but keep punctuation
        text = re.sub(r'[^\w\s\u4e00-\u9fff,.?!，。？！a-zA-Z]', '', text)
        
        if len(text) < 1: continue

        temp_filename = f"temp_line_{i}.mp3"
        try:
            print(f"Speaking ({current_voice}): {text[:15]}...")
            await generate_line(text, current_voice, temp_filename)
            
            if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 0:
                segment = AudioSegment.from_mp3(temp_filename)
                combined_audio += segment
                
                # Smart Pause: Longer pause for long sentences
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
    
    # 1. Try Repo
    try:
        print(f"Attempting custom BGM from: {REPO_BGM_URL}")
        r = requests.get(REPO_BGM_URL)
        if r.status_code == 200:
            with open("bgm.mp3", "wb") as f:
                f.write(r.content)
            return True
    except: pass

    # 2. Fallback
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
        bgm = AudioSegment.from_mp3("bgm.mp3") 
        
        # FIXED: 30% Softer (-28dB is very subtle background)
        bgm = bgm - 28
        
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

# 4. CONTENT
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
        if count >= 5: break
        try:
            f = feedparser.parse(url)
            for item in f.entries:
                if count >= 5: break
                desc = getattr(item, 'summary', getattr(item, 'description', ''))
                desc = re.sub('<[^<]+?>', '', desc)[:150] 
                content += f"- {item.title} (Context: {desc})\n"
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
        res = client.chat_completion(model="Qwen/Qwen2.5-72B-Instruct", messages=msgs, max_tokens=1500)
        return res.choices[0].message.content.replace("\n", " ")
    except:
        return "出木杉: 系統故障。 | 電車少女: 聽日再見！"

def write_script(hk_news, global_news, weather):
    prompt = f"""
    You are writing a script for "電車少女 & 出木杉" (Hong Kong News Podcast).
    
    **Characters:**
    - "電車少女": Young, very energetic, uses heavy HK slang/particles (e.g. 勁, 癲, 唔係掛, 㗎, 喎, 啫).
    - "出木杉": Calm, intellectual, analytical.

    **Language:** Authentic Hong Kong Cantonese (廣東話口語).
    **Format:** One single line. Use "|" to separate speakers. No newlines.
    **Constraint:** Start every sentence with "Character Name:" (e.g. 出木杉: ...).

    **Content Requirements:**
    1. **Intro:** Quick energetic greeting.
    2. **Weather:** Brief update ({weather}).
    3. **News Segment (Select 3 distinct stories):**
       - Girl asks/comments on headline. Boy explains context. Girl reacts.
    4. **English Corner:** Teach one phrase related to the news.
    5. **Outro:** Bye.

    **Source Material:**
    HK News: {hk_news}
    Global News: {global_news}
    """
    return generate_script_robust(prompt)

def update_rss(audio_file, script):
    repo = os.environ.get("GITHUB_REPOSITORY", "local/test")
    base_url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}"
    
    p = Podcast(
        name="香港早晨",
        description="HK News Analysis (Powered by AI).",
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
    
    # Safety Check
    if "電車少女:" not in script and "出木杉:" not in script:
        script = f"電車少女: {script}"
    
    try:
        asyncio.run(generate_dialogue_audio(script, "dialogue_raw.mp3"))
        mix_music("dialogue_raw.mp3", final_mp3)
        update_rss(final_mp3, script)
        print("Done!")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        exit(1)
