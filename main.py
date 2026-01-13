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

# 2. AUDIO ENGINE
# -----------------------------
async def generate_line(text, voice, filename):
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
        
        # STRICT NAME MATCHING
        if "出木杉:" in line or "Dekisugi:" in line:
            voice = VOICE_MALE
            text = line.replace("出木杉:", "").replace("Dekisugi:", "").strip()
        elif "電車少女:" in line or "Girl:" in line:
            voice = VOICE_FEMALE
            text = line.replace("電車少女:", "").replace("Girl:", "").strip()
        else:
            # Fallback: If no name found, assume it's a continuation of previous or default to Girl
            voice = VOICE_FEMALE 
            text = line.strip()
        
        # Cleanup: Remove asterisks and weird symbols, keep punctuation
        text = re.sub(r'[^\w\s\u4e00-\u9fff,.?!，。？！a-zA-Z]', '', text)
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

# 4. ROBUST AI BRAIN (Google -> Fallback to HF)
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

def generate_script_robust(prompt):
    # --- PHASE 1: GOOGLE GEMINI ---
    gemini_models = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-pro"]
    
    for m in gemini_models:
        try:
            print(f"🤖 Attempting Google Model: {m}...")
            model = genai.GenerativeModel(m)
            response = model.generate_content(prompt)
            text = response.text.replace("\n", " ").replace("**", "")
            
            # Credit Google
            return text + " | 電車少女: 本節目由 Google Gemini 支援製作。"
            
        except Exception as e:
            print(f"⚠️ Google {m} failed: {e}")
            continue

    # --- PHASE 2: HUGGING FACE FALLBACK ---
    print("🚨 Google Gemini completely failed. Switching to Hugging Face Backup...")
    try:
        hf_token = os.environ.get("HF_TOKEN")
        if not hf_token:
            print("❌ No HF_TOKEN found in secrets.")
            raise Exception("No HF_TOKEN")

        client = InferenceClient(api_key=hf_token)
        
        # Using Qwen 2.5-72B (Great Chinese performance)
        messages = [{"role": "user", "content": prompt}]
        response = client.chat_completion(
            model="Qwen/Qwen2.5-72B-Instruct", 
            messages=messages, 
            max_tokens=1000
        )
        
        text = response.choices[0].message.content.replace("\n", " ").replace("**", "")
        
        # Credit Hugging Face
        return text + " | 電車少女: 本節目由 Hugging Face Qwen 支援製作。"
        
    except Exception as e:
        print(f"❌ Hugging Face failed: {e}")

    # --- PHASE 3: TOTAL FAILURE ---
    return "電車少女: 今日系統發生嚴重故障。 | 出木杉: 我地聽日再嘗試啦。"

def write_script(hk_news, global_news, weather):
    prompt = f"""
    You are writing a script for "電車少女 & 出木杉" (Hong Kong News Podcast).
    
    **Characters:**
    - "電車少女": Energetic, uses Hong Kong slang.
    - "出木杉": Calm, analytical, intellectual.

    **Language:** Authentic Hong Kong Cantonese (廣東話口語).
    **Format:** One single line. Use "|" to separate speakers. No newlines.
    **Constraint:** Start every sentence with the character name followed by a colon (e.g., 電車少女: ...).

    **Content Structure:**
    1. Intro: 電車少女 & 出木杉 greet listeners.
    2. Weather: {weather}
    3. HK News: {hk_news} (出木杉 analyzes).
    4. Global News: {global_news} (Brief mention).
    5. **English Corner**: Teach one useful English idiom or phrase related to today's news. Explain it in Cantonese.
    6. Outro: Goodbye.

    **Example Output:**
    電車少女: 早晨！今日天氣點呀？ | 出木杉: 今日有雨，記得帶遮啦。 | 電車少女: 咁今日有咩新聞？ | 出木杉: 今日焦點係... | 電車少女: 係時候學英文啦！ | 出木杉: 今日嘅英文係 "Rain check"，即係改期咁解。
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
    
    # Safety Check: Ensure the script starts with a character name
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
