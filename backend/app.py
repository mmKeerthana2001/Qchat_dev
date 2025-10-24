from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from elevenlabs.client import ElevenLabs
from elevenlabs.play import play
from dotenv import load_dotenv
from fastapi import FastAPI, Request
import os
import speech_recognition as sr

load_dotenv()

API_KEY = os.getenv("ELEVENLABS_API_KEY")
elevenlabs = ElevenLabs(api_key=API_KEY)

app = FastAPI()

# Allow CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/voice")
async def voice_response(request: Request):
    body = await request.json()
    text = body.get("text", "")

    if not text:
        return {"error": "No text provided"}

    # Generate speech (streaming generator)
    voice_id = "JBFqnCBsd6RMkjVDRZzb"
    model_id = "eleven_multilingual_v2"
    output_format = "mp3_44100_128"

    audio_stream = elevenlabs.text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id=model_id,
        output_format=output_format,
    )

    response_path = "static/response.mp3"
    os.makedirs("static", exist_ok=True)

    with open(response_path, "wb") as f:
        for chunk in audio_stream:
            f.write(chunk)

    return {"text": text, "audio_file": "/response.mp3"}

# Serve static files
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="static", html=True), name="static")
