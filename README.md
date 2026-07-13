# 🌟 Trade-whisper-cloud

A lightweight, serverless, and cloud-optimized multi-stream trade detector designed to run 24/7 on free-tier hosting platforms (such as Render.com or Fly.io). 

This project is a port of the local trade detector, replacing PyTorch, CUDA, and local 1.6GB Whisper models with the ultra-fast **Groq Whisper API** and utilizing **Gemini AI** (`gemini-3.1-flash-lite`) to classify real-time audio transcripts into structured trade cards.

🔗 **Live URL**: [https://trade-whisper-cloud.onrender.com/](https://trade-whisper-cloud.onrender.com/)

---

## ✨ Features

* 🔋 **Ultra-Lightweight (< 30MB RAM)**: Complete removal of local deep learning frameworks (PyTorch/CUDA). Fits easily within any free-tier RAM budget.
* ⚡ **Direct Stream Audio Slicing**: Uses `ffmpeg` to download and slice 30-second audio blocks directly from live or static stream URLs in 2-3 seconds, consuming minimal CPU and bandwidth.
* 🎙️ **Groq Whisper API**: Leverages the high-speed `whisper-large-v3-turbo` model for near-instant transcription.
* 🧠 **Gemini AI Trade Detection**: Analyzes rolling transcript windows to classify asset calls, directions (BUY/SELL), entry targets, stop losses, and reasoning using structured schemas.
* 📱 **Mobile-Responsive glassmorphic UI**:
  * Segmented Mobile Nav Controller to easily toggle between **Monitor Streams** and **Trade Signals**.
  * Auto-stacked inputs and touch-friendly control configurations.
  * Real-time notification counters on mobile tabs.
  * Synthesized browser voice alerts (Web Audio API) for instant trade announcements.
* 🚨 **Telegram Notifications**: Asynchronously forwards trade cards to your Telegram Bot.

---

## 📂 Project Structure

```
├── app.py                  # FastAPI Backend (Slicing loops, Groq, Gemini & WS Manager)
├── templates/
│   └── index.html          # Dark-mode glassmorphic responsive UI dashboard
├── requirements.txt        # Lightweight dependencies list (FastAPI, google-genai, etc.)
├── Dockerfile              # Deployment config (Pre-installs Python, ffmpeg, & dependencies)
├── .gitignore              # Ignores venv, temp .mp3 files, and .env credentials
└── README.md               # Documentation
```

---

## ⚙️ Environment Configuration

Create a `.env` file in the root directory for local testing:

```env
GEMINI_API_KEY="your_gemini_api_key"
TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
TELEGRAM_CHAT_ID="your_telegram_chat_id"
GROQ_API_KEY="your_groq_api_key"
```

---

## 🚀 Getting Started

### 1. Local Run
1. Clone the repository:
   ```bash
   git clone https://github.com/sohan565/trade-whisper-cloud.git
   cd trade-whisper-cloud
   ```
2. Set up a virtual environment and install packages:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate       # On Windows
   source venv/bin/activate     # On macOS/Linux
   pip install -r requirements.txt
   ```
3. Run the server:
   ```bash
   python app.py
   ```
4. Open your browser and navigate to `http://localhost:8000`.

---

### 2. Cloud Deployment (Render.com)

Render automatically compiles the Docker container containing our backend and the `ffmpeg` binary dependencies.

1. Create a new **Web Service** on Render and link your Git repository.
2. Select **Docker** as the environment runtime.
3. Select **Singapore** (or your closest region) and choose the **Free Tier**.
4. Click **Advanced** -> **Add Environment Variable** and enter your credentials:
   * `GROQ_API_KEY`
   * `GEMINI_API_KEY` (Optional, enables Gemini analysis)
   * `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID` (Optional, enables Telegram bot)
5. Click **Deploy Web Service**.

---

### 😴 How to prevent Render from going to sleep (24/7 Run)

Render's free instances automatically spin down (go to sleep) if they do not receive HTTP traffic for 15 minutes. 

To keep your streams monitoring continuously 24/7:
1. Register for a free account at [UptimeRobot.com](https://uptimerobot.com/) or [cron-job.org](https://cron-job.org/).
2. Create a new monitor with **HTTP(s)** type.
3. Point it to your Render web app link: `https://trade-whisper-cloud.onrender.com/`
4. Set the ping interval to **5 minutes**.

This sends a lightweight ping request every 5 minutes, keeping your server awake indefinitely!

---

## 🛡️ License

Distributed under the MIT License. See `LICENSE` for more information.
