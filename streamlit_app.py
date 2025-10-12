# streamlit_app.py
# Single-file Streamlit app that performs:
# - upload audio (mp3/wav)
# - chunking + transcription via Google Gemini API (google-generativeai)
# - incremental chunk summarization
# - synthesis into notes / flashcards / quizzes
# - filesystem caching per-audio (sha256)
#
# Prereqs: pip install streamlit pydub python-dotenv google-generativeai
# ffmpeg must be installed on the host and available in PATH.

import os
import io
import json
import time
import math
import hashlib
import tempfile
from pathlib import Path

import streamlit as st
from pydub import AudioSegment
from dotenv import load_dotenv

# Try to import the official Google generative sdk
try:
    import google.generativeai as genai
except Exception as e:
    genai = None

# ---------- Configuration ----------
load_dotenv()  # allow .env fallback if user put GEMINI_API_KEY there

# Configurable parameters
CHUNK_MS = int(os.environ.get("CHUNK_MS_MS", 5 * 60 * 1000))  # default 5 minutes per chunk
CHUNK_OVERLAP_MS = int(os.environ.get("CHUNK_OVERLAP_MS", 5000))  # 5s overlap
MIN_FINAL_CHUNK_MS = int(os.environ.get("MIN_FINAL_CHUNK_MS", 30 * 1000))  # 30s min before merging
MAX_ALLOWED_MINUTES = int(os.environ.get("MAX_ALLOWED_MINUTES", 60))
TRANSCRIBE_PAUSE = float(os.environ.get("TRANSCRIBE_PAUSE", 0.2))

CACHE_DIR = Path(os.environ.get("CACHE_DIR", "./cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Obtain GEMINI API key (prefer Streamlit secrets, then env)
GEMINI_KEY = None
try:
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
except Exception:
    GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_KEY:
    st.warning("GEMINI_API_KEY not found in Streamlit secrets or environment. Add it to run model calls.")
else:
    if genai:
        genai.configure(api_key=GEMINI_KEY)
    else:
        st.error("google-generativeai package not installed or import failed. Install it first (pip install google-generativeai).")

# ---------- Helpers ----------

def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def make_cache_path(h: str) -> Path:
    p = CACHE_DIR / h
    p.mkdir(parents=True, exist_ok=True)
    return p

def read_cache_text(cache_path: Path, name: str):
    f = cache_path / name
    if f.exists():
        return f.read_text(encoding="utf-8")
    return None

def write_cache_text(cache_path: Path, name: str, text: str):
    f = cache_path / name
    f.write_text(text, encoding="utf-8")

def validate_audio_bytes(file_bytes: bytes, filename: str):
    """
    Validate type and duration. Returns (ok, error_message or duration_seconds).
    """
    parts = filename.rsplit(".", 1)
    if len(parts) < 2:
        return False, "File has no extension."
    ext = parts[1].lower()
    if ext not in ("mp3", "wav"):
        return False, "Unsupported file type. Use MP3 or WAV."

    try:
        audio = AudioSegment.from_file(io.BytesIO(file_bytes), format=ext)
        duration_seconds = len(audio) / 1000.0
        if duration_seconds > MAX_ALLOWED_MINUTES * 60:
            return False, f"Audio too long ({duration_seconds/60:.1f} minutes). Max is {MAX_ALLOWED_MINUTES} minutes."
        return True, duration_seconds
    except Exception as e:
        return False, f"Could not parse audio file: {e}"

def split_audio_with_overlap(audio_segment: AudioSegment, chunk_ms: int = CHUNK_MS,
                             overlap_ms: int = CHUNK_OVERLAP_MS, min_final_ms: int = MIN_FINAL_CHUNK_MS):
    """
    Splits AudioSegment into chunks with overlap. Merges last tiny remainder into previous chunk.
    Returns list of dicts: {"bytes": b, "start_ms": s, "end_ms": e}
    """
    total_ms = len(audio_segment)
    starts = list(range(0, total_ms, chunk_ms))
    chunks = []
    for i, start in enumerate(starts):
        end = min(start + chunk_ms, total_ms)
        # extend end by overlap if not last
        if i < len(starts) - 1:
            end = min(end + overlap_ms, total_ms)
        if end <= start:
            continue
        seg = audio_segment[start:end]
        buf = io.BytesIO()
        seg.export(buf, format="wav")
        buf.seek(0)
        chunks.append({"bytes": buf.read(), "start_ms": start, "end_ms": end})

    # merge last if too short
    if len(chunks) >= 2:
        last = chunks[-1]
        last_len = last["end_ms"] - last["start_ms"]
        if last_len < min_final_ms:
            prev = chunks[-2]
            merged_seg = audio_segment[prev["start_ms"]: last["end_ms"]]
            buf = io.BytesIO()
            merged_seg.export(buf, format="wav")
            buf.seek(0)
            prev["bytes"] = buf.read()
            prev["end_ms"] = last["end_ms"]
            chunks.pop()
    return chunks

def get_gemini_model():
    if not genai:
        raise RuntimeError("Google generative SDK not available")
    return genai.GenerativeModel("gemini-2.0-flash")

def transcribe_chunk(model, chunk_bytes, idx):
    audio_part = {"mime_type": "audio/wav", "data": chunk_bytes}
    prompt = "Transcribe the audio into clear English text. Preserve punctuation, do not add commentary."
    try:
        resp = model.generate_content([prompt, audio_part])
        return (resp.text or "").strip()
    except Exception as e:
        return f"[UNTRANSCRIBED_CHUNK_{idx+1}: error {e}]"

def summarize_chunk_text(model, chunk_transcript, idx):
    prompt = f"""You are an assistant that produces short chunk-level summaries useful for study notes.
Summarize the transcript below in 1-3 sentences capturing the main points and important terms.

Chunk transcript:
{chunk_transcript}
"""
    try:
        resp = model.generate_content([prompt])
        return (resp.text or "").strip()
    except Exception as e:
        return f"[UNSUMMARIZED_CHUNK_{idx+1}: error {e}]"

# ---------- High-level pipeline (caching + incremental summarization) ----------

def prepare_transcript_and_summaries_from_bytes(file_bytes: bytes, filename: str, progress_callback=None):
    """
    Returns tuple: (audio_hash, cache_path, combined_transcript_text, chunk_summaries_list)
    chunk_summaries_list is a list of dicts: {"index": int, "summary": str, "transcript_snippet": str}
    If cached found, returns cached values.
    progress_callback: function(text, value) to report progress to UI (optional)
    """
    audio_hash = sha256_bytes(file_bytes)
    cache_path = make_cache_path(audio_hash)

    # cached?
    cached_transcript = read_cache_text(cache_path, "transcript.txt")
    cached_chunk_summaries = read_cache_text(cache_path, "chunk_summaries.json")
    if cached_transcript is not None and cached_chunk_summaries is not None:
        try:
            summaries = json.loads(cached_chunk_summaries)
        except Exception:
            summaries = []
        return audio_hash, cache_path, cached_transcript, summaries

    # Not cached -> process
    parts = filename.rsplit(".", 1)
    ext = parts[1].lower() if len(parts) > 1 else "wav"
    audio_segment = AudioSegment.from_file(io.BytesIO(file_bytes), format=ext)
    chunks = split_audio_with_overlap(audio_segment, chunk_ms=CHUNK_MS)

    model = get_gemini_model()

    transcripts = []
    summaries = []
    total = len(chunks)
    for idx, chunk in enumerate(chunks):
        if progress_callback:
            progress_callback(f"Transcribing chunk {idx+1}/{total}...", int((idx/total) * 100))
        t = transcribe_chunk(model, chunk["bytes"], idx)
        transcripts.append(t)
        # summary
        if progress_callback:
            progress_callback(f"Summarizing chunk {idx+1}/{total}...", int(((idx+0.5)/total) * 100))
        s = summarize_chunk_text(model, t, idx)
        summaries.append({"index": idx, "summary": s, "transcript_snippet": t[:800]})
        time.sleep(TRANSCRIBE_PAUSE)  # polite pause

    combined_transcript = "\n\n--- CHUNK BOUNDARY ---\n\n".join(transcripts)
    write_cache_text(cache_path, "transcript.txt", combined_transcript)
    write_cache_text(cache_path, "chunk_summaries.json", json.dumps(summaries, ensure_ascii=False, indent=2))

    if progress_callback:
        progress_callback("Done chunk processing", 100)
    return audio_hash, cache_path, combined_transcript, summaries

def synthesize_notes_from_summaries(model, chunk_summaries):
    concatenated = "\n\n".join([f"Chunk {c['index']+1}: {c['summary']}" for c in chunk_summaries])
    prompt = f"""
You are an AI assistant specialized in creating detailed study notes from chunk summaries.
Produce:
1) High-level overview (one short paragraph).
2) Concept-wise breakdown with headings, explanations, examples, and formulas if applicable.
3) Bullet-point review list of key takeaways.

Chunk summaries:
{concatenated}
"""
    resp = model.generate_content([prompt])
    return resp.text or ""

def generate_flashcards_from_summaries(model, chunk_summaries):
    concatenated = "\n\n".join([f"Chunk {c['index']+1}: {c['summary']}" for c in chunk_summaries])
    prompt = f"""
You are an assistant that produces study flashcards. From the chunk summaries below, produce 3-10 flashcards.
Format strictly as JSON array: [{{"front":"...", "back":"..."}}]]
Chunk summaries:
{concatenated}
"""
    resp = model.generate_content([prompt])
    text = resp.text or ""
    # strip fences if present
    if text.strip().startswith("```json"):
        text = text.strip().lstrip("```json").rstrip("```").strip()
    return json.loads(text)

def generate_quiz_from_summaries(model, chunk_summaries):
    concatenated = "\n\n".join([f"Chunk {c['index']+1}: {c['summary']}" for c in chunk_summaries])
    prompt = f"""
You are an assistant that generates 3 multiple-choice questions (MCQs) from chunk summaries.
For each question provide: "question", "choices" (object mapping 'A'.. to text OR array), and "correct_answer" (letter 'A'..).
Return strict JSON array.
Chunk summaries:
{concatenated}
"""
    resp = model.generate_content([prompt])
    text = resp.text or ""
    if text.strip().startswith("```json"):
        text = text.strip().lstrip("```json").rstrip("```").strip()
    return json.loads(text)

# ---------- Streamlit UI ----------

st.set_page_config(page_title="Gemini Class Assistant (Streamlit)", layout="centered")
st.title("Gemini Class Assistant — Streamlit (All-in-one)")

st.markdown(
    f"**Chunk size:** {CHUNK_MS//1000//60} min  **Overlap:** {CHUNK_OVERLAP_MS/1000:.0f}s  **Max:** {MAX_ALLOWED_MINUTES} min"
)

uploaded = st.file_uploader("Upload MP3/WAV lecture (≤ {} min)".format(MAX_ALLOWED_MINUTES), type=["mp3", "wav"])

# Session UI elements for progress and status
progress_bar = st.progress(0)
progress_text = st.empty()
result_area = st.empty()

def progress_cb(text, pct):
    progress_text.text(text)
    progress_bar.progress(min(max(int(pct), 0), 100))

if uploaded is not None:
    uploaded_bytes = uploaded.read()
    ok, dur_or_err = validate_audio_bytes(uploaded_bytes, uploaded.name)
    if not ok:
        st.error(dur_or_err)
    else:
        minutes = dur_or_err / 60.0
        st.info(f"File OK — duration {minutes:.2f} minutes")
        # options
        col1, col2, col3 = st.columns(3)
        if col1.button("Generate Notes"):
            # run pipeline
            with st.spinner("Processing... (this may take some minutes)"):
                try:
                    audio_hash, cache_path, transcript_text, chunk_summaries = prepare_transcript_and_summaries_from_bytes(
                        uploaded_bytes, uploaded.name, progress_callback=progress_cb
                    )
                    # check cache for notes
                    notes_cached = read_cache_text(cache_path, "notes.txt")
                    model = get_gemini_model()
                    if notes_cached:
                        result_area.text_area("Notes (cached)", value=notes_cached, height=360)
                        st.success("Notes returned from cache")
                    else:
                        progress_cb("Synthesizing final notes...", 95)
                        notes = synthesize_notes_from_summaries(model, chunk_summaries)
                        write_cache_text(cache_path, "notes.txt", notes)
                        progress_cb("Done", 100)
                        result_area.text_area("Notes", value=notes, height=360)
                except Exception as e:
                    st.error(f"Failed to generate notes: {e}")

        if col2.button("Generate Flashcards"):
            with st.spinner("Processing..."):
                try:
                    audio_hash, cache_path, transcript_text, chunk_summaries = prepare_transcript_and_summaries_from_bytes(
                        uploaded_bytes, uploaded.name, progress_callback=progress_cb
                    )
                    flash_cached = read_cache_text(cache_path, "flashcards.json")
                    model = get_gemini_model()
                    if flash_cached:
                        flashcards = json.loads(flash_cached)
                        st.success("Flashcards returned from cache")
                    else:
                        progress_cb("Generating flashcards...", 95)
                        flashcards = generate_flashcards_from_summaries(model, chunk_summaries)
                        write_cache_text(cache_path, "flashcards.json", json.dumps(flashcards, ensure_ascii=False, indent=2))
                        progress_cb("Done", 100)
                    # display
                    if flashcards:
                        for i, fc in enumerate(flashcards, start=1):
                            st.markdown(f"**{i}. {fc.get('front','(no front)')}**")
                            st.write(fc.get("back","(no back)"))
                    else:
                        st.warning("No flashcards generated.")
                except Exception as e:
                    st.error(f"Failed to generate flashcards: {e}")

        if col3.button("Generate Quizzes"):
            with st.spinner("Processing..."):
                try:
                    audio_hash, cache_path, transcript_text, chunk_summaries = prepare_transcript_and_summaries_from_bytes(
                        uploaded_bytes, uploaded.name, progress_callback=progress_cb
                    )
                    quiz_cached = read_cache_text(cache_path, "quiz.json")
                    model = get_gemini_model()
                    if quiz_cached:
                        quiz = json.loads(quiz_cached)
                        st.success("Quiz returned from cache")
                    else:
                        progress_cb("Generating quiz questions...", 95)
                        quiz = generate_quiz_from_summaries(model, chunk_summaries)
                        write_cache_text(cache_path, "quiz.json", json.dumps(quiz, ensure_ascii=False, indent=2))
                        progress_cb("Done", 100)
                    # display
                    if quiz:
                        for i, q in enumerate(quiz, start=1):
                            st.markdown(f"**Q{i}. {q.get('question','(no question)')}**")
                            choices = q.get('choices') or q.get('options') or q.get('answers') or {}
                            if isinstance(choices, dict):
                                for k, v in choices.items():
                                    st.write(f"- {k}: {v}")
                            elif isinstance(choices, list):
                                for idx, val in enumerate(choices):
                                    st.write(f"- {chr(65+idx)}: {val}")
                            else:
                                st.write("No choices available.")
                    else:
                        st.warning("No quiz questions generated.")

                except Exception as e:
                    st.error(f"Failed to generate quiz: {e}")

# Footer / tips
st.markdown("---")
st.write("Notes:")
st.write("- This app performs multiple network/model calls and may take minutes for long recordings.")
st.write("- Cache lives in `./cache/<sha256>/` on the host. Remove a folder to re-run processing from scratch.")