#!/usr/bin/env python3
"""
Whisper Transcription Service
Provides speech-to-text using faster-whisper
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, Body
from fastapi.responses import JSONResponse
from faster_whisper import WhisperModel
import tempfile
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Whisper Transcription Service")

class TranscribeRequest(BaseModel):
    """Request model for transcription"""
    audio_data: str  # Base64 encoded audio

# Global model instance
model: Optional[WhisperModel] = None

def load_model(model_size: str = "base.en"):
    """Load the Whisper model"""
    global model
    if model is None:
        logger.info(f"Loading Whisper model: {model_size}")
        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8"
        )
        logger.info("Model loaded successfully")
    return model

@app.on_event("startup")
async def startup_event():
    """Initialize the model on startup"""
    load_model()

@app.post("/transcribe")
async def transcribe_audio(
    request: Optional[TranscribeRequest] = None,
    audio: Optional[UploadFile] = File(None)
):
    """
    Transcribe audio file to text
    
    Args:
        request: JSON request with base64 audio_data
        audio: Audio file upload (wav, mp3, etc.)
    
    Returns:
        JSON with transcription and metadata
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Handle JSON request with base64 audio (from bridge service)
        if request and request.audio_data:
            import base64
            audio_bytes = base64.b64decode(request.audio_data)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
                tmp_file.write(audio_bytes)
                tmp_path = tmp_file.name
        # Handle file upload
        elif audio:
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(audio.filename).suffix) as tmp_file:
                content = await audio.read()
                tmp_file.write(content)
                tmp_path = tmp_file.name
        else:
            raise HTTPException(status_code=400, detail="Either request with audio_data or audio file must be provided")
        
        # Transcribe
        logger.info(f"Transcribing audio from {tmp_path}")
        
        # Check audio file size for debugging
        import os
        file_size = os.path.getsize(tmp_path)
        logger.info(f"Audio file size: {file_size} bytes")
        
        segments, info = model.transcribe(
            tmp_path,
            beam_size=5,
            language="en",
            task="transcribe"
        )
        
        # Collect results
        transcription = " ".join([segment.text.strip() for segment in segments])
        
        # Log transcription result
        if transcription:
            logger.info(f"Transcribed: '{transcription[:100]}...' (length: {len(transcription)})")
        else:
            logger.warning("Empty transcription result")
        
        # Clean up
        os.unlink(tmp_path)
        
        return JSONResponse(content={
            "transcription": transcription,
            "language": info.language,
            "duration": info.duration,
            "language_probability": info.language_probability
        })
        
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        if 'tmp_path' in locals():
            try:
                os.unlink(tmp_path)
            except:
                pass
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transcribe/stream")
async def transcribe_stream(audio: UploadFile = File(...)):
    """
    Transcribe audio with word-level timestamps
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            content = await audio.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        # Transcribe with word timestamps
        segments, info = model.transcribe(
            tmp_path,
            beam_size=5,
            language="en",
            task="transcribe",
            word_timestamps=True
        )
        
        # Collect segments with timestamps
        result_segments = []
        for segment in segments:
            seg_data = {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip()
            }
            if segment.words:
                seg_data["words"] = [
                    {
                        "start": word.start,
                        "end": word.end,
                        "word": word.word.strip(),
                        "probability": word.probability
                    }
                    for word in segment.words
                ]
            result_segments.append(seg_data)
        
        # Clean up
        os.unlink(tmp_path)
        
        return JSONResponse(content={
            "segments": result_segments,
            "language": info.language,
            "duration": info.duration
        })
        
    except Exception as e:
        logger.error(f"Stream transcription error: {str(e)}")
        if 'tmp_path' in locals():
            try:
                os.unlink(tmp_path)
            except:
                pass
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "model_loaded": model is not None
    }

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=7001,
        log_level="info"
    )