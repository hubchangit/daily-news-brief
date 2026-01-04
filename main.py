import feedparser
import os
import asyncio
import edge_tts
from datetime import datetime
from podgen import Podcast, Episode, Media
from huggingface_hub import InferenceClient

# 1. SETUP
# -----------------------------
# We use the Mistral 7B model. It is fast, free, and good at summarization.
REPO_ID = "mistralai/Mistral-7B-Instruct-v0.3"
HF_TOKEN = os.environ.get("HF_TOKEN")

# RSS Feeds
FEEDS = [
    "https://rthk.hk/rthk/news/rss/e_expressnews_elocal.xml",       # HK News
    "https://feeds.bbci.co.uk/news/world/rss.xml"                   # Global News
]

# 2. FETCH NEWS
# -----------------------------
def get_news():
    full_text = ""
    for url in FEEDS:
        feed = feedparser.parse(url)
        # Get top 3 headlines from each feed to keep input short for the free API
        for item in feed.entries[:3]:
            # Clean up text slightly to save tokens
            clean_desc = item.description.replace('<br>', ' ').replace('\n', ' ')[:200]
            full_text += f"- {item.title}: {clean_desc}\n"
    return full_text

# 3. AI SCRIPT WRITING (Hugging Face)
# -----------------------------
def write_script(raw_news):
    client = InferenceClient(token=HF_TOKEN)
    
    prompt = f"""
    You are a professional news anchor for a podcast called "HK Daily Brief".
    Summarize the following news items into a short, smooth spoken script (approx 2-3 minutes).
    
    Rules:
    1. Group the news: Hong Kong news first, then Global news.
    2. Do NOT use markdown, asterisks, or bold text. plain text only.
    3. Start with: "Good morning. Here is your daily briefing for {datetime.now().strftime('%A, %B %d')}."
    4. End with: "That is the news for today. Have a good one."
    
    News Items:
    {raw_news}
    """
    
    # We use chat_completion for better instruction following
    try:
        response = client.chat_completion(
            model=REPO_ID,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error calling AI: {e}")
        # Fallback if AI fails: Just read the raw headlines
        return "Good morning. AI generation failed, but here are the headlines. " + raw_news

# 4. TEXT TO SPEECH (Edge TTS)
# -----------------------------
async def generate_audio(text, filename="episode.mp3"):
    # 'en-GB-SoniaNeural' is a British voice. 
    # Use 'en-US-AriaNeural' for American.
    communicate = edge_tts.Communicate(text, "en-GB-SoniaNeural")
    await communicate.save(filename)

# 5. GENERATE PODCAST FEED
# -----------------------------
def update_rss(audio_filename, episode_text):
    repo_name = os.environ.get("GITHUB_REPOSITORY") 
    # Construct the GitHub Pages URL
    if repo_name:
        base_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}"
    else:
        base_url = "http://localhost" # For local testing

    p = Podcast(
        name="HK Daily Brief",
        description="Daily AI-generated news for Hong Kong.",
        website=base_url,
        explicit=False,
    )
    
    p.add_episode(Episode(
        title=f"News Briefing: {datetime.now().strftime('%Y-%m-%d')}",
        media=Media(f"{base_url}/{audio_filename}", 4000000), 
        summary=episode_text[:200] + "...",
        publication_date=datetime.now().astimezone(),
    ))
    
    p.rss_file('feed.xml')

# MAIN EXECUTION
# -----------------------------
if __name__ == "__main__":
    print("Fetching news...")
    raw_news = get_news()
    
    print("Writing script with AI (Hugging Face)...")
    script = write_script(raw_news)
    print("--- SCRIPT START ---")
    print(script) 
    print("--- SCRIPT END ---")
    
    print("Generating audio...")
    asyncio.run(generate_audio(script, "daily_brief.mp3"))
    
    print("Updating RSS feed...")
    update_rss("daily_brief.mp3", script)
    print("Done!")
