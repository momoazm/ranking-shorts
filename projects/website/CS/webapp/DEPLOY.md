# Deploying CS Chat to Hugging Face Spaces (free, always-on)

This puts the app on a public `https://…hf.space` URL that works from your phone on
any network and stays up when your laptop is off. Your laptop is only used to test
and push — the running app lives on Hugging Face's servers.

## What you need
- A Hugging Face account (free): https://huggingface.co/join
- Your two API keys: `GEMINI_API_KEY` and `PINECONE_API_KEY`.

---

## Option A — Web UI (no git, easiest)

1. Go to https://huggingface.co/new-space.
2. **Space name:** e.g. `cs-chat`. **SDK:** choose **Gradio**. **Hardware:** `CPU basic`
   (free). Visibility: **Private** if you don't want strangers using it. Create.
3. Open the Space → **Files** tab → **Add file → Upload files**. Upload these four
   files from `CS/webapp/`:
   - `app.py`
   - `requirements.txt`
   - `README.md`
   - `.gitignore`
   (Do **not** upload any `.env` — keys go in secrets, below.)
4. Go to **Settings → Variables and secrets → New secret** and add:
   | Name | Value |
   | --- | --- |
   | `GEMINI_API_KEY` | *(your Gemini key)* |
   | `PINECONE_API_KEY` | *(your Pinecone key)* |
   | `PINECONE_INDEX` | `media-memory` |
5. The Space rebuilds automatically. When it says **Running**, open the app URL
   (e.g. `https://<your-username>-cs-chat.hf.space`) on your phone. Bookmark it /
   add to home screen.

---

## Option B — git push (if you prefer the terminal)

```bash
# 1. Create the Space on the website first (step A.1–A.2 above), then:
cd "CS/webapp"
git init
git remote add space https://huggingface.co/spaces/<your-username>/cs-chat
git add app.py requirements.txt README.md .gitignore
git commit -m "CS Chat RAG app"
git push space main        # use your HF username + an access token as the password
```
Then add the secrets as in step A.4. (An HF write token: https://huggingface.co/settings/tokens)

---

## Using it
- **Add data** tab: upload files or paste text → **Ingest**. This writes into the same
  Pinecone `media-memory` index your `CS/` tools use — data added here is searchable
  from the CLI too, and vice versa.
- **Chat** tab: ask questions; answers are grounded in what's been ingested, with a
  *Sources* line.

## Notes
- The index and its 3072 dimension already exist; the app just reads/writes it.
- Free Spaces may take a few seconds to wake after long idle — the URL stays valid.
- To lock it down, make the Space **Private** (only you, logged in, can open it).
- If Google ever renames the chat model, add a `GEMINI_CHAT_MODEL` secret to override
  the `gemini-2.5-flash` default — no code change needed.
