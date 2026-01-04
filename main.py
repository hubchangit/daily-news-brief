import feedparser
import os
import asyncio
import edge_tts
import re
from datetime import datetime
from podgen import Podcast, Episode, Media, Person, Category
from huggingface_hub import InferenceClient

# 1. SETUP
# -----------------------------
REPO_ID = "Qwen/Qwen2.5-72B-Instruct" 
HF_TOKEN = os.environ.get("HF_TOKEN")

# NEWS SOURCES (Updated)
FEEDS = [
    # HK Local
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",      # RTHK (Chinese)
    "https://www.scmp.com/rss/2/feed",                             # SCMP (HK/English)
    
    # Global
    "https://feeds.bbci.co.uk/news/world/rss.xml",                 # BBC World
    "https://www.theguardian.com/world/rss"                        # The Guardian
]

# WEATHER SOURCE (HK Observatory)
WEATHER_URL = "https://rss.weather.gov.hk/rss/LocalWeatherForecast_uc.xml"

# 2. FETCH WEATHER
# -----------------------------
def get_weather():
    try:
        feed = feedparser.parse(WEATHER_URL)
        # HKO RSS usually puts the forecast in the description of the first item
        if feed.entries:
            # Clean up the HTML tags (HKO includes <br> often)
            raw_weather = feed.entries[0].description
            clean_weather = raw_weather.replace('<br/>', ' ').replace('\n', ' ')
            return clean_weather[:300] # Keep it concise
    except Exception as e:
        print(f"Error fetching weather: {e}")
    return "Weather data unavailable."

# 3. FETCH NEWS
# -----------------------------
def get_news():
    full_text = ""
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            # Take top 3 items from each source (3x4 = ~12 stories total)
            for item in feed.entries[:3]:
                clean_desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:250]
                
                # Tag the source clearly for the AI
                if "scmp" in url or "rthk" in url:
                    source_tag = "HK News"
                else:
                    source_tag = "Global News"
                
                full_text += f"[{source_tag} - {feed.feed.title}] {item.title}: {clean_desc}\n"
        except Exception as e:
            print(f"Error reading feed {url}: {e}")
    return full_text

# 4. HELPER: CLEAN TEXT & FIX DATE
# -----------------------------
def clean_script_for_speech(text):
    # Remove Markdown (*, #, _, ~)
    text = re.sub(r'[*#_`~]', '', text)
    # Remove links
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Collapse spaces
    text = re.sub(r'\n+', '\n', text).strip()
    return text

def get_natural_date():
    # Returns "1月5日" (One Month Five Day)
    now = datetime.now()
    return f"{now.month}月{now.day}日"

# 5. AI SCRIPT WRITING
# -----------------------------
def write_script(raw_news, weather_report):
    client = InferenceClient(token=HF_TOKEN)
    natural_date = get_natural_date()
    
    prompt = f"""
    You are "Tram Girl" (電車少女), a friendly HK podcaster.
    
    **Goal:** Write a **5-7 minute** deep-dive news script in Cantonese.
    
    **CRITICAL RULES:**
    1. **NO MARKDOWN:** No bold (**), no headers (###). Pure text only.
    2. **Language:** FULL Cantonese (Colloquial). Hong Kong spoken language. Translate ALL English news (Guardian/BBC/SCMP) into natural Cantonese.
    3. **Date:** Read as "{natural_date}".
    
    **Structure:**
    1. **Intro:** "哈囉大家好，今日係 {natural_date}..."
    2. **Weather Report:** Use this real data: "{weather_report}". (Summarize it: e.g., " ，上午較爲清涼，氣溫為xx度至xx度。有/沒有需要帶雨傘")
    3. **HK News Deep Dive:** Discuss the RTHK and SCMP stories.
    4. **Global News Deep Dive:** Discuss the BBC and Guardian stories.
    5. **Outro:** "今日嘅新聞係咁多，我地聼日見！"
    
    **Raw News Data:**
    {raw_news}
    """
    
    try:
        response = client.chat_completion(
            model=REPO_ID,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3500, 
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Error: {e}")
        return "Sorry, AI generation failed."

# 6. TEXT TO SPEECH (1.5x SPEED)
# -----------------------------
async def generate_audio(text, filename):
    clean_text = clean_script_for_speech(text)
    # Speed increased to +50%
    communicate = edge_tts.Communicate(clean_text, "zh-HK-HiuGaaiNeural", rate="+50%") 
    await communicate.save(filename)

# 7. GENERATE PODCAST FEED
# -----------------------------
def update_rss(audio_filename, episode_text):
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    if repo_name:
        base_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}"
    else:
        base_url = "http://localhost"

    p = Podcast(
        name="電車少女 (Tram Girl)",
        description="Daily HK & Global news deep dive with weather updates.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Tram Girl", "news@example.com")],
        owner=Person("Tram Girl", "news@example.com"),
        category=Category("News", "Daily News"),
    )
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    p.add_episode(Episode(
        title=f"電車日記: {today_str}",
        media=Media(f"{base_url}/{audio_filename}", 9000000, type="audio/mpeg"),
        summary=episode_text[:150] + "...",
        publication_date=datetime.now().astimezone(),
    ))
    
    p.rss_file('feed.xml')

# MAIN EXECUTION
if __name__ == "__main__":
    date_str = datetime.now().strftime('%Y%m%d')
    mp3_filename = f"brief_{date_str}.mp3"
    
    print("Fetching HKO Weather...")
    weather = get_weather()
    print(f"Weather: {weather[:50]}...") # Print first 50 chars to check
    
    print("Fetching Global & HK News...")
    raw_news = get_news()
    
    print("Writing Script (Tram Girl)...")
    script = write_script(raw_news, weather)
    
    # Final cleanup before audio
    final_script = clean_script_for_speech(script)
    
    print(f"Generating Audio (1.5x)...")
    asyncio.run(generate_audio(final_script, mp3_filename))
    
    print("Updating RSS...")
    update_rss(mp3_filename, final_script)
    print("Done!")
