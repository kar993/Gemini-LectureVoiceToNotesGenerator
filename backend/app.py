import os
import io
import json
import time
import math
import hashlib
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import google.generativeai as genai
from pydub import AudioSegment

# --- Configuration ---
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is required")

genai.configure(api_key=GEMINI_KEY)

CACHE_DIR = Path("./cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Tune these
MAX_ALLOWED_MINUTES = 60  # allow up to 60 minutes
CHUNK_MS = 15 * 60 * 1000  # 15 minutes per chunk (in ms)
TRANSCRIBE_PAUSE = 0.2  # seconds between chunk transcriptions to be polite to API

app = Flask(__name__)
CORS(app)

def get_gemini_model():
    return genai.GenerativeModel("gemini-2.0-flash")

# ---------- Utilities ----------

def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def make_cache_path(audio_hash: str) -> Path:
    p = CACHE_DIR / audio_hash
    p.mkdir(parents=True, exist_ok=True)
    return p

def read_cache_file(cache_path: Path, name: str):
    f = cache_path / name
    if f.exists():
        return f.read_bytes() if name.endswith((".wav", ".bin")) else f.read_text(encoding="utf-8")
    return None

def write_cache_file(cache_path: Path, name: str, data, binary: bool = False):
    f = cache_path / name
    if binary:
        f.write_bytes(data)
    else:
        f.write_text(data, encoding="utf-8")

def validate_audio_file(file_stream, filename):
    if not filename:
        return False, "No file uploaded."
    parts = filename.rsplit('.', 1)
    if len(parts) < 2:
        return False, "Uploaded file has no extension."
    ext = parts[1].lower()
    if ext not in ['mp3', 'wav']:
        return False, f"Unsupported file type: .{ext}. Only MP3 and WAV are allowed."
    try:
        file_stream.seek(0)
        file_bytes = io.BytesIO(file_stream.read())
        audio = AudioSegment.from_file(file_bytes, format=ext)
        duration_minutes = len(audio) / (1000 * 60)
        if duration_minutes > MAX_ALLOWED_MINUTES:
            return False, f"Audio file is too long ({duration_minutes:.2f} mins). Maximum allowed is {MAX_ALLOWED_MINUTES} minutes."
        file_stream.seek(0)
        return True, None
    except Exception as e:
        return False, f"Could not process audio file: {str(e)}"

def split_audio_into_chunks(audio_segment: AudioSegment, chunk_ms: int = CHUNK_MS):
    total_ms = len(audio_segment)
    chunks = []
    num_chunks = math.ceil(total_ms / chunk_ms)
    for i in range(num_chunks):
        start = i * chunk_ms
        end = min((i + 1) * chunk_ms, total_ms)
        chunk = audio_segment[start:end]
        buf = io.BytesIO()
        # export as WAV for reliable transcription
        chunk.export(buf, format="wav")
        buf.seek(0)
        chunks.append(buf.read())
    return chunks

# ---------- Model interaction helpers ----------

def transcribe_chunk(model, chunk_bytes, idx):
    """
    Send one audio chunk to Gemini for transcription. Returns string transcript.
    """
    audio_part = {"mime_type": "audio/wav", "data": chunk_bytes}
    transcribe_prompt = "Transcribe the audio to clear English text only. Preserve words and punctuation; do not add commentary."
    try:
        resp = model.generate_content([transcribe_prompt, audio_part])
        return (resp.text or "").strip()
    except Exception as e:
        return f"[UNTRANSCRIBED CHUNK {idx+1}: error {str(e)}]"

def summarize_chunk_text(model, chunk_transcript, idx):
    """
    Summarize a chunk transcript into 1-3 concise sentences.
    """
    prompt = f"""
You are an assistant that produces concise chunk-level summaries for study.
Summarize the following chunk transcript in 1-3 short sentences that capture the main points and any important terminology.

Chunk transcript:
{chunk_transcript}
"""
    try:
        resp = model.generate_content([prompt])
        return (resp.text or "").strip()
    except Exception as e:
        return f"[UNSUMMARIZED CHUNK {idx+1}: error {str(e)}]"

# ---------- High-level pipeline ----------

def prepare_transcript_and_summaries(audio_file):
    """
    Given werkzeug FileStorage audio_file:
     - compute hash
     - if transcript exists in cache -> load chunk_summaries and transcript
     - else: split -> transcribe each chunk -> summarize each chunk -> write to cache
    Returns: (audio_hash, cache_path, transcript_text, chunk_summaries_list)
    """
    # read bytes and compute hash
    audio_file.stream.seek(0)
    audio_bytes = audio_file.stream.read()
    audio_hash = sha256_bytes(audio_bytes)
    cache_path = make_cache_path(audio_hash)

    # quick cache check for transcript + chunk summaries
    cached_transcript = read_cache_file(cache_path, "transcript.txt")
    cached_chunk_summaries = read_cache_file(cache_path, "chunk_summaries.json")
    if cached_transcript is not None and cached_chunk_summaries is not None:
        try:
            chunk_summaries = json.loads(cached_chunk_summaries)
        except Exception:
            chunk_summaries = []
        return audio_hash, cache_path, cached_transcript, chunk_summaries

    # not cached or incomplete -> generate
    # load audio into AudioSegment
    # determine format
    filename = getattr(audio_file, "filename", "audio")
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else "wav"
    audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format=ext)

    # split into chunks
    chunks = split_audio_into_chunks(audio_segment, chunk_ms=CHUNK_MS)
    model = get_gemini_model()

    transcripts = []
    summaries = []
    for idx, chunk_bytes in enumerate(chunks):
        # transcribe
        t = transcribe_chunk(model, chunk_bytes, idx)
        transcripts.append(t)
        # small pause
        time.sleep(TRANSCRIBE_PAUSE)
        # summarize chunk text (safe to provide transcript as text)
        s = summarize_chunk_text(model, t, idx)
        summaries.append({"index": idx, "summary": s, "transcript_snippet": t[:600]})
        time.sleep(TRANSCRIBE_PAUSE)

    combined_transcript = "\n\n--- CHUNK BOUNDARY ---\n\n".join(transcripts)

    # write transcript & chunk summaries to cache
    write_cache_file(cache_path, "transcript.txt", combined_transcript)
    write_cache_file(cache_path, "chunk_summaries.json", json.dumps(summaries, ensure_ascii=False, indent=2))

    return audio_hash, cache_path, combined_transcript, summaries

# ---------- Endpoints (notes / flashcards / quizzes) ----------

@app.route("/generate_notes", methods=["POST"])
def generate_notes():
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    audio_file = request.files['audio']
    filename = audio_file.filename
    is_valid, err = validate_audio_file(audio_file.stream, filename)
    if not is_valid:
        return jsonify({"error": err}), 400

    try:
        audio_hash, cache_path, transcript_text, chunk_summaries = prepare_transcript_and_summaries(audio_file)

        # If notes cached, return immediately
        cached_notes = read_cache_file(cache_path, "notes.txt")
        if cached_notes is not None:
            return jsonify({"notes": cached_notes, "cached": True}), 200

        # Build synthesis prompt using chunk summaries (safer than full transcript)
        concatenated_chunk_summaries = "\n\n".join([f"Chunk {c['index']+1}: {c['summary']}" for c in chunk_summaries])

        prompt_text = f"""
You are an AI assistant specialized in creating detailed study notes from class content.
Below are concise chunk-level summaries (1-3 sentences each) created from the audio transcript.
Use them to produce:

1) High-Level Overview: one short paragraph summarizing the main topics.
2) Concept-Wise Breakdown: for each major concept, provide a heading, definition/explanation, example(s), and any formulas if present.
3) Bullet Point Summary: the most important takeaways suitable for quick review.

Chunk summaries:
{concatenated_chunk_summaries}

Produce the notes in clear English.
"""
        model = get_gemini_model()
        resp = model.generate_content([prompt_text])
        notes_content = resp.text or ""

        # cache notes
        write_cache_file(cache_path, "notes.txt", notes_content)

        return jsonify({"notes": notes_content, "cached": False}), 200

    except Exception as e:
        return jsonify({"error": f"Failed to generate notes: {str(e)}"}), 500

@app.route("/generate_flashcards", methods=["POST"])
def generate_flashcards():
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    audio_file = request.files['audio']
    filename = audio_file.filename
    is_valid, err = validate_audio_file(audio_file.stream, filename)
    if not is_valid:
        return jsonify({"error": err}), 400

    try:
        audio_hash, cache_path, transcript_text, chunk_summaries = prepare_transcript_and_summaries(audio_file)

        cached_flashcards = read_cache_file(cache_path, "flashcards.json")
        if cached_flashcards is not None:
            return jsonify({"flashcards": json.loads(cached_flashcards), "cached": True}), 200

        # Use chunk summaries as input to generate flashcards
        concatenated_chunk_summaries = "\n\n".join([f"Chunk {c['index']+1}: {c['summary']}" for c in chunk_summaries])
        prompt_text = f"""
You are an AI assistant that makes study flashcards from class content. Use the chunk summaries below to identify 3-10 good flashcards.
Format strictly as JSON array of objects: [{{"front":"...","back":"..."}}], where 'front' is a concise prompt/question and 'back' is the concise answer/explanation.

Chunk summaries:
{concatenated_chunk_summaries}
"""
        model = get_gemini_model()
        resp = model.generate_content([prompt_text])
        flashcards_text = resp.text or ""

        # strip code block if needed
        if flashcards_text.strip().startswith("```json"):
            flashcards_text = flashcards_text.strip().lstrip("```json").rstrip("```").strip()

        flashcards_data = json.loads(flashcards_text)
        write_cache_file(cache_path, "flashcards.json", json.dumps(flashcards_data, ensure_ascii=False, indent=2))
        return jsonify({"flashcards": flashcards_data, "cached": False}), 200

    except json.JSONDecodeError:
        return jsonify({"error": "Gemini returned invalid JSON for flashcards. Please try again."}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to generate flashcards: {str(e)}"}), 500

@app.route("/generate_quizzes", methods=["POST"])
def generate_quizzes():
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    audio_file = request.files['audio']
    filename = audio_file.filename
    is_valid, err = validate_audio_file(audio_file.stream, filename)
    if not is_valid:
        return jsonify({"error": err}), 400

    try:
        audio_hash, cache_path, transcript_text, chunk_summaries = prepare_transcript_and_summaries(audio_file)

        cached_quiz = read_cache_file(cache_path, "quiz.json")
        if cached_quiz is not None:
            return jsonify({"quiz": json.loads(cached_quiz), "cached": True}), 200

        concatenated_chunk_summaries = "\n\n".join([f"Chunk {c['index']+1}: {c['summary']}" for c in chunk_summaries])
        prompt_text = f"""
You are an AI assistant specialized in generating multiple-choice quiz questions from class content.
From the chunk summaries below, create exactly 5 multiple-choice questions (MCQs). For each question:
 - Provide the question text.
 - Provide 4 possible answer choices labeled A, B, C, D (only one correct).
 - Indicate the correct choice with the 'correct_answer' field.

Format output as strict JSON array of objects.

Chunk summaries:
{concatenated_chunk_summaries}
"""
        model = get_gemini_model()
        resp = model.generate_content([prompt_text])
        quiz_text = resp.text or ""

        if quiz_text.strip().startswith("```json"):
            quiz_text = quiz_text.strip().lstrip("```json").rstrip("```").strip()

        quiz_data = json.loads(quiz_text)
        write_cache_file(cache_path, "quiz.json", json.dumps(quiz_data, ensure_ascii=False, indent=2))
        return jsonify({"quiz": quiz_data, "cached": False}), 200

    except json.JSONDecodeError:
        return jsonify({"error": "Gemini returned invalid JSON for quizzes. Please try again."}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to generate quizzes: {str(e)}"}), 500

# Basic health/status
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(debug=True, port=5000)
