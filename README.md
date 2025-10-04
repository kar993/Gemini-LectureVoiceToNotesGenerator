# Gemini-LectureVoiceToNotesGenerator
An AI powered webapp that takes lecture/class audio recordings and turns them into study aids

Upload an audio file (format: MP3 and WAV only and duration: 15 mins maximum for now) and choose:
1. Generate Notes - For concise summary of the lecture
2. Generate Flashcards - Concept/explanation style cards for revision
3. Generate Quizzes - Practice MCQs to test understanding

Built with python (backend) and JavaScript, CSS and HTML (frontend), using Google AI Studio's API for LLM.

**Setup:**

1. Clone the Repo:
  ```
  git clone git@github.com:kar993/Gemini-LectureVoiceToNotesGenerator.git
  cd Gemini-LectureVoiceToNotesGenerator
  ```

2. Backend (Python):
  ```
  cd backend
  python -m venv venv
  # activate venv
  venv\Scripts\activate.bat      # Windows
  source venv/bin/activate   # macOS/Linux
  
  pip install -r Requirements.txt
  ```

3. Environment variables: Edit the .env.example to .env and add your Google AI Studio's API key to the environment variable inside the .env file

4. Running backend:
  * Make sure your virtual environment is active and you have installed the dependencies through Requirements.txt file
  * ```
    flask run
    ```

5. Launch the webapp:
  ```
  cd frontend
  npm install
  npm run dev
  ```

6. Usage:
  Upload the audio file and select an option.


All the best :)
