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

FEEDS = [
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",      # HK News
    "https://feeds.bbci.co.uk/news/world/rss.xml",                 # Global
    "https://www.theverge.com/rss/index.xml"                       # Tech
]

# 2. FETCH NEWS
# -----------------------------
def get_news():
    full_text = ""
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            # Take top 5 items for the Long Form podcast
            for item in feed.entries[:5]:
                clean_desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:250]
                source = "Global News (English)" if "bbc" in url or "verge" in url else "HK News"
                full_text += f"[{source}] {item.title}: {clean_desc}\n"
        except Exception as e:
            print(f"Error reading feed {url}: {e}")
    return full_text

# 3. HELPER: CLEAN TEXT & FIX DATE
# -----------------------------
def clean_script_for_speech(text):
    # 1. Remove Markdown symbols (*, #, _, ~, `)
    # This turns "### Headline" into "Headline" and "**Bold**" into "Bold"
    text = re.sub(r'[*#_`~]', '', text)
    
    # 2. Remove any remaining markdown links [Link](url) -> Link
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    
    # 3. Collapse multiple spaces/newlines
    text = re.sub(r'\n+', '\n', text).strip()
    
    return text

def get_natural_date():
    # Returns "1月5日" instead of "01月05日" (No leading zeros)
    now = datetime.now()
    return f"{now.month}月{now.day}日"

# 4. AI SCRIPT WRITING
# -----------------------------
def write_script(raw_news):
    client = InferenceClient(token=HF_TOKEN)
    natural_date = get_natural_date()
    
    prompt = f"""
    You are "Tram Girl" (電車少女), a friendly HK podcaster.
    
    **Goal:** Write a **5-7 minute** deep-dive news script in Cantonese.
    
    **CRITICAL RULES:**
    1. **NO MARKDOWN:** Do not use headers (###), bold (**), or bullet points (-). Write only plain paragraphs.
    2. **Language:** FULL Cantonese (Colloquial/Spoken).
    3. **Date:** Read the date naturally as "{natural_date}".
    4. **Flow:** Casual storytelling. Connect the stories smoothly.
    
    **Structure:**
    - Intro: "哈囉大家好，今日係 {natural_date}..."
    - HK News Deep Dive
    - Global News Deep Dive (Translated to Cantonese)
    - Outro

    **Raw News:**
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

# 5. TEXT TO SPEECH (1.5x SPEED)
# -----------------------------
async def generate_audio(text, filename):
    # We run a final clean just in case
    clean_text = clean_script_for_speech(text)
    
    communicate = edge_tts.Communicate(clean_text, "zh-HK-HiuGaaiNeural", rate="+50%") 
    await communicate.save(filename)

# 6. GENERATE PODCAST FEED
# -----------------------------
def update_rss(audio_filename, episode_text):
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    if repo_name:
        base_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}"
    else:
        base_url = "http://localhost"

    p = Podcast(
        name="電車少女 (Tram Girl)",
        description="A daily, relaxing news deep dive in Cantonese. (Global & Local)",
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
    
    print("Fetching News...")
    raw_news = get_news()
    
    print("Writing Script (No Markdown)...")
    script = write_script(raw_news)
    
    # Double check cleaning before printing/generating
    final_script = clean_script_for_speech(script)
    
    print(f"Generating Audio (1.5x)...")
    asyncio.run(generate_audio(final_script, mp3_filename))
    
    print("Updating RSS...")
    update_rss(mp3_filename, final_script)
    print("Done!")
