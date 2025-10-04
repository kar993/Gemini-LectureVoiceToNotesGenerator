import os
import io
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS # Needed for cross-origin requests from frontend
from dotenv import load_dotenv
import google.generativeai as genai
from pydub import AudioSegment # For audio processing utilities if needed

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
# Allow CORS for all origins, necessary for local frontend development
# In a production environment, you would restrict this to your frontend's domain.
CORS(app)

# Configure Gemini API
# This will raise an error if GEMINI_API_KEY is not set
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Define a function to initialize the Gemini model
def get_gemini_model():
    """Initializes and returns the Gemini Pro Vision (gemini-2.0-flash) model for multimodal input."""
    return genai.GenerativeModel('gemini-2.0-flash')

# --- Helper Functions ---

def validate_audio_file(file_stream, filename):
    """
    Validates audio file type and duration.
    Returns (True, None) if valid, or (False, error_message) if invalid.
    """
    if not filename:
        return False, "No file uploaded."

    # Validate file extension
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in ['mp3', 'wav']:
        return False, f"Unsupported file type: .{ext}. Only MP3 and WAV are allowed."

    try:
        # Use pydub to load audio and check duration
        # Rewind the stream before passing to AudioSegment
        file_stream.seek(0)
        audio = AudioSegment.from_file(file_stream, format=ext)
        duration_minutes = len(audio) / (1000 * 60) # duration in milliseconds

        if duration_minutes > 15:
            return False, f"Audio file is too long ({duration_minutes:.2f} mins). Maximum allowed is 15 minutes."

        # Rewind the stream again so it can be read by Gemini API later
        file_stream.seek(0)
        return True, None
    except Exception as e:
        return False, f"Could not process audio file: {str(e)}"

# --- API Endpoints ---

@app.route('/upload_audio', methods=['POST'])
def upload_audio():
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files['audio']
    filename = audio_file.filename

    is_valid, error_msg = validate_audio_file(audio_file.stream, filename)
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    # At this point, the file is validated and its stream is rewound.
    # You can now read audio_file.stream.read() to get the bytes
    # or pass audio_file.stream directly to Gemini.

    # For demonstration, let's just confirm upload and prepare for further processing
    # In a real scenario, you'd store this or pass it to Gemini immediately.
    return jsonify({
        "message": f"Audio file '{filename}' uploaded and validated successfully.",
        "filename": filename,
        "size": audio_file.content_length,
        # In a real scenario, you might return a session ID or path to processed audio
    }), 200

@app.route('/generate_notes', methods=['POST'])
def generate_notes():
    # This route will receive the audio data (or a reference to it)
    # and call the Gemini API for notes.
    # For now, it's a placeholder.
    # The actual audio data would be sent here from the frontend,
    # or if we store it temporarily, we'd reference it.
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files['audio']
    filename = audio_file.filename

    is_valid, error_msg = validate_audio_file(audio_file.stream, filename)
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    try:
        model = get_gemini_model()
        audio_content_bytes = audio_file.stream.read() # Read the content after validation

        # Prepare the audio part for Gemini
        audio_part = {
            "mime_type": f"audio/{filename.rsplit('.', 1)[1].lower()}",
            "data": audio_content_bytes
        }

        # Define the prompt for notes
        prompt_text = """
        You are an AI assistant specialized in creating detailed study notes from class recordings.
        Please transcribe the following audio. After transcription, generate comprehensive notes with the following structure:
        1.  **High-Level Overview:** A concise summary of the main topics covered in the class, briefly mentioning key concepts.
        2.  **Concept-Wise Breakdown:** For each major concept discussed, provide a more detailed explanation, including definitions, relevant examples, and any formulas mentioned. Organize this clearly under concept headings.
        3.  **Bullet Point Summary:** A concise list of the most important takeaways and key points, suitable for quick review.

        Example of desired output structure:
        ---
        [High-Level Overview]
        Class covered the newton's laws of motion. 1st law: ... 2nd law: ... 3rd law: ...
        
        [Concept-Wise Breakdown]
        **Newton's First Law of Motion (Law of Inertia)**
        Definition: ...
        Explanation: ...
        Example: ...
        Formula/Principle: ...

        **Newton's Second Law of Motion**
        Definition: ...
        Explanation: ...
        Example: ...
        Formula: F = ma (where F is force, m is mass, a is acceleration)
        
        **Newton's Third Law of Motion**
        Definition: ...
        Explanation: ...
        Example: ...
        Principle: ...
        
        [Bullet Point Summary]
        - Newton's Laws of Motion:
        - 1st Law: definition, example, principle of inertia.
        - 2nd Law: definition, example, F=ma.
        - 3rd Law: definition, example, action-reaction pairs.
        ---
        Ensure all output is in English, even if the speaker has an accent.
        """
        # Note: The actual prompt should be more detailed, like the example I gave earlier.
        # This is a concise version for initial testing.

        # Send both text prompt and audio to Gemini Pro Vision
        response = model.generate_content([prompt_text, audio_part])

        # Extract the text response
        notes_content = response.text

        return jsonify({"notes": notes_content}), 200

    except genai.types.BlockedPromptException as e:
        return jsonify({"error": f"Content generation blocked due to safety policy: {e.response.prompt_feedback}"}), 400
    except Exception as e:
        # Catch other potential Gemini errors or network issues
        return jsonify({"error": f"Failed to generate notes: {str(e)}"}), 500


@app.route('/generate_flashcards', methods=['POST'])
def generate_flashcards():
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files['audio']
    filename = audio_file.filename

    is_valid, error_msg = validate_audio_file(audio_file.stream, filename)
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    try:
        model = get_gemini_model()
        audio_content_bytes = audio_file.stream.read()

        audio_part = {
            "mime_type": f"audio/{filename.rsplit('.', 1)[1].lower()}",
            "data": audio_content_bytes
        }

        # Define the prompt for flashcards
        prompt_text = """
        You are an AI assistant specialized in creating study flashcards from class content.
        Please transcribe the following audio. From the transcribed content, identify 1 to 3 key concepts and/or formulas suitable for flashcards. For each flashcard, provide:
        -   **Front:** The concept or formula itself.
        -   **Back:** A clear, concise explanation or definition of the concept/formula.
        Focus on a mix of important concepts and formulas.
        
        Provide the output in a structured JSON format, where each object represents a flashcard:
        [
            {
                "front": "Concept/Formula Name",
                "back": "Explanation/Definition"
            },
            {
                "front": "Concept/Formula Name 2",
                "back": "Explanation/Definition 2"
            }
        ]
        """

        response = model.generate_content([prompt_text, audio_part])
        flashcards_json_string = response.text

        # Gemini might sometimes include markdown code block syntax (```json)
        # We need to strip it to get pure JSON
        if flashcards_json_string.strip().startswith('```json'):
            flashcards_json_string = flashcards_json_string.strip()[len('```json'):]
            if flashcards_json_string.strip().endswith('```'):
                flashcards_json_string = flashcards_json_string.strip()[:-len('```')]

        import json
        flashcards_data = json.loads(flashcards_json_string)

        return jsonify({"flashcards": flashcards_data}), 200

    except json.JSONDecodeError:
        return jsonify({"error": "Gemini returned invalid JSON for flashcards. Please try again."}), 500
    except genai.types.BlockedPromptException as e:
        return jsonify({"error": f"Content generation blocked due to safety policy: {e.response.prompt_feedback}"}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to generate flashcards: {str(e)}"}), 500


@app.route('/generate_quizzes', methods=['POST'])
def generate_quizzes():
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files['audio']
    filename = audio_file.filename

    is_valid, error_msg = validate_audio_file(audio_file.stream, filename)
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    try:
        model = get_gemini_model()
        audio_content_bytes = audio_file.stream.read()

        audio_part = {
            "mime_type": f"audio/{filename.rsplit('.', 1)[1].lower()}",
            "data": audio_content_bytes
        }

        # Define the prompt for quizzes
        prompt_text = """
        You are an AI assistant specialized in generating multiple-choice quiz questions from class content.
        Please transcribe the following audio. From the transcribed content, create exactly 3 multiple-choice questions (MCQs) for general understanding. For each question:
        -   Provide the question itself.
        -   Provide 4 possible answer choices (A, B, C, D), where only one is correct.
        -   Clearly indicate the correct answer.

        Example of desired output structure (JSON format):
        [
            {
                "question": "What is the primary definition of Newton's First Law of Motion?",
                "options": {
                    "A": "Force equals mass times acceleration.",
                    "B": "For every action, there is an equal and opposite reaction.",
                    "C": "An object at rest stays at rest, and an object in motion stays in motion with the same speed and in the same direction unless acted upon by an unbalanced force.",
                    "D": "Energy cannot be created or destroyed."
                },
                "correct_answer": "C"
            }
        ]
        Ensure the questions are at a general understanding difficulty level.
        """

        response = model.generate_content([prompt_text, audio_part])
        quiz_json_string = response.text

        # Strip markdown code block syntax if present
        if quiz_json_string.strip().startswith('```json'):
            quiz_json_string = quiz_json_string.strip()[len('```json'):]
            if quiz_json_string.strip().endswith('```'):
                quiz_json_string = quiz_json_string.strip()[:-len('```')]

        import json
        quiz_data = json.loads(quiz_json_string)

        return jsonify({"quiz": quiz_data}), 200

    except json.JSONDecodeError:
        return jsonify({"error": "Gemini returned invalid JSON for quizzes. Please try again."}), 500
    except genai.types.BlockedPromptException as e:
        return jsonify({"error": f"Content generation blocked due to safety policy: {e.response.prompt_feedback}"}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to generate quizzes: {str(e)}"}), 500


# --- Run the Flask App ---
if __name__ == '__main__':
    # For development, Flask defaults to port 5000.
    # debug=True allows for auto-reloading on code changes.
    app.run(debug=True, port=5000)