import feedparser
import os
import asyncio
import edge_tts
from datetime import datetime
from podgen import Podcast, Episode, Media, Person, Category
from huggingface_hub import InferenceClient

# 1. SETUP
# -----------------------------
# Qwen is the best for Cantonese slang and humor.
REPO_ID = "Qwen/Qwen2.5-72B-Instruct" 
HF_TOKEN = os.environ.get("HF_TOKEN")

# MIXED SOURCES: HK Local + Global
FEEDS = [
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",      # HK News (RTHK)
    "https://www.hk01.com/rss",                                    # HK News (HK01)
    "https://feeds.bbci.co.uk/news/world/rss.xml",                 # Global (BBC)
    "https://www.theverge.com/rss/index.xml"                       # Tech/Global (The Verge - good for fun news)
]

# 2. FETCH NEWS
# -----------------------------
def get_news():
    full_text = ""
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            # Get top 2 items from each feed to keep it diverse but short
            for item in feed.entries[:2]:
                clean_desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:150]
                # Label the source so the AI knows where it came from
                source_name = "Global News" if "bbc" in url or "verge" in url else "HK News"
                full_text += f"[{source_name}] {item.title}: {clean_desc}\n"
        except Exception as e:
            print(f"Error reading feed {url}: {e}")
    return full_text

# 3. AI SCRIPT WRITING (FUNNY MODE)
# -----------------------------
def write_script(raw_news):
    client = InferenceClient(token=HF_TOKEN)
    
    # THE SECRET SAUCE: A highly specific "Persona" prompt
    prompt = f"""
    You are "Ah-Fa" (阿發), a witty, sarcastic, and energetic Hong Kong YouTuber/Podcaster.
    You are NOT a boring news anchor. You are chatting with friends.
    
    Instructions:
    1. **Language:** Use very colloquial Cantonese (Oral/Spoken). Use slang like "爆單嘢", "搞錯", "痴線", "食花生".
    2. **Tone:** High energy, slightly funny, maybe a little bit mean/sarcastic if the news is stupid. 
    3. **Content:** Summarize the news, but add your own 1-sentence reaction to each story.
    4. **Structure:**
       - Start: "喂各位早晨！又係我阿發講新聞時間。今日 {datetime.now().strftime('%m月%d日')}，睇下個世界發生咩事。"
       - Part 1: Talk about Hong Kong news first.
       - Part 2: "轉頭睇下國際新聞..." (Switch to Global/BBC news).
       - End: "好啦，講完收工！記得飲多杯水呀，拜拜！"
    5. **Format:** Pure text only. No emojis (TTS can't read them). No markdown.

    Here is the boring raw news (Spice it up!):
    {raw_news}
    """
    
    try:
        response = client.chat_completion(
            model=REPO_ID,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500, # Increased length for jokes
            temperature=0.85 # Higher temperature = More creativity/randomness
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Error: {e}")
        return "各位早晨，阿發今日個腦實左少少，讀住標題先啦。"

# 4. TEXT TO SPEECH (FASTER & ENERGETIC)
# -----------------------------
async def generate_audio(text, filename):
    # We use 'rate=+10%' to make it sound faster and less "droning"
    # zh-HK-HiuGaaiNeural is the most expressive voice.
    communicate = edge_tts.Communicate(text, "zh-HK-HiuGaaiNeural", rate="+10%")
    await communicate.save(filename)

# 5. GENERATE PODCAST FEED
# -----------------------------
def update_rss(audio_filename, episode_text):
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    if repo_name:
        base_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}"
    else:
        base_url = "http://localhost"

    p = Podcast(
        name="阿發講新聞 (Ah Fa Daily)", # Rebranded!
        description="Daily sarcastic news briefing in Cantonese.",
        website=base_url,
        explicit=False, # Set to True if you want it to swear!
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",
        authors=[Person("Ah Fa", "news@example.com")],
        owner=Person("Ah Fa", "news@example.com"),
        category=Category("Comedy", "News"), # Changed category to Comedy
    )
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    p.add_episode(Episode(
        title=f"阿發簡報: {today_str}",
        media=Media(f"{base_url}/{audio_filename}", 4000000, type="audio/mpeg"),
        summary=episode_text[:100] + "...",
        publication_date=datetime.now().astimezone(),
    ))
    
    p.rss_file('feed.xml')

# MAIN EXECUTION
if __name__ == "__main__":
    # Unique filename
    date_str = datetime.now().strftime('%Y%m%d')
    mp3_filename = f"brief_{date_str}.mp3"
    
    print("Fetching Global & HK news...")
    raw_news = get_news()
    
    print("Writing Witty Script...")
    script = write_script(raw_news)
    
    print(f"Generating Audio (Fast Mode)...")
    asyncio.run(generate_audio(script, mp3_filename))
    
    print("Updating RSS...")
    update_rss(mp3_filename, script)
    print("Done!")
