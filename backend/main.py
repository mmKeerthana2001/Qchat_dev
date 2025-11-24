#main.py
import os
import asyncio
from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Dict, List
from read_files import ReadFiles
from context_manager import ContextManager
from login import LoginHandler
from agent import Agent
import logging
from fastapi.responses import JSONResponse, RedirectResponse, Response, FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import time
from pydantic import BaseModel
import io
import uuid
import re
import traceback
import base64
from pymongo import MongoClient
from dotenv import load_dotenv
import pathlib
from datetime import datetime
import googlemaps
from googlemaps.exceptions import ApiError
import urllib.parse
from rapidfuzz import process, fuzz
import requests
from pydub import AudioSegment
from openai import AsyncOpenAI
from pymongo.errors import CollectionInvalid
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import math
from math import radians, sin, cos, sqrt, atan2
from fuzzywuzzy import fuzz
from google.cloud import texttospeech
from google.oauth2 import service_account
from openai import OpenAI

load_dotenv()
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
ELEVENLABS_MODEL_ID_STT = os.getenv("ELEVENLABS_MODEL_ID_STT", "scribe_v2")
ELEVENLABS_MODEL_ID_TTS = os.getenv("ELEVENLABS_MODEL_ID_TTS", "eleven_multilingual_v2")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_TTS")
LIVE_MODE = os.getenv("LIVE_MODE", "false").lower() == "true"
HARDCODED_DELAY_SECONDS = 5  # Fixed 5-second delay before playing hardcoded audio
KANNADA_PRESTORED_PATH = r"C:\Users\Quadrant\Qchat-main\backend\output_kannada.mp3"
TELUGU_PRESTORED_PATH = r"C:\Users\Quadrant\Qchat-main\backend\output_telugu.mp3"
session_storage = {}
websocket_connections: Dict[str, List[WebSocket]] = {}

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY) if GOOGLE_MAPS_API_KEY else None
agent = Agent()
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
sync_openai = OpenAI(api_key=OPENAI_API_KEY)

class DebugMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        logger.debug(f"Request path: {request.url.path}")
        logger.debug(f"Request headers: {dict(request.headers)}")
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            logger.debug("Multipart form data request detected")
        response = await call_next(request)
        return response

app = FastAPI()
router = APIRouter()

app.add_middleware(DebugMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "upgrade", "websocket"],
)

file_reader = ReadFiles()
context_manager = ContextManager()
login_handler = LoginHandler()

logging.basicConfig(level=logging.INFO)
logging.getLogger("python_multipart").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

mongo_client = MongoClient("mongodb://localhost:27017")
db = mongo_client["document_analysis"]
sessions_collection = db["sessions"]

security = HTTPBearer(auto_error=False)

async def verify_session(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials or credentials.scheme != "Bearer" or not credentials.credentials:
        logger.error("Invalid or missing Authorization header. Expected: 'Bearer <session_id>'")
        raise HTTPException(status_code=401, detail="Invalid or missing Authorization header")
    session_id = credentials.credentials
    try:
        session = sessions_collection.find_one({"session_id": session_id})
        if not session:
            logger.error(f"Invalid session ID: {session_id}")
            raise HTTPException(status_code=401, detail="Invalid session ID")
        if session.get("expires_at") < datetime.utcnow():
            logger.error(f"Session expired: {session_id}")
            raise HTTPException(status_code=401, detail="Session expired")
        logger.info(f"Verified session {session_id} for user {session['email']}")
        return {"user_id": session["user_id"], "email": session["email"]}
    except Exception as e:
        logger.error(f"Error verifying session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error verifying session: {str(e)}")

async def verify_websocket_session(session_id: str):
    try:
        if not is_valid_uuid(session_id):
            logger.error(f"Invalid session_id format for WebSocket: {session_id}")
            raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")
        session = await context_manager.get_session(session_id)
        if not session:
            logger.error(f"Session not found for WebSocket: {session_id}")
            raise HTTPException(status_code=404, detail="Session not found")
        logger.info(f"Validated WebSocket session: {session_id}")
        return session
    except HTTPException as e:
        logger.error(f"WebSocket session validation failed: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error validating WebSocket session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error validating WebSocket session: {str(e)}")

class QueryRequest(BaseModel):
    query: str
    role: str

class SessionRequest(BaseModel):
    candidate_name: str
    candidate_email: str

class InitialMessageRequest(BaseModel):
    message: str

def is_valid_uuid(value: str) -> bool:
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    return bool(uuid_pattern.match(value))

@app.get("/login")
async def initiate_login():
    try:
        return await login_handler.initiate_login()
    except Exception as e:
        logger.error(f"Error initiating login: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error initiating login: {str(e)}")

@app.get("/callback")
async def handle_callback(request: Request):
    try:
        return await login_handler.handle_callback(request)
    except HTTPException as e:
        logger.error(f"HTTP error in callback: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error handling callback: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error handling callback: {str(e)}")

@app.get("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        if credentials and credentials.scheme == "Bearer" and credentials.credentials:
            session_id = credentials.credentials
            sessions_collection.delete_one({"session_id": session_id})
            logger.info(f"Session {session_id} invalidated")
        return RedirectResponse(url="http://localhost:8080/")
    except Exception as e:
        logger.error(f"Error during logout: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error during logout: {str(e)}")

@app.get("/user-info", dependencies=[Depends(verify_session)])
async def get_user_info(user: dict = Depends(verify_session)):
    return {"email": user["email"]}

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

@app.get("/sessions/", dependencies=[Depends(verify_session)])
async def get_sessions():
    try:
        sessions = await context_manager.list_sessions()
        return JSONResponse(content={"sessions": sessions})
    except Exception as e:
        logger.error(f"Error fetching sessions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching sessions: {str(e)}")

@app.post("/create-session/", dependencies=[Depends(verify_session)])
async def create_session(request: SessionRequest):
    try:
        start_time = time.time()
        session_id = str(uuid.uuid4())
        share_token = str(uuid.uuid4())
        await context_manager.create_session(session_id, request.candidate_name, request.candidate_email, share_token)
        logger.info(f"Created new session: {session_id} for {request.candidate_name}")

        session = await context_manager.get_session(session_id)
        initial_message = session["chat_history"][0]["query"]
        logger.info(f"Broadcasting and saving initial message: '{initial_message}' for session {session_id}")
        if session_id in websocket_connections:
            for ws in websocket_connections[session_id]:
                try:
                    await ws.send_json({
                        "role": "system",
                        "content": initial_message,
                        "timestamp": time.time(),
                        "type": "initial"
                    })
                    logger.debug(f"Sent WebSocket message to client for session {session_id}")
                except Exception as e:
                    logger.error(f"WebSocket broadcast failed for session {session_id}: {str(e)}")
                    websocket_connections[session_id].remove(ws)

        logger.info(f"Session creation time: {time.time() - start_time:.2f} seconds")
        return JSONResponse(content={"session_id": session_id, "share_token": share_token})
    except Exception as e:
        logger.error(f"Error creating session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating session: {str(e)}")

@app.post("/extract-text/{session_id}")
async def extract_text_from_files(session_id: str, files: List[UploadFile] = File(...)):
    start_time = time.time()
    try:
        if not is_valid_uuid(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")
       
        logger.info(f"Received {len(files)} files for session {session_id}: {[file.filename for file in files]}")
        allowed_extensions = ["pdf", "doc", "docx"]
        file_contents = []
        for file in files:
            if not file.filename:
                raise HTTPException(status_code=400, detail="No filename provided for one or more files")
            file_ext = file.filename.split(".")[-1].lower()
            if file_ext not in allowed_extensions:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file format: {file_ext}. Supported formats: {allowed_extensions}"
                )
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail=f"Empty file: {file.filename}")
            file_contents.append((file.filename, io.BytesIO(content)))
            logger.debug(f"Read {file.filename} into memory")
       
        results = await file_reader.file_reader(file_contents)
        extracted_text = {filename: text for filename, text in results.items()}
        for filename, text in extracted_text.items():
            logger.info(f"Processed {filename}: {len(text)} characters")
       
        await context_manager.store_session_data(session_id, extracted_text)
       
        if session_id in websocket_connections:
            for ws in websocket_connections[session_id]:
                try:
                    for filename in extracted_text.keys():
                        await ws.send_json({
                            "type": "file_uploaded",
                            "filename": filename,
                            "path": f"uploads/{session_id}/{filename}",
                            "timestamp": time.time()
                        })
                except:
                    websocket_connections[session_id].remove(ws)
       
        logger.info(f"Total processing time: {time.time() - start_time:.2f} seconds")
        return JSONResponse(content={"session_id": session_id, "extracted_text": extracted_text})
   
    except HTTPException as e:
        logger.error(f"HTTP error: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error processing files for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

@app.post("/upload-files/{session_id}")
async def upload_files(session_id: str, files: List[UploadFile] = File(...)):
    try:
        return await extract_text_from_files(session_id, files)
    except HTTPException as e:
        logger.error(f"HTTP error in upload-files: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error uploading files for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error uploading files: {str(e)}")

@app.get("/files/{session_id}")
async def get_files(session_id: str):
    try:
        if not is_valid_uuid(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")
        session = await context_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        extracted_text = session.get("extracted_text", {})
        files = [{"filename": filename, "path": f"uploads/{session_id}/{filename}"} for filename in extracted_text.keys()]
        logger.info(f"Retrieved {len(files)} files for session {session_id}")
        return JSONResponse(content={"files": files})
    except HTTPException as e:
        logger.error(f"HTTP error: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error retrieving files for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving files: {str(e)}")

@app.get("/download-file/{session_id}")
async def download_file(session_id: str, path: str):
    try:
        if not is_valid_uuid(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")
        file_path = pathlib.Path(path)
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(file_path, filename=file_path.name)
    except HTTPException as e:
        logger.error(f"HTTP error: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error downloading file for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error downloading file: {str(e)}")

@app.get("/messages/{session_id}")
async def get_messages(session_id: str):
    try:
        if not is_valid_uuid(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")
       
        session = await context_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
       
        chat_history = session.get("chat_history", [])
        messages = [
            {
                "role": msg["role"],
                "query": msg.get("query", ""),
                "response": msg.get("response", ""),
                "timestamp": msg.get("timestamp", time.time()),
                "audio_base64": msg.get("audio_base64"),
                "map_data": msg.get("map_data")
            }
            for msg in chat_history
        ]
        logger.info(f"Retrieved {len(messages)} messages for session {session_id}")
        return JSONResponse(content={"messages": messages})
    except HTTPException as e:
        logger.error(f"HTTP error: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error retrieving messages for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving messages: {str(e)}")

@app.post("/send-initial-message/{session_id}", dependencies=[Depends(verify_session)])
async def send_initial_message(session_id: str, req: InitialMessageRequest):
    try:
        if not is_valid_uuid(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")
       
        await context_manager.add_initial_message(session_id, req.message)
        if session_id in websocket_connections:
            for ws in websocket_connections[session_id]:
                try:
                    await ws.send_json({
                        "role": "hr",
                        "content": req.message,
                        "timestamp": time.time(),
                        "type": "initial"
                    })
                except:
                    websocket_connections[session_id].remove(ws)
       
        return JSONResponse(content={"status": "Initial message sent and flag set"})
    except Exception as e:
        logger.error(f"Error sending initial message for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error sending initial message: {str(e)}")

@app.get("/generate-share-link/{session_id}", dependencies=[Depends(verify_session)])
async def generate_share_link(session_id: str):
    try:
        if not is_valid_uuid(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")
        session = await context_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if not session.get("initial_message_sent", False):
            raise HTTPException(status_code=403, detail="Initial message must be sent before generating share link")
        share_token = session.get("share_token")
        link = f"http://localhost:8080/candidate-chat?token={share_token}"
        return JSONResponse(content={"share_link": link})
    except HTTPException as e:
        logger.error(f"HTTP error: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error generating share link for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating share link: {str(e)}")

@app.get("/get-session/{session_id}")
async def get_session(session_id: str):
    try:
        if not is_valid_uuid(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")
        session = await context_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return JSONResponse(content={
            "initial_message_sent": session.get("initial_message_sent", False)
        })
    except Exception as e:
        logger.error(f"Error getting session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting session: {str(e)}")

@app.get("/validate-token/")
async def validate_token(token: str):
    try:
        session_id = await context_manager.validate_token(token)
        if not session_id:
            logger.warning(f"Invalid or expired token: {token}")
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        logger.info(f"Validated token {token} for session {session_id}")
        return JSONResponse(content={"session_id": session_id})
    except HTTPException as e:
        raise
    except Exception as e:
        logger.error(f"Unexpected error validating token {token}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error validating token: {str(e)}")

async def process_chat_query(session_id: str, query_req: QueryRequest):
    try:
        session = await context_manager.get_session(session_id)
        history = session.get("chat_history", [])
        query_corrected = await agent.correct_query(query_req.query, history, query_req.role)

        agent_instance = Agent()
        intent_data = await agent_instance.classify_intent_and_extract(query_corrected, history, query_req.role)

        is_map_query = intent_data.get("is_map", False)
        map_data = None
        media_data = None
        if is_map_query:
            logger.info(f"Routing query '{query_corrected}' as map-related (is_map: {is_map_query}) with intent_data: {intent_data}")
            try:
                map_data = await handle_map_query(session_id, QueryRequest(
                    query=query_corrected,
                    role=query_req.role
                ), intent_data)
                response, history = await context_manager.process_map_query(session_id, query_corrected, query_req.role, map_data, intent_data)
            except Exception as e:
                logger.error(f"Map query failed for session {session_id}: {str(e)}")
                logger.error(f"Full traceback: {traceback.format_exc()}")
                logger.error(f"Intent data: {intent_data}, Query: {query_corrected}")
                response = f"Sorry, I couldn't process the location request for '{query_corrected}'. Please rephrase."
                history.append({
                    "role": query_req.role,
                    "query": query_corrected,
                    "response": response,
                    "timestamp": time.time(),
                    "intent_data": intent_data,
                    "map_data": None
                })
                collection_name = f"sessions_{session_id}"
                await context_manager.db[collection_name].update_one(
                    {"session_id": session_id},
                    {"$set": {"chat_history": history[-10:], "updated_at": time.time()}}
                )
                logger.warning(f"Fallback response stored for map query failure in session {session_id}")
        else:
            logger.info(f"Routing query '{query_corrected}' as non-map (is_map: {is_map_query}) with intent_data: {intent_data}")
            # Process all non-map queries through context_manager, including document-based ones
            response, media_data, history = await context_manager.process_query(session_id, query_corrected, query_req.role, intent_data=intent_data)
            logger.debug(f"Non-map query processed, media_data: {media_data}")

        # Broadcast to all WebSocket connections
        if session_id in websocket_connections:
            for ws in websocket_connections[session_id]:
                try:
                    ws_response = {
                        "role": query_req.role,
                        "content": query_corrected,
                        "timestamp": time.time(),
                        "type": "query"
                    }
                    await ws.send_json(ws_response)
                    ws_response = {
                        "role": "assistant",
                        "content": response,
                        "timestamp": time.time(),
                    }
                    if is_map_query:
                        # Include all map_data fields, including coordinates and encoded_polyline
                        ws_response["map_data"] = {
                            "type": map_data.get("type"),
                            "data": map_data.get("data"),
                            "map_url": map_data.get("map_url"),
                            "static_map_url": map_data.get("static_map_url"),
                            "coordinates": map_data.get("coordinates"),
                            "llm_response": map_data.get("llm_response"),
                            "encoded_polyline": map_data.get("encoded_polyline")
                        }
                    else:
                        ws_response["media_data"] = media_data
                    await ws.send_json(ws_response)
                    logger.debug(f"Broadcasted query and response to WebSocket for session {session_id}")
                except Exception as e:
                    logger.error(f"WebSocket broadcast failed for session {session_id}: {str(e)}")
                    websocket_connections[session_id].remove(ws)

        return response, map_data, media_data, history, is_map_query
    except Exception as e:
        logger.error(f"Error in process_chat_query: {str(e)}")
        raise

@app.post("/chat/{session_id}")
async def chat_with_documents(session_id: str, query_req: QueryRequest):
    try:
        if not is_valid_uuid(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")
       
        start_time = time.time()
        logger.info(f"Received chat query for session {session_id}: {query_req.query} by {query_req.role}")

        response, map_data, media_data, history, is_map_query = await process_chat_query(session_id, query_req)

        response_data = {
            "response": response,
            "history": history
        }
        if not is_map_query and media_data:
            response_data["media_data"] = media_data
            logger.debug(f"Including media_data in HTTP response: {media_data}")
       
        logger.info(f"Chat processing time: {time.time() - start_time:.2f} seconds")
        return JSONResponse(content=response_data)
    except HTTPException as e:
        logger.error(f"HTTP error: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error processing chat query for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing chat query: {str(e)}")
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Returns distance in kilometers between two lat/lng points."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return c * 6371  # Earth radius in km

country_to_city = {
    "malaysia": "Kuala Lumpur, Malaysia",
    "australia": "Lane Cove, Australia",
    "uk": "Chiswick, UK",
    "mexico": "Guadalajara, Mexico",
    "canada": "Surrey, Canada",
    "uae": "Dubai, UAE"
}
quadrant_locations = [
    {"city": "Redmond, WA", "address": "5020, 148th Ave NE Ste 250, Redmond, WA, 98052", "lat": 47.6456, "lng": -122.1419},
    {"city": "Iselin, NJ", "address": "33 S Wood Ave, Suite 600, Iselin, New Jersey, 08830", "lat": 40.5754, "lng": -74.3282},
    {"city": "Dallas, TX", "address": "3333 Lee Pkwy #600, Dallas, Texas, 75219", "lat": 32.8085, "lng": -96.8035},
    {"city": "Hyderabad, Telangana", "address": "4th floor, Building No.21, Raheja Mindspace, Sy No. 64 (Part), Madhapur, Hyderabad, Telangana, 500081", "lat": 17.4416, "lng": 78.3804},
    {"city": "Bengaluru, Karnataka", "address": "Office No. 106, #1, Navarathna garden, Doddakallasandra Kanakpura Road, Bengaluru, Karnataka, 560062", "lat": 12.8797, "lng": 77.5407},
    {"city": "Warangal, Telangana", "address": "IT - SEZ, Madikonda, Warangal, Telangana, 506009", "lat": 17.9475, "lng": 79.5781},
    {"city": "Noida, Uttar Pradesh", "address": "Worcoz, A-24, 1st Floor, Sector 63, Noida, Uttar Pradesh, 201301", "lat": 28.6270, "lng": 77.3727},
    {"city": "Guadalajara, Mexico", "address": "Amado Nervo 785, Guadalajara, Jalisco, 44656", "lat": 20.6720, "lng": -103.3668},
    {"city": "Surrey, Canada", "address": "7404 King George Blvd, Suite 200, Surrey, British Columbia, V3W 1N6", "lat": 49.1372, "lng": -122.8457},
    {"city": "Dubai, UAE", "address": "The Meydan Hotel, Grandstand, 6th floor, Meydan Road, Dubai, Nad Al Sheba", "lat": 25.1560, "lng": 55.2964},
    {"city": "Lane Cove, Australia", "address": "24 Birdwood Lane, Lane Cove, New South Wales", "lat": -33.8144, "lng": 151.1693},
    {"city": "Kuala Lumpur, Malaysia", "address": "19A-24-3, Level 24, Wisma UOA No. 19, Jalan Pinang, Business Suite Unit, Kuala Lumpur, Wilayah Persekutuan, 50450", "lat": 3.1517, "lng": 101.7129},
    {"city": "Singapore", "address": "#02-01, 68 Circular Road, Singapore, 049422", "lat": 1.2864, "lng": 103.8491},
    {"city": "Chiswick, UK", "address": "Gold Building 3 Chiswick Business Park, Chiswick, London, W4 5YA", "lat": 51.4937, "lng": -0.2786}
]

# Helper function to infer city from query components
def infer_city_from_query(query: str, origin: str, destination: str, quadrant_locations: list) -> str:
    """Infer the city from query, origin, or destination using fuzzy matching."""
    query_lower = query.lower()
    candidates = []
    
    # Check for city names in query, origin, or destination
    for loc in quadrant_locations:
        city_name = loc["city"].lower()
        # Direct match in query
        query_score = fuzz.partial_ratio(city_name, query_lower)
        origin_score = fuzz.partial_ratio(city_name, origin.lower()) if origin else 0
        dest_score = fuzz.partial_ratio(city_name, destination.lower()) if destination else 0
        max_score = max(query_score, origin_score, dest_score)
        if max_score >= 80:
            candidates.append((loc["city"], max_score))
    
    # Sort by score and return the best match
    if candidates:
        return max(candidates, key=lambda x: x[1])[0]
    
    # Fallback: Check for known landmarks (e.g., "Seattle Airport" -> "Redmond, WA")
    if "seattle airport" in query_lower or (destination and "seattle airport" in destination.lower()):
        return "Redmond, WA"  # Closest Quadrant location to Seattle
    # Add more landmark-to-city mappings as needed
    return None

# main.py (updated handle_map_query function)
@app.post("/map-query/{session_id}")
async def handle_map_query(session_id: str, query_req: QueryRequest, intent_data: dict = None):
    try:
        if not gmaps:
            raise HTTPException(status_code=500, detail="Google Maps API key not configured")
        if not is_valid_uuid(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")

        map_data = {}
        intent = intent_data.get("intent", "non_map") if intent_data else "non_map"
        city_value = intent_data.get("city") if intent_data else None
        city_query = city_value.lower() if isinstance(city_value, str) else ""
        nearby_value = intent_data.get("nearby_type") if intent_data else None
        nearby_type = nearby_value.lower() if isinstance(nearby_value, str) else ""
        origin_value = intent_data.get("origin") if intent_data else None
        origin = origin_value.strip() if isinstance(origin_value, str) else ""
        destination_value = intent_data.get("destination") if intent_data else None
        destination = destination_value.strip() if isinstance(destination_value, str) else ""

        logger.info(f"Extracted params: intent={intent}, city_query='{city_query}', nearby_type='{nearby_type}', origin='{origin}', destination='{destination}'")

        # Infer city if not provided, but skip for multi_location
        if intent != "multi_location" and not city_query:
            city_query = infer_city_from_query(query_req.query, origin, destination, quadrant_locations)
            if not city_query:
                raise HTTPException(status_code=400, detail="Could not determine city from query. Please specify a city (e.g., Redmond, WA).")

        # Find location with fuzzy matching
        location = None
        if city_query:
            location = next((loc for loc in quadrant_locations if loc["city"].lower() == city_query.lower()), None)
            if not location:
                for loc in quadrant_locations:
                    score = fuzz.partial_ratio(city_query.lower(), loc["city"].lower())
                    if score >= 80:
                        location = loc
                        break
                if not location:
                    raise HTTPException(status_code=404, detail=f"Quadrant Technologies location not found for {city_query}")

        if intent == "single_location":
            if not location:
                raise HTTPException(status_code=400, detail="Please specify a valid city for location query")
            
            map_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(location['address'])}"
            static_map_url = f"https://maps.googleapis.com/maps/api/staticmap?center={location['lat']},{location['lng']}&zoom=15&size=600x300&markers=color:purple|label:Q|{location['lat']},{location['lng']}&key={GOOGLE_MAPS_API_KEY}"
            
            map_data = {
                "type": "address",
                "data": location["address"],
                "city": location["city"],
                "map_url": map_url,
                "static_map_url": static_map_url
            }

        elif intent == "multi_location":
            locations_data = []
            coordinates = []
            for loc in quadrant_locations:
                map_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(loc['address'])}"
                static_map_url = f"https://maps.googleapis.com/maps/api/staticmap?center={loc['lat']},{loc['lng']}&zoom=15&size=600x300&markers=color:purple|label:Q|{loc['lat']},{loc['lng']}&key={GOOGLE_MAPS_API_KEY}"
                locations_data.append({
                    "city": loc["city"],
                    "address": loc["address"],
                    "map_url": map_url,
                    "static_map_url": static_map_url
                })
                coordinates.append({
                    "lat": loc["lat"],
                    "lng": loc["lng"],
                    "label": loc["city"]
                })
            
            # Compute center for overview map
            center_lat = sum(loc["lat"] for loc in quadrant_locations) / len(quadrant_locations)
            center_lng = sum(loc["lng"] for loc in quadrant_locations) / len(quadrant_locations)
            
            # Static overview map with markers (limit to first 10 for simplicity)
            markers_str = "|".join([f"color:blue|label:{loc['city'][0]}|{loc['lat']},{loc['lng']}" for loc in quadrant_locations[:10]])
            overview_static_map_url = f"https://maps.googleapis.com/maps/api/staticmap?center={center_lat},{center_lng}&zoom=2&size=600x300&maptype=roadmap&markers={markers_str}&key={GOOGLE_MAPS_API_KEY}"
            
            map_data = {
                "type": "multi_location",
                "data": locations_data,
                "map_url": f"https://www.google.com/maps/search/?api=1&query=Quadrant+Technologies+offices+worldwide",
                "static_map_url": overview_static_map_url,
                "coordinates": coordinates
            }

        elif intent == "nearby":
            if not location:
                raise HTTPException(status_code=400, detail="Please specify a city for nearby search")

            keyword = nearby_type or "nearby amenities"
            logger.info(f"Using keyword for Places API: '{keyword}'")

            if session_id not in session_storage:
                session_storage[session_id] = {"previous_places": [], "next_page_token": None}

            if query_req.query and "more" in query_req.query.lower():
                session_storage[session_id]["previous_places"] = []

            coordinates = [{
                "lat": location["lat"],
                "lng": location["lng"],
                "label": location["address"],
                "color": "purple"
            }]

            places = gmaps.places_nearby(
                location={"lat": location["lat"], "lng": location["lng"]},
                radius=2000,
                keyword=keyword
            )
            logger.info(f"Places API returned {len(places['results'])} results for keyword '{keyword}' near {location['city']}")
            data_list = []
            seen_place_ids = set(session_storage[session_id]["previous_places"])

            markers = [f"color:purple|label:Q|{location['lat']},{location['lng']}"]
            for place in places['results'][:10]:
                place_id = place['place_id']
                if place_id not in seen_place_ids:
                    place_lat, place_lng = place['geometry']['location']['lat'], place['geometry']['location']['lng']
                    price_level = place.get('price_level')
                    price_level_display = ''.join(['$'] * price_level) if price_level is not None else 'N/A'
                    place_type = place.get('types', [])[0].replace('_', ' ').title() if place.get('types') else 'N/A'
                    item = {
                        "name": place['name'],
                        "address": place.get('vicinity', 'N/A'),
                        "map_url": f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(place.get('vicinity', place['name']))}",
                        "static_map_url": f"https://maps.googleapis.com/maps/api/staticmap?center={place_lat},{place_lng}&zoom=15&size=150x112&markers=color:red|{place_lat},{place_lng}&key={GOOGLE_MAPS_API_KEY}",
                        "rating": place.get('rating', 'N/A'),
                        "total_reviews": place.get('user_ratings_total', 0),
                        "type": place_type,
                        "price_level": price_level_display
                    }
                    data_list.append(item)
                    coordinates.append({
                        "lat": place_lat,
                        "lng": place_lng,
                        "label": place.get('vicinity', place['name'])
                    })
                    markers.append(f"color:red|{place_lat},{place_lng}")
                    seen_place_ids.add(place_id)

            next_page_token = places.get('next_page_token')
            if next_page_token and len(data_list) < 10 and query_req.query and "more" in query_req.query.lower():
                logger.info(f"Fetching more results with next_page_token: {next_page_token}")
                time.sleep(2)
                more_places = gmaps.places_nearby(
                    location={"lat": location["lat"], "lng": location["lng"]},
                    radius=2000,
                    keyword=keyword,
                    page_token=next_page_token
                )
                logger.info(f"Places API returned {len(more_places['results'])} additional results")
                for place in more_places['results'][:10 - len(data_list)]:
                    place_id = place['place_id']
                    if place_id not in seen_place_ids:
                        place_lat, place_lng = place['geometry']['location']['lat'], place['geometry']['location']['lng']
                        price_level = place.get('price_level')
                        price_level_display = ''.join(['$'] * price_level) if price_level is not None else 'N/A'
                        place_type = place.get('types', [])[0].replace('_', ' ').title() if place.get('types') else 'N/A'
                        item = {
                            "name": place['name'],
                            "address": place.get('vicinity', 'N/A'),
                            "map_url": f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(place.get('vicinity', place['name']))}",
                            "static_map_url": f"https://maps.googleapis.com/maps/api/staticmap?center={place_lat},{place_lng}&zoom=15&size=150x112&markers=color:red|{place_lat},{place_lng}&key={GOOGLE_MAPS_API_KEY}",
                            "rating": place.get('rating', 'N/A'),
                            "total_reviews": place.get('user_ratings_total', 0),
                            "type": place_type,
                            "price_level": price_level_display
                        }
                        data_list.append(item)
                        coordinates.append({
                            "lat": place_lat,
                            "lng": place_lng,
                            "label": place.get('vicinity', place['name'])
                        })
                        markers.append(f"color:red|{place_lat},{place_lng}")
                        seen_place_ids.add(place_id)

            session_storage[session_id]["previous_places"] = list(seen_place_ids)
            session_storage[session_id]["next_page_token"] = next_page_token if next_page_token else None
            logger.info(f"Session {session_id} updated: {session_storage[session_id]}")

            if not data_list:
                logger.warning(f"No {keyword} found within 2000m. Trying broader radius (3000m).")
                places = gmaps.places_nearby(
                    location={"lat": location["lat"], "lng": location["lng"]},
                    radius=3000,
                    keyword=keyword
                )
                for place in places['results'][:10]:
                    place_id = place['place_id']
                    if place_id not in seen_place_ids:
                        place_lat, place_lng = place['geometry']['location']['lat'], place['geometry']['location']['lng']
                        price_level = place.get('price_level')
                        price_level_display = ''.join(['$'] * price_level) if price_level is not None else 'N/A'
                        place_type = place.get('types', [])[0].replace('_', ' ').title() if place.get('types') else 'N/A'
                        item = {
                            "name": place['name'],
                            "address": place.get('vicinity', 'N/A'),
                            "map_url": f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(place.get('vicinity', place['name']))}",
                            "static_map_url": f"https://maps.googleapis.com/maps/api/staticmap?center={place_lat},{place_lng}&zoom=15&size=150x112&markers=color:red|{place_lat},{place_lng}&key={GOOGLE_MAPS_API_KEY}",
                            "rating": place.get('rating', 'N/A'),
                            "total_reviews": place.get('user_ratings_total', 0),
                            "type": place_type,
                            "price_level": price_level_display
                        }
                        data_list.append(item)
                        coordinates.append({
                            "lat": place_lat,
                            "lng": place_lng,
                            "label": place.get('vicinity', place['name'])
                        })
                        markers.append(f"color:red|{place_lat},{place_lng}")
                        seen_place_ids.add(place_id)
                session_storage[session_id]["previous_places"] = list(seen_place_ids)

            if not data_list:
                raise HTTPException(status_code=404, detail=f"No {keyword} found near {location['city']}")

            all_lats = [location["lat"]] + [place["lat"] for place in coordinates[1:]]
            all_lngs = [location["lng"]] + [place["lng"] for place in coordinates[1:]]
            center_lat = sum(all_lats) / len(all_lats)
            center_lng = sum(all_lngs) / len(all_lngs)
            
            unified_map_url = f"https://www.google.com/maps/search/?api=1&query={center_lat},{center_lng}&zoom=13"
            
            unified_static_map_url = (
                f"https://maps.googleapis.com/maps/api/staticmap?center={center_lat},{center_lng}"
                f"&zoom=13&size=600x300&markers={'|'.join(markers)}&key={GOOGLE_MAPS_API_KEY}"
            )

            map_data = {
                "type": "nearby",
                "data": data_list,
                "coordinates": coordinates,
                "map_url": unified_map_url,
                "static_map_url": unified_static_map_url
            }

        elif intent == "directions":
            if not location:
                raise HTTPException(status_code=400, detail="Please specify a destination city for directions")
            source = location
            source_addr = source["address"]

            if origin:
                directions = gmaps.directions(origin, source_addr, mode="driving")
                if directions:
                    legs = directions[0]['legs'][0]
                    steps = [re.sub('<[^<]+?>', '', step['html_instructions']) for step in legs['steps']]
                    origin_addr = legs['start_address']
                    dest_addr = legs['end_address']
                    encoded_polyline = directions[0]['overview_polyline']['points']
                    map_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(origin_addr)}&destination={urllib.parse.quote(dest_addr)}&travelmode=driving"
                    static_map_url = f"https://maps.googleapis.com/maps/api/staticmap?size=600x300&path=enc:{urllib.parse.quote(encoded_polyline)}&markers=label:S|color:green|{legs['start_location']['lat']},{legs['start_location']['lng']}|label:D|color:red|{legs['end_location']['lat']},{legs['end_location']['lng']}&key={GOOGLE_MAPS_API_KEY}"
                    map_data = {
                        "type": "directions",
                        "data": steps,
                        "map_url": map_url,
                        "static_map_url": static_map_url,
                        "encoded_polyline": encoded_polyline,
                        "coordinates": [
                            {"lat": legs['start_location']['lat'], "lng": legs['start_location']['lng'], "label": origin_addr, "color": "green"},
                            {"lat": legs['end_location']['lat'], "lng": legs['end_location']['lng'], "label": dest_addr, "color": "red"}
                        ]
                    }
                else:
                    raise HTTPException(status_code=404, detail="Directions not found")
            else:
                raise HTTPException(status_code=400, detail="Please specify an origin for directions")

        elif intent == "distance":
            if not location:
                raise HTTPException(status_code=400, detail="Please specify a city for distance query")
            source = location
            source_addr = source["address"]

            if not destination:
                raise HTTPException(status_code=400, detail="Please specify a destination for distance query")

            places_url = "https://places.googleapis.com/v1/places:searchText"
            headers = {
                "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location"
            }
            payload = {
                "textQuery": f"{destination} near {source['city']}",
                "locationBias": {
                    "circle": {
                        "center": {"latitude": source["lat"], "longitude": source["lng"]},
                        "radius": 50000
                    }
                }
            }
            try:
                places_response = requests.post(places_url, json=payload, headers=headers, timeout=10)
                logger.debug(f"Places API request payload: {payload}")
                logger.debug(f"Places API response: {places_response.text}")
                places_response.raise_for_status()
                places_data = places_response.json()
                
                if not places_data.get("places"):
                    raise HTTPException(status_code=404, detail=f"Could not find a precise location for {destination} near {source['city']}")
                
                place = places_data["places"][0]
                place_id = place.get("id")
                dest_name = place.get("displayName", {}).get("text", destination)
                dest_addr = place.get("formattedAddress", dest_name)
                dest_lat = place.get("location", {}).get("latitude")
                dest_lng = place.get("location", {}).get("longitude")

                if dest_lat and dest_lng:
                    approx_distance = haversine_distance(source["lat"], source["lng"], dest_lat, dest_lng)
                    if approx_distance > 100:
                        logger.warning(f"Places API returned a location too far away: {dest_addr} ({approx_distance:.1f} km)")
                        raise HTTPException(status_code=404, detail=f"Found {dest_name} at {dest_addr}, but it's too far from {source['city']}. Please clarify the destination.")

            except requests.RequestException as e:
                logger.error(f"Places API error: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Google Maps Places API error: {str(e)}")

            routes_url = "https://routes.googleapis.com/directions/v2:computeRoutes"
            headers = {
                "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"
            }
            payload = {
                "origin": {"address": source_addr},
                "destination": {"placeId": place_id} if place_id else {"address": dest_name},
                "travelMode": "DRIVE",
                "computeAlternativeRoutes": False,
                "units": "METRIC"
            }
            try:
                response = requests.post(routes_url, json=payload, headers=headers, timeout=10)
                logger.debug(f"Routes API request payload: {payload}")
                logger.debug(f"Routes API response: {response.text}")
                response.raise_for_status()
                route_data = response.json()
                
                if route_data.get("routes"):
                    distance_meters = route_data["routes"][0]["distanceMeters"]
                    duration_seconds = int(route_data["routes"][0]["duration"].rstrip("s"))
                    encoded_polyline = route_data["routes"][0]["polyline"]["encodedPolyline"]
                    distance = f"{distance_meters / 1000:.1f} km"
                    duration = f"{duration_seconds // 60} mins" if duration_seconds < 3600 else f"{duration_seconds // 3600} hr {(duration_seconds % 3600) // 60} mins"
                    origin_addr = source_addr
                    
                    map_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(origin_addr)}&destination={urllib.parse.quote(dest_addr)}&travelmode=driving"
                    static_map_url = f"https://maps.googleapis.com/maps/api/staticmap?size=600x300&path=enc:{urllib.parse.quote(encoded_polyline)}&markers=label:S|color:green|{source['lat']},{source['lng']}|label:D|color:red|{dest_lat},{dest_lng}&key={GOOGLE_MAPS_API_KEY}"
                    
                    map_data_temp = {
                        "type": "distance",
                        "data": {
                            "origin": origin_addr,
                            "destination": dest_name,
                            "distance": distance,
                            "duration": duration
                        }
                    }
                    llm_response = await agent.process_map_query(map_data_temp, query_req.query, role="candidate")
                    
                    map_data = {
                        "type": "distance",
                        "data": {
                            "origin": origin_addr,
                            "destination": dest_name,
                            "distance": distance,
                            "duration": duration
                        },
                        "llm_response": llm_response,
                        "map_url": map_url,
                        "static_map_url": static_map_url,
                        "encoded_polyline": encoded_polyline,
                        "coordinates": [
                            {"lat": source["lat"], "lng": source["lng"], "label": "Origin", "color": "green"},
                            {"lat": dest_lat, "lng": dest_lng, "label": dest_name, "color": "red"}
                        ]
                    }
                else:
                    raise HTTPException(status_code=404, detail=f"No route found to {dest_name}")
            except requests.RequestException as e:
                logger.error(f"Routes API error: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Google Maps Routes API error: {str(e)}")

        else:
            raise HTTPException(status_code=400, detail="Invalid map intent")

        return map_data
    except ApiError as e:
        logger.error(f"Google Maps API error for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Google Maps API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing map query for session {session_id}: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error processing map query: {str(e)}")

def strip_markdown(text: str) -> str:
    if not text:
        return text
    # Remove headers
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    # Remove bold **text** and italics *text*
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    # Remove links [text](url)
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    # Remove code blocks
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    # Remove inline code `code`
    text = re.sub(r'`(.*?)`', r'\1', text)
    # Clean up extra newlines
    text = re.sub(r'\n\s*\n', '\n\n', text)
    # Remove trailing punctuation if needed, but keep periods
    return text.strip()
async def detect_language(text: str) -> str:
    try:
        completion = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a language detector. Detect the language of the following text. It is either English ('en'), Kannada ('kn', uses Kannada script with rounded letters), or Telugu ('te', uses Telugu script with distinct circular vowels and more curves). Respond with only the ISO code."},
                {"role": "user", "content": f"Language: {text}"}
            ],
            max_tokens=5
        )
        lang = completion.choices[0].message.content.strip().lower()
        return lang if lang in ['en', 'kn', 'te'] else 'en'
    except Exception as e:
        logging.getLogger(__name__).warning(f"Language detection failed: {e}, defaulting to 'en'")
        return 'en'
def detect_language_sync(text: str) -> str:
    try:
        completion = sync_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a language detector. Detect the language of the following text. It is either English ('en'), Kannada ('kn', uses Kannada script with rounded letters), or Telugu ('te', uses Telugu script with distinct circular vowels and more curves). Respond with only the ISO code."},
                {"role": "user", "content": f"Language: {text}"}
            ],
            max_tokens=5
        )
        lang = completion.choices[0].message.content.strip().lower()
        return lang if lang in ['en', 'kn', 'te'] else 'en'
    except Exception as e:
        logging.getLogger(__name__).warning(f"Language detection failed: {e}, defaulting to 'en'")
        return 'en'
async def translate_text(text: str, target_lang: str, source_lang: str) -> str:
    if source_lang == target_lang:
        return text
    try:
        prompt = f"Translate the following text from {source_lang} to {target_lang}. Provide only the translation, no additional text: {text}"
        completion = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        logging.getLogger(__name__).error(f"Translation failed: {e}")
        return text  # Fallback to original
def translate_text_sync(text: str, target_lang: str, source_lang: str) -> str:
    if source_lang == target_lang:
        return text
    try:
        prompt = f"Translate the following text from {source_lang} to {target_lang}. Provide only the translation, no additional text: {text}"
        completion = sync_openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        logging.getLogger(__name__).error(f"Translation failed: {e}")
        return text  # Fallback to original
def split_into_sentences(text: str, max_length: int = 150) -> list[str]:
    # Split on sentence-ending punctuation: ., ?, !, । followed by whitespace
    sentences = re.split(r'([.?!।]\s+)', text)
    chunks = []
    current_chunk = ""
    for part in sentences:
        if len(current_chunk + part) > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = part
        else:
            current_chunk += part
    if current_chunk:
        chunks.append(current_chunk.strip())
    # If still too long, split by words
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= max_length:
            final_chunks.append(chunk)
        else:
            words = chunk.split()
            sub_chunk = ""
            for word in words:
                if len(sub_chunk + word + " ") > max_length:
                    if sub_chunk:
                        final_chunks.append(sub_chunk.strip())
                    sub_chunk = word + " "
                else:
                    sub_chunk += word + " "
            if sub_chunk:
                final_chunks.append(sub_chunk.strip())
    return [c for c in final_chunks if c]
def generate_indic_tts(text: str, lang: str) -> bytes:
    if not GOOGLE_CREDENTIALS_PATH or not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        raise Exception("Google TTS credentials not found. Set GOOGLE_TTS in .env to the path of your service account JSON.")
    credentials = service_account.Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH)
    client = texttospeech.TextToSpeechClient(credentials=credentials)
    # Set language and voice based on lang
    if lang == 'kn':
        language_code = "kn-IN"
        voice_name = "kn-IN-Chirp3-HD-Achernar"
    elif lang == 'te':
        language_code = "te-IN"
        voice_name = "te-IN-Chirp3-HD-Achernar"
    else:
        raise ValueError(f"Unsupported Indic language: {lang}")
    # Split into small sentences/chunks
    chunks = split_into_sentences(text)
    if not chunks:
        raise ValueError("No valid chunks to synthesize")
    audio_segments = []
    for i, chunk in enumerate(chunks):
        try:
            synthesis_input = texttospeech.SynthesisInput(text=chunk)
            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice_name
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            # Load as AudioSegment for concatenation
            seg = AudioSegment.from_mp3(io.BytesIO(response.audio_content))
            audio_segments.append(seg)
            # Add a short pause between chunks for natural flow (except last)
            if i < len(chunks) - 1:
                pause = AudioSegment.silent(duration=500)  # 0.5 second pause
                audio_segments.append(pause)
        except Exception as e:
            logger.warning(f"Failed to synthesize chunk '{chunk[:50]}...': {e}")
            # Skip this chunk and continue
            continue
    if not audio_segments:
        raise ValueError("No audio segments generated")
    # Concatenate all segments
    combined = AudioSegment.empty()
    for seg in audio_segments:
        combined += seg
    # Export combined audio to bytes
    output = io.BytesIO()
    combined.export(output, format="mp3")
    output.seek(0)
    return output.getvalue()
def load_pre_stored_audio(lang: str) -> bytes:
    if lang == 'kn':
        file_path = KANNADA_PRESTORED_PATH
    elif lang == 'te':
        file_path = TELUGU_PRESTORED_PATH
    else:
        raise ValueError(f"No pre-stored audio for language: {lang}")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Pre-stored audio file not found: {file_path}")
    with open(file_path, 'rb') as f:
        return f.read()
@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    try:
        await verify_websocket_session(session_id)
        await websocket.accept()
        if session_id not in websocket_connections:
            websocket_connections[session_id] = []
        websocket_connections[session_id].append(websocket)
        logger.info(f"WebSocket connected for session {session_id}. Total connections: {len(websocket_connections[session_id])}")
       
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                    logger.debug(f"Received ping for session {session_id}, sent pong")
                    continue
               
                # Process text query
                query = data.get("content")
                role = data.get("role", "candidate")
                if query:
                    query_req = QueryRequest(query=query, role=role)
                    response, map_data, media_data, history, is_map_query = await process_chat_query(session_id, query_req)
                    # Persist message
                    await persist_message(
                        session_id=session_id,
                        query=query,
                        response=response,
                        role=role,
                        map_data=map_data,
                        media_data=media_data
                    )
               
        except WebSocketDisconnect:
            websocket_connections[session_id].remove(websocket)
            logger.info(f"WebSocket disconnected for session {session_id}. Remaining connections: {len(websocket_connections[session_id])}")
            if not websocket_connections[session_id]:
                del websocket_connections[session_id]
        except Exception as e:
            logger.error(f"WebSocket error for session {session_id}: {str(e)}")
            await websocket.send_json({"error": str(e)})
    except HTTPException as e:
        logger.error(f"WebSocket connection rejected for session {session_id}: {e.detail}")
        await websocket.close(code=1008, reason=e.detail)
    except Exception as e:
        logger.error(f"Unexpected WebSocket error for session {session_id}: {str(e)}")
        await websocket.close(code=1011, reason="Internal server error")
    finally:
        if session_id in websocket_connections and websocket in websocket_connections[session_id]:
            websocket_connections[session_id].remove(websocket)
            if not websocket_connections[session_id]:
                del websocket_connections[session_id]
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.HTTPError),
    before_sleep=lambda retry_state: logger.debug(f"Retrying STT request, attempt {retry_state.attempt_number} after {retry_state.next_action.sleep}s")
)
def send_stt_request(audio_filename, mp3_bytes):
    stt_url = "https://api.elevenlabs.io/v1/speech-to-text"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY
    }
    files = {
        "file": (audio_filename, mp3_bytes, "audio/mp3"),
        "model_id": (None, ELEVENLABS_MODEL_ID_STT)
    }
    response = requests.post(stt_url, headers=headers, files=files)
    response.raise_for_status()
    return response.json()
async def speech_to_text(audio_bytes: bytes) -> str:
    try:
        audio_io = io.BytesIO(audio_bytes)
        audio_segment = AudioSegment.from_file(audio_io)
        mp3_io = io.BytesIO()
        audio_segment.export(mp3_io, format="mp3")
        mp3_io.seek(0)
       
        response_json = send_stt_request("recording.mp3", mp3_io.getvalue())
        transcription = response_json.get("text", "")
        if not transcription:
            logger.warning("No transcription generated from audio")
            return ""
        return transcription
    except Exception as e:
        logger.error(f"Speech-to-text error: {str(e)}")
        raise
async def generate_fallback_response(query: str):
    try:
        completion = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant responding to general queries in a conversational and professional tone."},
                {"role": "user", "content": query}
            ],
            max_tokens=150
        )
        return completion.choices[0].message.content
    except Exception as e:
        logger.error(f"Fallback GPT response error: {str(e)}")
        return "I'm sorry, I couldn't process your query at the moment. Please try again."
async def process_query(context, query: str, role: str, intent_data: dict = None):
    try:
        agent_instance = Agent()
        response_data = await agent_instance.process_query(context, query, role, intent_data)
        return response_data
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        raise
async def persist_message(session_id: str, query: str, response: str, role: str, audio_base64: str = None, map_data: dict = None, media_data: dict = None):
    try:
        session = await context_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
       
        history = session.get("chat_history", [])
        history.append({
            "role": role,
            "query": query,
            "response": response,
            "timestamp": int(datetime.now().timestamp()),
            "audio_base64": audio_base64,
            "map_data": map_data,
            "media_data": media_data
        })
       
        collection_name = f"sessions_{session_id}"
        await context_manager.db[collection_name].update_one(
            {"session_id": session_id},
            {"$set": {"chat_history": history[-10:], "updated_at": time.time()}}
        )
        logger.info(f"Persisted message for session {session_id}")
    except Exception as e:
        logger.error(f"Error persisting message for session {session_id}: {str(e)}")
        raise
@router.websocket("/ws/voice/{session_id}")
async def voice_websocket_endpoint(websocket: WebSocket, session_id: str):
    try:
        await verify_websocket_session(session_id)
        await websocket.accept()
        if session_id not in websocket_connections:
            websocket_connections[session_id] = []
        websocket_connections[session_id].append(websocket)
        logger.info(f"Voice WebSocket connected for session {session_id}. Total connections: {len(websocket_connections[session_id])}")
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                    logger.debug(f"Received ping for session {session_id}, sent pong")
                    continue
                audio_data = data.get("audio_data")
                if not audio_data:
                    logger.error(f"No audio data provided for session {session_id}")
                    await websocket.send_json({"error": "No audio data provided"})
                    continue
                try:
                    audio_bytes = base64.b64decode(audio_data)
                    logger.debug(f"Received audio data for session {session_id}: {len(audio_bytes)} bytes")
                    transcription = await speech_to_text(audio_bytes)
                    if not transcription:
                        logger.warning(f"No transcription generated for session {session_id}")
                        await websocket.send_json({"error": "No transcription generated from audio"})
                        continue
                    logger.debug(f"Transcribed audio for session {session_id}: {transcription}")
                    # Auto-detect language
                    lang = await detect_language(transcription)
                    logger.info(f"Detected language for session {session_id}: {lang}")
                    # For non-live mode + Indic languages: skip full pipeline, delay, play hardcoded audio
                    if not LIVE_MODE and lang in ['kn', 'te']:
                        # Still process query in background for persistence (no await to avoid delay)
                        asyncio.create_task(
                            (lambda: context_manager.process_query(session_id=session_id, query=transcription, role="candidate"))()
                        )
                        # Fixed 5-second delay
                        await asyncio.sleep(HARDCODED_DELAY_SECONDS)
                        try:
                            audio_bytes = load_pre_stored_audio(lang)
                            logger.info(f"Playing pre-stored {lang} audio after {HARDCODED_DELAY_SECONDS}s delay")
                        except Exception as e:
                            logger.error(f"Failed to load pre-stored audio for {lang}: {str(e)}")
                            await websocket.send_json({"error": f"Failed to load pre-stored audio: {str(e)}"})
                            continue
                        # Send dummy response (use transcription as content for display)
                        response = transcription  # Or a placeholder like "Leave policy explained."
                    else:
                        # Full live pipeline for English or live mode
                        query_en = transcription if lang == 'en' else await translate_text(transcription, target_lang='en', source_lang=lang)
                        response_en, media_data, history = await context_manager.process_query(
                            session_id=session_id,
                            query=query_en,
                            role="candidate"
                        )
                        tts_text_en = strip_markdown(response_en)
                        response = tts_text_en if lang == 'en' else await translate_text(tts_text_en, target_lang=lang, source_lang='en')
                        tts_text = response
                        if lang == 'en':
                            tts_headers = {
                                "Accept": "audio/mpeg",
                                "Content-Type": "application/json",
                                "xi-api-key": ELEVENLABS_API_KEY
                            }
                            tts_data = {
                                "text": tts_text,
                                "model_id": ELEVENLABS_MODEL_ID_TTS,
                                "voice_settings": {
                                    "stability": 0.5,
                                    "similarity_boost": 0.5
                                }
                            }
                            tts_response = requests.post(
                                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                                json=tts_data,
                                headers=tts_headers
                            )
                            if tts_response.status_code != 200:
                                logger.error(f"ElevenLabs TTS API error: {tts_response.text}")
                                await websocket.send_json({"error": f"Text-to-speech API error: {tts_response.text}"})
                                continue
                            audio_bytes = tts_response.content
                        else:
                            audio_bytes = generate_indic_tts(tts_text, lang)
                    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
                    response_message = {
                        "type": "response",
                        "role": "assistant",
                        "content": response,
                        "audio_base64": audio_base64,
                        "map_data": None,
                        "media_data": {} if 'media_data' not in locals() else media_data,
                        "timestamp": int(datetime.now().timestamp())
                    }
                    await websocket.send_json(response_message)
                    logger.debug(f"Sent voice response for session {session_id}")
                    # Persist (use original response_en if available)
                    persist_response = response_en if 'response_en' in locals() else response
                    await persist_message(
                        session_id=session_id,
                        query=transcription,
                        response=persist_response,
                        role="candidate",
                        audio_base64=audio_base64,
                        map_data=None,
                        media_data={} if 'media_data' not in locals() else media_data
                    )
                    # Broadcast
                    if session_id in websocket_connections:
                        for conn in websocket_connections[session_id]:
                            try:
                                if conn != websocket:
                                    await conn.send_json({
                                        "role": "candidate",
                                        "content": transcription,
                                        "timestamp": int(datetime.now().timestamp()),
                                        "type": "query"
                                    })
                                    await conn.send_json(response_message)
                                    logger.debug(f"Broadcasted voice query and response to WebSocket for session {session_id}")
                            except Exception as e:
                                logger.error(f"WebSocket broadcast failed for session {session_id}: {str(e)}")
                                websocket_connections[session_id].remove(conn)
                except ValueError as e:
                    logger.error(f"Invalid audio data for session {session_id}: {str(e)}")
                    await websocket.send_json({"error": "Invalid audio data format"})
                except Exception as e:
                    logger.error(f"Error processing voice input for session {session_id}: {str(e)}")
                    await websocket.send_json({"error": f"Failed to process voice input: {str(e)}"})
           
        except WebSocketDisconnect:
            logger.info(f"Voice WebSocket disconnected for session {session_id}. Remaining connections: {len(websocket_connections.get(session_id, [])) - 1}")
            websocket_connections[session_id].remove(websocket)
            if not websocket_connections[session_id]:
                del websocket_connections[session_id]
        except Exception as e:
            logger.error(f"WebSocket error for session {session_id}: {str(e)}")
            await websocket.send_json({"error": str(e)})
    except HTTPException as e:
        logger.error(f"Voice WebSocket connection rejected for session {session_id}: {e.detail}")
        await websocket.close(code=1008, reason=e.detail)
    except Exception as e:
        logger.error(f"Unexpected Voice WebSocket error for session {session_id}: {str(e)}")
        await websocket.close(code=1011, reason="Internal server error")
    finally:
        if session_id in websocket_connections and websocket in websocket_connections[session_id]:
            websocket_connections[session_id].remove(websocket)
            if not websocket_connections[session_id]:
                del websocket_connections[session_id]
            logger.info(f"Voice WebSocket connection closed for session {session_id}. Remaining connections: {len(websocket_connections.get(session_id, []))}")
@app.post("/voice/{session_id}")
async def process_voice(session_id: str, audio: UploadFile = File(...)):
    try:
        if not is_valid_uuid(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format. Must be a valid UUID.")
       
        logger.info(f"Processing voice input for session {session_id}")
        start_time = time.time()
        audio_content = await audio.read()
        if not audio_content:
            logger.error(f"No audio content received for session {session_id}")
            raise HTTPException(status_code=400, detail="No audio content provided")
       
        audio_io = io.BytesIO(audio_content)
        audio_segment = AudioSegment.from_file(audio_io)
        wav_io = io.BytesIO()
        audio_segment.export(wav_io, format="wav")
        wav_io.seek(0)
       
        headers = {
            "Accept": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }
        files = {
            "file": ("recording.wav", wav_io, "audio/wav"),
            "model_id": (None, ELEVENLABS_MODEL_ID_STT)
        }
        response = requests.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers=headers,
            files=files
        )
        if response.status_code != 200:
            logger.error(f"ElevenLabs STT API error: {response.text}")
            if response.status_code == 429:
                raise HTTPException(status_code=429, detail="The speech-to-text service is currently busy. Please try again later.")
            raise HTTPException(status_code=500, detail=f"Speech-to-text API error: {response.text}")
       
        transcription = response.json().get("text")
        if not transcription:
            logger.warning(f"No transcription received for session {session_id}")
            raise HTTPException(status_code=400, detail="No transcription could be generated from the audio")
       
        logger.info(f"Transcribed audio for session {session_id}: {transcription}")
        # Auto-detect language
        lang = detect_language_sync(transcription)
        logger.info(f"Detected language for session {session_id}: {lang}")
        # For non-live mode + Indic: skip full pipeline, delay, play hardcoded
        if not LIVE_MODE and lang in ['kn', 'te']:
            # Background persistence
            asyncio.create_task(
                (lambda: context_manager.process_query(session_id=session_id, query=transcription, role="candidate"))()
            )
            await asyncio.sleep(HARDCODED_DELAY_SECONDS)
            try:
                audio_bytes = load_pre_stored_audio(lang)
                logger.info(f"Playing pre-stored {lang} audio after {HARDCODED_DELAY_SECONDS}s delay")
            except Exception as e:
                logger.error(f"Failed to load pre-stored audio for {lang}: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Failed to load pre-stored audio: {str(e)}")
            response = transcription  # Dummy
        else:
            query_en = transcription if lang == 'en' else translate_text_sync(transcription, target_lang='en', source_lang=lang)
            response_en, media_data, history = await context_manager.process_query(session_id, query_en, "candidate")
            tts_text_en = strip_markdown(response_en)
            response = tts_text_en if lang == 'en' else translate_text_sync(tts_text_en, target_lang=lang, source_lang='en')
            tts_text = response
            if lang == 'en':
                tts_headers = {
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                    "xi-api-key": ELEVENLABS_API_KEY
                }
                tts_data = {
                    "text": tts_text,
                    "model_id": ELEVENLABS_MODEL_ID_TTS,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.5
                    }
                }
                tts_response = requests.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                    json=tts_data,
                    headers=tts_headers
                )
                if tts_response.status_code != 200:
                    logger.error(f"ElevenLabs TTS API error: {tts_response.text}")
                    raise HTTPException(status_code=500, detail=f"Text-to-speech API error: {tts_response.text}")
                audio_bytes = tts_response.content
            else:
                audio_bytes = generate_indic_tts(tts_text, lang)
       
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        logger.info(f"Generated audio response for session {session_id}")
       
        if session_id in websocket_connections:
            for ws in websocket_connections[session_id]:
                try:
                    await ws.send_json({
                        "role": "candidate",
                        "content": transcription,
                        "timestamp": time.time(),
                        "type": "query"
                    })
                    await ws.send_json({
                        "role": "assistant",
                        "content": response_en if 'response_en' in locals() else response,
                        "timestamp": time.time(),
                        "audio_base64": audio_base64,
                        "media_data": media_data if 'media_data' in locals() else {},
                        "type": "response"
                    })
                    logger.debug(f"Sent voice response via WebSocket for session {session_id}")
                except Exception as e:
                    logger.error(f"WebSocket send failed for session {session_id}: {str(e)}")
                    websocket_connections[session_id].remove(ws)
       
        logger.info(f"Voice processing time: {time.time() - start_time:.2f} seconds")
        return JSONResponse(content={
            "response": response_en if 'response_en' in locals() else response,
            "audio_base64": audio_base64,
            "media_data": media_data if 'media_data' in locals() else {}
        })
    except HTTPException as e:
        logger.error(f"HTTP error in voice processing: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error processing voice for session {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing voice: {str(e)}")
app.include_router(router)