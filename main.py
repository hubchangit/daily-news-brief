import feedparser
import os
import asyncio
import edge_tts
from datetime import datetime
from podgen import Podcast, Episode, Media, Person, Category
from huggingface_hub import InferenceClient

# 1. SETUP
# -----------------------------
# We use a model that handles Chinese well. 
# "Qwen" is excellent for Chinese/Cantonese, but if it fails on the free tier,
# Mistral (v0.3) is a solid backup. Let's try Qwen first for better Cantonese.
REPO_ID = "Qwen/Qwen2.5-72B-Instruct" 
# If Qwen gives errors, change REPO_ID back to: "mistralai/Mistral-7B-Instruct-v0.3"

HF_TOKEN = os.environ.get("HF_TOKEN")

FEEDS = [
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",      # RTHK (Chinese)
    "https://www.hk01.com/rss"                                     # HK01 (Good for variety)
]

# 2. FETCH NEWS
# -----------------------------
def get_news():
    full_text = ""
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            # Grab top 3 items
            for item in feed.entries[:3]:
                # Clean up text
                clean_desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:150]
                full_text += f"- {item.title}: {clean_desc}\n"
        except Exception as e:
            print(f"Error reading feed {url}: {e}")
    return full_text

# 3. AI SCRIPT WRITING (CANTONESE)
# -----------------------------
def write_script(raw_news):
    client = InferenceClient(token=HF_TOKEN)
    
    # Updated Prompt for Cantonese
    prompt = f"""
    You are a professional Hong Kong news anchor. 
    Summarize the following news headlines into a smooth, spoken Cantonese broadcast script (Traditional Chinese).
    
    Guidelines:
    1. Language: Cantonese (Written as spoken text, e.g., using "嘅", "係", "今日").
    2. Tone: Professional, clear, and concise.
    3. Structure: 
       - Start with: "各位早晨，今日係 {datetime.now().strftime('%m月%d日')}，以下係今日嘅新聞重點。"
       - Group Hong Kong news first, then other news.
       - End with: "新聞報道完畢，祝大家有美好嘅一日。"
    4. NO Markdown, NO asterisks (*), NO bold text. Just pure text.

    News Items:
    {raw_news}
    """
    
    try:
        response = client.chat_completion(
            model=REPO_ID,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Error: {e}")
        # Fallback in Cantonese if AI fails
        return "各位早晨，AI 生成發生錯誤，請直接查看標題。"

# 4. TEXT TO SPEECH (HK VOICE)
# -----------------------------
async def generate_audio(text, filename="episode.mp3"):
    # "zh-HK-HiuGaaiNeural" is a cheerful, clear female HK voice.
    # "zh-HK-WanLungNeural" is a calm male HK voice.
    communicate = edge_tts.Communicate(text, "zh-HK-HiuGaaiNeural")
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
        name="香港每日新聞 (HK Daily)",
        description="Daily AI-generated news briefing in Cantonese.",
        website=base_url,
        explicit=False,
        image="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/World_News_icon.png/600px-World_News_icon.png",
        language="zh-hk",  # Changed to Chinese-HK
        authors=[Person("AI News Bot", "news@example.com")],
        owner=Person("My News Bot", "news@example.com"),
        category=Category("News", "Daily News"),
    )
    
    p.add_episode(Episode(
        title=f"新聞簡報: {datetime.now().strftime('%Y-%m-%d')}",
        media=Media(f"{base_url}/{audio_filename}", 4000000, type="audio/mpeg"),
        summary=episode_text[:100] + "...",
        publication_date=datetime.now().astimezone(),
    ))
    
    p.rss_file('feed.xml')

# MAIN EXECUTION
if __name__ == "__main__":
    print("Fetching Chinese news...")
    raw_news = get_news()
    
    print("Writing Cantonese script...")
    script = write_script(raw_news)
    print(script) # Debug print
    
    print("Generating HK audio...")
    asyncio.run(generate_audio(script, "daily_brief.mp3"))
    
    print("Updating RSS...")
    update_rss("daily_brief.mp3", script)
    print("Done!")
