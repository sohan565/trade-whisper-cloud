import os
import sys
import time
import asyncio
import subprocess
import json
import requests
from typing import Dict, List, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import uvicorn

# Force standard output and error to use UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Load local .env file if it exists
env_path = os.path.join(os.path.dirname(__file__), ".env") if "__file__" in locals() else ".env"
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

# Check Gemini API Key
api_key = os.environ.get("GEMINI_API_KEY")
has_gemini = bool(api_key)
gemini_client = None

if has_gemini:
    try:
        from google import genai
        from google.genai import types
        from pydantic import BaseModel, Field
        gemini_client = genai.Client()
        print("Gemini API Client initialized successfully.")
        
        # Define Pydantic schema for structured trade signals
        class TradeAlert(BaseModel):
            trade_detected: bool = Field(description="True if a specific trade entry is recommended or announced, False otherwise")
            asset: str = Field(description="Name of the asset, e.g. BTC, ETH, AAPL, NIFTY")
            direction: str = Field(description="BUY or SELL")
            entry_price: str = Field(description="Entry price or price range mentioned")
            target_price: str = Field(description="Target price or take profit level, if mentioned")
            stop_loss: str = Field(description="Stop loss level, if mentioned")
            confidence: str = Field(description="HIGH, MEDIUM, or LOW")
            reasoning: str = Field(description="Brief explanation of the trade context or quotes from the speaker")
            
    except Exception as e:
        print(f"Warning: Failed to initialize Gemini SDK or Pydantic models: {e}")
        has_gemini = False
else:
    print("\n" + "="*80)
    print("WARNING: GEMINI_API_KEY environment variable is not set.")
    print("Trade detection will run in Mock Demo Mode (auto-detecting phrases like 'Buy BTC').")
    print("To enable full Gemini AI trade analysis, set the GEMINI_API_KEY environment variable.")
    print("="*80 + "\n")

# Slot State Definition
class SlotState:
    def __init__(self, slot_id: int):
        self.slot_id = slot_id
        self.active = False
        self.url = ""
        self.direct_audio_url = ""
        self.title = ""
        self.status = "Inactive"  # Inactive, Connecting, Transcribing, Error
        
        self.offset_seconds = 0.0
        self.is_live = False
        self.gemini_text_buffer = []  # Subtitles accumulated
        self.history_text = ""        # Rolling transcript history for context
        self.task = None              # asyncio task for transcription loop

# Initialize 5 Slots
slots: List[SlotState] = [SlotState(i) for i in range(5)]
slots_lock = asyncio.Lock()

# FastAPI Setup
app = FastAPI(title="Gemini Multi-Stream Trade Detector (Cloud)")
templates = Jinja2Templates(directory="templates")
active_connections: Set[WebSocket] = set()

# Helper Functions
def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    if milliseconds >= 1000:
        milliseconds = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"

def get_video_info(url: str):
    is_live = False
    title = "YouTube Feed"
    
    # Safe is_live check
    cmd_live = ['yt-dlp', '--no-cache-dir', '--print', '%(is_live)s', '--no-warnings', url]
    try:
        res = subprocess.run(cmd_live, capture_output=True, text=True, encoding='utf-8')
        output = res.stdout.strip().lower()
        is_live = any(x in output for x in ('true', 'yes', '1', 'live'))
    except Exception as e:
        print(f"Warning: failed to fetch is_live status for {url}: {e}")
        
    # Safe title check
    cmd_title = ['yt-dlp', '--no-cache-dir', '--print', '%(title)s', '--no-warnings', url]
    try:
        res = subprocess.run(cmd_title, capture_output=True, text=True, encoding='utf-8')
        title_out = res.stdout.strip()
        clean_lines = [line.strip() for line in title_out.split('\n') if 'warning' not in line.lower() and line.strip()]
        if clean_lines:
            title = clean_lines[-1]
    except Exception as e:
        print(f"Warning: failed to fetch title for {url}: {e}")
        
    return is_live, title

def get_direct_audio_url(url: str) -> str:
    cmd = ['yt-dlp', '--no-cache-dir', '-g', '-f', 'bestaudio', url]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if res.returncode == 0 and res.stdout.strip():
            out = res.stdout.strip().split('\n')
            return out[-1]
    except Exception:
        pass

    # Fallback to default format if bestaudio is not available (e.g. YouTube live streams without JS runtime)
    cmd_fallback = ['yt-dlp', '--no-cache-dir', '-g', url]
    try:
        res = subprocess.run(cmd_fallback, capture_output=True, text=True, encoding='utf-8')
        if res.returncode == 0 and res.stdout.strip():
            out = res.stdout.strip().split('\n')
            return out[-1]
    except Exception as e:
        print(f"Error getting fallback direct URL: {e}")
        
    return ""

def send_telegram_sync(token: str, chat_id: str, text: str):
    import urllib.request
    import urllib.parse
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    data = urllib.parse.urlencode(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            response.read()
            return True
    except Exception as e:
        print(f"Error sending Telegram notification with Markdown: {e}")
        # Fallback to plain text if Markdown format fails
        payload.pop("parse_mode", None)
        data = urllib.parse.urlencode(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                response.read()
                return True
        except Exception as e2:
            print(f"Error sending raw Telegram notification: {e2}")
            return False

async def send_telegram_alert(stream_title: str, asset: str, direction: str, entry_price: str, target_price: str, stop_loss: str, confidence: str, reasoning: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
        
    emoji = "🟢 LONG / BUY" if direction.upper() in ("BUY", "LONG") else "🔴 SHORT / SELL"
    text = (
        f"🚨 *NEW TRADE DETECTED* 🚨\n\n"
        f"📺 *Stream*: {stream_title}\n"
        f"💰 *Asset*: **{asset}**\n"
        f"📈 *Direction*: **{emoji}**\n\n"
        f"🎯 *Entry*: `{entry_price}`\n"
        f"🚀 *Target (TP)*: `{target_price}`\n"
        f"🛡️ *Stop Loss (SL)*: `{stop_loss}`\n\n"
        f"🔥 *Confidence*: {confidence}\n"
        f"🧠 *Reasoning*: _{reasoning}_"
    )
    
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, send_telegram_sync, token, chat_id, text)

# Broadcast helper for WebSockets
async def broadcast_message(message: dict):
    if not active_connections:
        return
    dead_connections = set()
    payload = json.dumps(message)
    for conn in active_connections:
        try:
            await conn.send_text(payload)
        except Exception:
            dead_connections.add(conn)
            
    for conn in dead_connections:
        active_connections.remove(conn)

# Get current slot status payload
def get_status_payload():
    payload = {
        "type": "streams_status",
        "slots": []
    }
    for slot in slots:
        payload["slots"].append({
            "slot_id": slot.slot_id,
            "active": slot.active,
            "url": slot.url,
            "title": slot.title,
            "status": slot.status
        })
    return payload

def run_ffmpeg(cmd: list) -> bool:
    try:
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        if res.returncode == 0:
            return True
        else:
            print(f"ffmpeg returned non-zero code {res.returncode}. Error: {res.stderr}")
            return False
    except Exception as e:
        print(f"ffmpeg execution error: {e}")
        return False

def call_groq_whisper(file_path: str) -> str:
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        print("Warning: GROQ_API_KEY environment variable is not set. Using mock translation.")
        # Simulating transcription for testing if key is absent
        return "[Groq Whisper API Key is missing. Please set GROQ_API_KEY]"
        
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {groq_api_key}"
    }
    try:
        with open(file_path, "rb") as f:
            files = {
                "file": (os.path.basename(file_path), f, "audio/mpeg")
            }
            data = {
                "model": "whisper-large-v3-turbo"
            }
            response = requests.post(url, headers=headers, files=files, data=data, timeout=30)
            
        if response.status_code == 200:
            return response.json().get("text", "")
        else:
            print(f"Groq API error {response.status_code}: {response.text}")
            return f"[Error transcribing via Groq: HTTP {response.status_code}]"
    except Exception as e:
        print(f"Exception calling Groq API: {e}")
        return f"[Error transcribing via Groq: {str(e)}]"

async def run_gemini_analysis(slot: SlotState, new_text: str):
    import re
    
    # Append the new transcribed text to the context history
    slot.history_text += " " + new_text
    
    # Keep history manageable (last 300 words)
    words = slot.history_text.split()
    if len(words) > 300:
        slot.history_text = " ".join(words[-300:])
        
    text_to_analyze = slot.history_text.strip()
    if not text_to_analyze:
        return
        
    # Show indicator on UI
    await broadcast_message({
        "type": "gemini_status",
        "slot_id": slot.slot_id,
        "active": True
    })
    
    if has_gemini and gemini_client:
        loop = asyncio.get_running_loop()
        try:
            prompt = (
                "You are an automated trading signal extractor. Analyze the provided transcript from a live trading video.\n"
                "Determine if the speaker is recommending a trade entry (Buy/Long or Sell/Short) for a specific asset.\n"
                "Only return trade_detected=true if the speaker is giving a specific trade call (Buy/Sell) with entry price, target price, or stop loss.\n"
                "If it is general market discussion, set trade_detected=false.\n\n"
                f"Transcript:\n{text_to_analyze}"
            )
            
            # Broadcast prompt before calling Gemini
            await broadcast_message({
                "type": "gemini_debug",
                "slot_id": slot.slot_id,
                "prompt": prompt,
                "response": "Waiting for Gemini API response..."
            })
            
            response = await loop.run_in_executor(None, lambda: gemini_client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=TradeAlert,
                ),
            ))
            
            # Broadcast response on success
            await broadcast_message({
                "type": "gemini_debug",
                "slot_id": slot.slot_id,
                "prompt": prompt,
                "response": response.text
            })
            
            data = json.loads(response.text)
            if data.get("trade_detected"):
                await broadcast_message({
                    "type": "trade_alert",
                    "slot_id": slot.slot_id,
                    "stream_title": slot.title,
                    "asset": data.get("asset"),
                    "direction": data.get("direction"),
                    "entry_price": data.get("entry_price"),
                    "target_price": data.get("target_price"),
                    "stop_loss": data.get("stop_loss"),
                    "confidence": data.get("confidence"),
                    "reasoning": data.get("reasoning")
                })
                # Trigger Telegram notification
                asyncio.create_task(send_telegram_alert(
                    stream_title=slot.title,
                    asset=data.get("asset"),
                    direction=data.get("direction"),
                    entry_price=data.get("entry_price"),
                    target_price=data.get("target_price"),
                    stop_loss=data.get("stop_loss"),
                    confidence=data.get("confidence"),
                    reasoning=data.get("reasoning")
                ))
        except Exception as ge:
            print(f"Gemini API Execution Error for slot {slot.slot_id}: {ge}")
            await broadcast_message({
                "type": "gemini_debug",
                "slot_id": slot.slot_id,
                "prompt": text_to_analyze,
                "response": f"Gemini API Error: {ge}"
            })
    else:
        # Fallback Mock / Regex mode (For testing without Gemini API Key)
        lower_text = text_to_analyze.lower()
        buy_match = re.search(r'\b(buy|long|entry)\s+([a-z0-9]+)', lower_text)
        sell_match = re.search(r'\b(sell|short)\s+([a-z0-9]+)', lower_text)
        
        if buy_match or sell_match:
            direction = "BUY" if buy_match else "SELL"
            match = buy_match if buy_match else sell_match
            asset = match.group(2).upper()
            
            target_match = re.search(r'(target|tp|take profit|goal)\s+([0-9a-z\.\$]+)', lower_text)
            sl_match = re.search(r'(stop loss|sl|stop)\s+([0-9a-z\.\$]+)', lower_text)
            entry_match = re.search(r'(entry|at|around)\s+([0-9a-z\.\$]+)', lower_text)
            
            target_val = target_match.group(2) if target_match else "N/A"
            sl_val = sl_match.group(2) if sl_match else "N/A"
            entry_val = entry_match.group(2) if entry_match else "Current Price"
            
            mock_prompt = f"Regex Scan for Buy/Sell keywords in:\n{text_to_analyze}"
            mock_response = json.dumps({
                "trade_detected": True,
                "asset": asset,
                "direction": direction,
                "entry_price": entry_val,
                "target_price": target_val,
                "stop_loss": sl_val,
                "confidence": "HIGH (Mock Detection)",
                "reasoning": f"Regex matched pattern: '{match.group(0)}'"
            }, indent=2)
            
            await broadcast_message({
                "type": "gemini_debug",
                "slot_id": slot.slot_id,
                "prompt": mock_prompt,
                "response": mock_response
            })
            
            await broadcast_message({
                "type": "trade_alert",
                "slot_id": slot.slot_id,
                "stream_title": slot.title,
                "asset": asset,
                "direction": direction,
                "entry_price": entry_val,
                "target_price": target_val,
                "stop_loss": sl_val,
                "confidence": "HIGH (Mock Detection)",
                "reasoning": f"Mock detected pattern: '{match.group(0)}' in transcript."
            })
            
            asyncio.create_task(send_telegram_alert(
                stream_title=slot.title,
                asset=asset,
                direction=direction,
                entry_price=entry_val,
                target_price=target_val,
                stop_loss=sl_val,
                confidence="HIGH (Mock Detection)",
                reasoning=f"Mock pattern matched: '{match.group(0)}' in transcript."
            ))
            
    # Turn off indicator on UI
    await broadcast_message({
        "type": "gemini_status",
        "slot_id": slot.slot_id,
        "active": False
    })

async def process_chunk(slot: SlotState, filepath: str, offset: float):
    loop = asyncio.get_running_loop()
    try:
        # Transcribe audio using Groq API
        transcription = await loop.run_in_executor(None, call_groq_whisper, filepath)
        
        # Delete temp file
        if os.path.exists(filepath):
            try: os.remove(filepath)
            except: pass
            
        if transcription and transcription.strip():
            text_val = transcription.strip()
            timestamp_str = format_timestamp(offset)
            
            # Broadcast subtitle to frontend
            await broadcast_message({
                "type": "subtitle",
                "slot_id": slot.slot_id,
                "timestamp": timestamp_str,
                "text": text_val
            })
            
            # Run Gemini analysis on the new text block
            await run_gemini_analysis(slot, text_val)
    except Exception as e:
        print(f"Error in process_chunk for slot {slot.slot_id}: {e}")
        if os.path.exists(filepath):
            try: os.remove(filepath)
            except: pass

async def slot_processing_loop(slot: SlotState):
    loop = asyncio.get_running_loop()
    chunk_id = 0
    
    # Base temp filename for this slot
    temp_file = f"temp_chunk_{slot.slot_id}.mp3"
    
    try:
        while slot.active:
            if slot.status != "Transcribing":
                await asyncio.sleep(0.5)
                continue
                
            start_time = time.time()
            
            # Build ffmpeg command to slice 30s of audio
            ffmpeg_cmd = ['ffmpeg', '-y', '-loglevel', 'error']
            if not slot.is_live:
                ffmpeg_cmd.extend(['-ss', str(slot.offset_seconds)])
                
            ffmpeg_cmd.extend([
                '-i', slot.direct_audio_url,
                '-t', '30',
                '-vn',
                '-acodec', 'libmp3lame',
                '-ar', '16000',
                '-ac', '1',
                temp_file
            ])
            
            # Execute ffmpeg command
            success = await loop.run_in_executor(None, run_ffmpeg, ffmpeg_cmd)
            
            if not success or not os.path.exists(temp_file) or os.path.getsize(temp_file) == 0:
                print(f"Slot {slot.slot_id}: Failed to capture audio chunk.")
                if os.path.exists(temp_file):
                    try: os.remove(temp_file)
                    except: pass
                    
                if not slot.is_live:
                    # For static streams, this signals we reached the end of the video file
                    slot.status = "Inactive"
                    slot.active = False
                    await broadcast_message(get_status_payload())
                    break
                else:
                    # Live stream error, wait and try to reconnect
                    await asyncio.sleep(5)
                    continue
            
            # Handle chunk processing based on stream type
            if slot.is_live:
                # Live streams require gapless capturing. We rename the file and hand it off
                # to a background process task while the loop immediately starts capturing the next chunk.
                live_temp_file = f"temp_chunk_{slot.slot_id}_{chunk_id}.mp3"
                try:
                    os.rename(temp_file, live_temp_file)
                except Exception as e:
                    print(f"Error renaming live temp file: {e}")
                    live_temp_file = temp_file
                    
                asyncio.create_task(process_chunk(slot, live_temp_file, slot.offset_seconds))
                slot.offset_seconds += 30.0
                chunk_id += 1
                # No extra sleep is needed because ffmpeg already spent 30 seconds recording the live audio!
            else:
                # For static videos, we process synchronously inside the loop and regulate the speed
                await process_chunk(slot, temp_file, slot.offset_seconds)
                slot.offset_seconds += 30.0
                chunk_id += 1
                
                # Regulate processing loop speed to simulate real-time playback
                elapsed = time.time() - start_time
                sleep_time = max(0.1, 30.0 - elapsed)
                await asyncio.sleep(sleep_time)
                
    except asyncio.CancelledError:
        print(f"Slot {slot.slot_id}: Background processing loop cancelled.")
    except Exception as e:
        print(f"Error in slot {slot.slot_id} processing loop: {e}")
    finally:
        if os.path.exists(temp_file):
            try: os.remove(temp_file)
            except: pass
        slot.active = False
        slot.status = "Inactive"
        await broadcast_message(get_status_payload())

# Main FastAPI routes
@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.head("/")
async def head_dashboard():
    return HTMLResponse(status_code=200)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    try:
        # Send current slots status immediately
        await websocket.send_json(get_status_payload())
        
        while True:
            data_str = await websocket.receive_text()
            data = json.loads(data_str)
            action = data.get("action")
            
            if action == "connect":
                url = data.get("url")
                start_time = data.get("start_time", "")
                asyncio.create_task(connect_new_stream(url, start_time))
            elif action == "disconnect":
                slot_id = data.get("slot_id")
                await disconnect_slot(slot_id)
    except WebSocketDisconnect:
        active_connections.remove(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if websocket in active_connections:
            active_connections.remove(websocket)

def parse_start_time(time_str: str) -> float:
    if not time_str or not time_str.strip():
        return 0.0
    parts = time_str.strip().split(':')
    try:
        if len(parts) == 1:
            return float(parts[0])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    return 0.0

async def connect_new_stream(url: str, start_time: str = ""):
    start_seconds = parse_start_time(start_time)
    
    # Find free slot
    async with slots_lock:
        free_slot = None
        for s in slots:
            if not s.active:
                free_slot = s
                break
        
        if free_slot is None:
            print("Cannot connect new stream: All 5 slots are full.")
            return

        # Reserve slot
        free_slot.active = True
        free_slot.status = "Connecting"
        free_slot.url = url
        free_slot.title = "Connecting..."
        free_slot.offset_seconds = start_seconds
        free_slot.is_live = False
        free_slot.gemini_text_buffer.clear()
        free_slot.history_text = ""
        
        await broadcast_message(get_status_payload())

    # Resolve URL and start transcription thread
    loop = asyncio.get_running_loop()
    try:
        is_live, title = await loop.run_in_executor(None, get_video_info, url)
        free_slot.title = title
        free_slot.is_live = is_live
        
        # Get the direct audio URL for ffmpeg
        direct_url = await loop.run_in_executor(None, get_direct_audio_url, url)
        free_slot.direct_audio_url = direct_url
        free_slot.status = "Transcribing"
        await broadcast_message(get_status_payload())
        
        # Start transcription loop task
        free_slot.task = asyncio.create_task(slot_processing_loop(free_slot))
            
    except Exception as e:
        print(f"Slot {free_slot.slot_id} connection failed: {e}")
        free_slot.active = False
        free_slot.status = "Inactive"
        await broadcast_message(get_status_payload())

async def disconnect_slot(slot_id: int):
    if slot_id < 0 or slot_id >= 5:
        return
    slot = slots[slot_id]
    if slot.active:
        slot.active = False
        slot.status = "Inactive"
        if slot.task:
            slot.task.cancel()
        await broadcast_message(get_status_payload())

# Clean up residual files on startup
@app.on_event("startup")
async def startup_event():
    # Delete temporary files from previous crashes/runs
    for file in os.listdir('.'):
        if file.startswith("temp_chunk_") and file.endswith(".mp3"):
            try: os.remove(file)
            except: pass
            
    print("\n" + "="*80)
    print("Trade-whisper-cloud server dashboard is starting.")
    print("Local URL: http://localhost:8000")
    print("="*80 + "\n")

@app.on_event("shutdown")
def shutdown_event():
    # Cancel all slot processing tasks and delete remaining chunk files
    for slot in slots:
        slot.active = False
        slot.status = "Inactive"
        if slot.task:
            slot.task.cancel()
            
    for file in os.listdir('.'):
        if file.startswith("temp_chunk_") and file.endswith(".mp3"):
            try: os.remove(file)
            except: pass

if __name__ == '__main__':
    # Start FastAPI server on port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
