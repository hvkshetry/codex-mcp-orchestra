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
from fastapi import FastAPI, HTTPException, UploadFile, File, Body, Request
from fastapi.responses import JSONResponse
from faster_whisper import WhisperModel
import tempfile
import os
import base64

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Enable debug logging for faster-whisper
logging.getLogger("faster_whisper").setLevel(logging.DEBUG)

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
async def transcribe_audio(request: TranscribeRequest = Body(...)):
    """
    Transcribe audio from base64 encoded data (JSON request)
    
    Args:
        request: JSON request with base64 audio_data
    
    Returns:
        JSON with transcription and metadata
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Decode base64 audio
        logger.info(f"Received audio_data of length: {len(request.audio_data)}")
        audio_bytes = base64.b64decode(request.audio_data)
        logger.info(f"Decoded to {len(audio_bytes)} bytes")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            tmp_file.write(audio_bytes)
            tmp_path = tmp_file.name
        
        # Transcribe
        logger.info(f"Transcribing audio from {tmp_path}")
        
        # Check audio file size for debugging
        import os
        file_size = os.path.getsize(tmp_path)
        logger.info(f"Audio file size: {file_size} bytes")
        
        # Optimized for fast voice commands (5-10 seconds)
        segments, info = model.transcribe(
            tmp_path,
            language="en",
            task="transcribe",
            # Speed optimization
            beam_size=1,  # Greedy search for fastest speed
            best_of=1,  # Single hypothesis only
            patience=1.0,  # Must be > 0
            length_penalty=1.0,
            # Disable fallback for speed - rely on post-processing guard
            temperature=0.0,  # Single temperature, no fallbacks
            compression_ratio_threshold=None,  # Disable compression check
            log_prob_threshold=None,  # Disable log prob check
            no_speech_threshold=0.6,  # Default threshold
            # Context handling
            condition_on_previous_text=False,  # Avoid runaway from prior segment
            initial_prompt=None,
            # VAD & timestamps
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            without_timestamps=True,
            # Token limits for short commands
            max_new_tokens=128,  # Limit output for voice commands
            # Token suppression
            suppress_blank=True,
            suppress_tokens=[-1]  # Default suppression list
        )
        
        logger.info(f"Audio duration: {info.duration} seconds")
        logger.info(f"Detected language: {info.language} (probability: {info.language_probability})")
        
        # Collect results
        transcription = " ".join([segment.text.strip() for segment in segments])
        
        # Post-processing guard: detect and fix repetitions
        import gzip
        if transcription:
            # Check compression ratio for repetition detection
            text_bytes = transcription.encode('utf-8')
            compressed = gzip.compress(text_bytes)
            compression_ratio = len(text_bytes) / len(compressed)
            
            if compression_ratio > 3.5:
                logger.warning(f"High compression ratio detected: {compression_ratio:.2f}, applying repetition fix")
                
                # Split into sentences and remove consecutive duplicates
                sentences = transcription.replace('?', '?|').replace('.', '.|').replace('!', '!|').split('|')
                unique_sentences = []
                for sentence in sentences:
                    sentence = sentence.strip()
                    if sentence and (not unique_sentences or sentence != unique_sentences[-1]):
                        unique_sentences.append(sentence)
                
                # Also check for repeated phrases within sentences
                original_transcription = transcription
                transcription = ' '.join(unique_sentences)
                
                # If still repetitive, truncate to first occurrence
                words = transcription.split()
                if len(words) > 10:
                    for n in [8, 7, 6, 5, 4, 3]:  # Check for n-gram repetitions
                        for i in range(len(words) - n):
                            ngram = ' '.join(words[i:i+n])
                            rest = ' '.join(words[i+n:])
                            if ngram in rest:
                                # Found repetition, truncate
                                transcription = ' '.join(words[:i+n])
                                logger.warning(f"Truncated repetitive {n}-gram at position {i}")
                                break
                        if len(transcription.split()) < len(words):
                            break
                
                logger.info(f"Fixed repetition: {len(original_transcription)} -> {len(transcription)} chars")
        
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
        error_msg = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
        logger.error(f"Transcription error: {error_msg}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        if 'tmp_path' in locals():
            try:
                os.unlink(tmp_path)
            except:
                pass
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/transcribe/file")
async def transcribe_file(audio: UploadFile = File(...)):
    """
    Transcribe audio file upload
    
    Args:
        audio: Audio file upload (wav, mp3, etc.)
    
    Returns:
        JSON with transcription and metadata
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(audio.filename).suffix) as tmp_file:
            content = await audio.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        # Check audio file size for debugging
        file_size = os.path.getsize(tmp_path)
        logger.info(f"Transcribing audio file: {audio.filename} (size: {file_size} bytes)")
        
        # Optimized for fast voice commands (5-10 seconds)
        segments, info = model.transcribe(
            tmp_path,
            language="en",
            task="transcribe",
            # Speed optimization
            beam_size=1,  # Greedy search for fastest speed
            best_of=1,  # Single hypothesis only
            patience=1.0,  # Must be > 0
            length_penalty=1.0,
            # Disable fallback for speed - rely on post-processing guard
            temperature=0.0,  # Single temperature, no fallbacks
            compression_ratio_threshold=None,  # Disable compression check
            log_prob_threshold=None,  # Disable log prob check
            no_speech_threshold=0.6,  # Default threshold
            # Context handling
            condition_on_previous_text=False,  # Avoid runaway from prior segment
            initial_prompt=None,
            # VAD & timestamps
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            without_timestamps=True,
            # Token limits for short commands
            max_new_tokens=128,  # Limit output for voice commands
            # Token suppression
            suppress_blank=True,
            suppress_tokens=[-1]  # Default suppression list
        )
        
        logger.info(f"Audio duration: {info.duration} seconds")
        logger.info(f"Detected language: {info.language} (probability: {info.language_probability})")
        
        # Collect results
        transcription = " ".join([segment.text.strip() for segment in segments])
        
        # Post-processing guard: detect and fix repetitions
        import gzip
        if transcription:
            # Check compression ratio for repetition detection
            text_bytes = transcription.encode('utf-8')
            compressed = gzip.compress(text_bytes)
            compression_ratio = len(text_bytes) / len(compressed)
            
            if compression_ratio > 3.5:
                logger.warning(f"High compression ratio detected: {compression_ratio:.2f}, applying repetition fix")
                
                # Split into sentences and remove consecutive duplicates
                sentences = transcription.replace('?', '?|').replace('.', '.|').replace('!', '!|').split('|')
                unique_sentences = []
                for sentence in sentences:
                    sentence = sentence.strip()
                    if sentence and (not unique_sentences or sentence != unique_sentences[-1]):
                        unique_sentences.append(sentence)
                
                # Also check for repeated phrases within sentences
                original_transcription = transcription
                transcription = ' '.join(unique_sentences)
                
                # If still repetitive, truncate to first occurrence
                words = transcription.split()
                if len(words) > 10:
                    for n in [8, 7, 6, 5, 4, 3]:  # Check for n-gram repetitions
                        for i in range(len(words) - n):
                            ngram = ' '.join(words[i:i+n])
                            rest = ' '.join(words[i+n:])
                            if ngram in rest:
                                # Found repetition, truncate
                                transcription = ' '.join(words[:i+n])
                                logger.warning(f"Truncated repetitive {n}-gram at position {i}")
                                break
                        if len(transcription.split()) < len(words):
                            break
                
                logger.info(f"Fixed repetition: {len(original_transcription)} -> {len(transcription)} chars")
        
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
        error_msg = str(e) if str(e) else f"{type(e).__name__}: {repr(e)}"
        logger.error(f"File transcription error: {error_msg}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        if 'tmp_path' in locals():
            try:
                os.unlink(tmp_path)
            except:
                pass
        raise HTTPException(status_code=500, detail=error_msg)

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
            word_timestamps=True,
            no_speech_threshold=None,  # Disable no-speech detection
            log_prob_threshold=None,  # Disable quality filtering
            vad_filter=False  # Disable VAD
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