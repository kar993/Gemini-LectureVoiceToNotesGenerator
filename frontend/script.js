// --- Configuration ---
const BACKEND_URL = 'http://127.0.0.1:5000'; // Our Flask backend URL
const MAX_AUDIO_SECONDS = 60 * 60; // 60 minutes in seconds
const ESTIMATED_PROCESSING_TIME_SECONDS = 60 * 8; // Approx 8 minutes for a 60 min audio (adjust as needed)

// --- DOM Element Caching ---
const dropArea = document.getElementById('drop-area');
const fileInput = document.getElementById('audio-file-input');
const fileNameDisplay = document.getElementById('file-name');
const fileBrowseBtn = document.getElementById('file-browse-btn');

const generateNotesBtn = document.getElementById('generate-notes-btn');
const generateFlashcardsBtn = document.getElementById('generate-flashcards-btn');
const generateQuizzesBtn = document.getElementById('generate-quizzes-btn');

const loadingArea = document.getElementById('loading-area');
const loadingMessage = document.getElementById('loading-message');

const notesOutput = document.getElementById('notes-output');
const notesContentArea = document.getElementById('notes-content');
const downloadNotesBtn = document.getElementById('download-notes-btn');

const modal = document.getElementById('modal');
const modalTitle = document.getElementById('modal-title');
const modalMessage = document.getElementById('modal-message');
const modalBodyContent = document.getElementById('modal-body-content');
const modalNavigation = document.getElementById('modal-navigation');
const prevBtn = document.getElementById('prev-btn');
const nextBtn = document.getElementById('next-btn');
const closeButton = document.querySelector('.close-button');

// --- Global State ---
let uploadedAudioFile = null;
let currentFlashcardIndex = 0;
let currentQuizQuestionIndex = 0;
let flashcardsData = [];
let quizData = [];

// --- Utility Functions ---

/**
 * Shows the modal with a title and message.
 * Optionally hides navigation if not needed for the content.
 */
function showModal(title, message, bodyHtml = '', showNav = false) {
    modalTitle.textContent = title;
    modalMessage.textContent = message;
    modalBodyContent.innerHTML = bodyHtml;
    if (showNav) {
        modalNavigation.classList.remove('hidden');
    } else {
        modalNavigation.classList.add('hidden');
    }
    modal.classList.remove('hidden');
}

/**
 * Hides the modal.
 */
function hideModal() {
    modal.classList.add('hidden');
    modalBodyContent.innerHTML = ''; // Clear content
    currentFlashcardIndex = 0; // Reset state for interactive content
    currentQuizQuestionIndex = 0;
    flashcardsData = [];
    quizData = [];
}

/**
 * Displays a temporary loading indicator.
 */
function showLoading(message = "Processing your audio...") {
    loadingMessage.textContent = message;
    loadingArea.classList.remove('hidden');
    // Disable all control buttons while loading
    generateNotesBtn.disabled = true;
    generateFlashcardsBtn.disabled = true;
    generateQuizzesBtn.disabled = true;
    // Hide previous outputs
    notesOutput.classList.add('hidden');
}

/**
 * Hides the loading indicator.
 */
function hideLoading() {
    loadingArea.classList.add('hidden');
    // Re-enable buttons if a file is present
    if (uploadedAudioFile) {
        enableControlButtons();
    }
}

/**
 * Enables the generation buttons.
 */
function enableControlButtons() {
    generateNotesBtn.disabled = false;
    generateFlashcardsBtn.disabled = false;
    generateQuizzesBtn.disabled = false;
}

/**
 * Disables the generation buttons.
 */
function disableControlButtons() {
    generateNotesBtn.disabled = true;
    generateFlashcardsBtn.disabled = true;
    generateQuizzesBtn.disabled = true;
}

/**
 * Handles the selected file and updates UI.
 * Also performs a client-side duration check using an Audio element.
 */
function handleFile(file) {
    if (file) {
        // Simple client-side validation for UI feedback
        const validTypes = ['audio/mpeg', 'audio/wav'];
        if (!validTypes.includes(file.type)) {
            showModal('Invalid File Type', `Please upload an MP3 or WAV audio file. Received: ${file.type}`);
            uploadedAudioFile = null;
            fileNameDisplay.textContent = '';
            disableControlButtons();
            return;
        }

        // Client-side duration check: create an audio element and load metadata
        const objectUrl = URL.createObjectURL(file);
        const audioEl = new Audio();
        audioEl.src = objectUrl;
        audioEl.preload = 'metadata';

        audioEl.addEventListener('loadedmetadata', () => {
            const duration = audioEl.duration; // in seconds (may be NaN if not available)
            URL.revokeObjectURL(objectUrl);
            if (!isFinite(duration)) {
                // fallback: allow it but warn user
                uploadedAudioFile = file;
                fileNameDisplay.textContent = `Selected file: ${file.name}`;
                enableControlButtons();
                notesOutput.classList.add('hidden');
                showModal('Warning', 'Could not determine audio duration in the browser. Server will validate when uploading.');
                return;
            }

            if (duration > MAX_AUDIO_SECONDS) {
                showModal('File Too Long', `Uploaded audio is ${Math.floor(duration/60)} minutes and ${Math.floor(duration%60)} seconds — the maximum allowed is 60 minutes.`);
                uploadedAudioFile = null;
                fileNameDisplay.textContent = '';
                disableControlButtons();
                return;
            }

            // All good
            uploadedAudioFile = file;
            fileNameDisplay.textContent = `Selected file: ${file.name} (${Math.floor(duration/60)}m ${Math.floor(duration%60)}s)`;
            enableControlButtons();
            notesOutput.classList.add('hidden'); // Hide notes if new file uploaded
        });

        audioEl.addEventListener('error', (e) => {
            URL.revokeObjectURL(objectUrl);
            showModal('Error', 'Could not read audio metadata in the browser. The server will validate the file when uploaded.');
            uploadedAudioFile = file;
            fileNameDisplay.textContent = `Selected file: ${file.name}`;
            enableControlButtons();
        });

    } else {
        uploadedAudioFile = null;
        fileNameDisplay.textContent = '';
        disableControlButtons();
    }
}

/**
 * Sends audio to the backend and fetches generated content.
 * @param {string} endpoint - The backend API endpoint (e.g., '/generate_notes').
 * @returns {Promise<any>} The parsed JSON response from the backend.
 */
async function sendAudioToBackend(endpoint) {
    if (!uploadedAudioFile) {
        showModal('Error', 'Please upload an audio file first.');
        return;
    }

    showLoading(); // Show loading indicator
    const formData = new FormData();
    formData.append('audio', uploadedAudioFile);

    try {
        const response = await fetch(`${BACKEND_URL}${endpoint}`, {
            method: 'POST',
            body: formData,
        });

        const data = await response.json();

        if (!response.ok) {
            // If response.ok is false, it's an HTTP error (4xx, 5xx)
            showModal('Error', data.error || `An unknown error occurred: ${response.status}`);
            return null;
        }

        return data;
    } catch (error) {
        console.error('Network or API Error:', error);
        showModal('Network Error', `Could not connect to the backend or API: ${error.message}. Make sure the backend server is running.`);
        return null;
    } finally {
        hideLoading(); // Always hide loading indicator
    }
}

// --- Specific Content Generation Functions ---

async function generateNotesAndSummary() {
    const data = await sendAudioToBackend('/generate_notes');
    if (data && data.notes) {
        notesContentArea.value = data.notes;
        notesOutput.classList.remove('hidden');
    }
}

async function generateFlashcards() {
    const data = await sendAudioToBackend('/generate_flashcards');
    if (data && data.flashcards) {
        flashcardsData = data.flashcards;
        if (flashcardsData.length > 0) {
            currentFlashcardIndex = 0;
            // show modal first, then inject content so it doesn't get wiped
            showModal('Generated Flashcards', 'Click the card to flip!', '', true);
            displayFlashcard();
        } else {
            showModal('No Flashcards', 'Gemini could not generate any flashcards from the audio.');
        }
    }
}

// --- Restore generateQuizzes (was missing) ---
async function generateQuizzes() {
    const data = await sendAudioToBackend('/generate_quizzes');
    if (data && data.quiz) {
        quizData = data.quiz;

        // Helpful debug output (open DevTools Console to inspect the raw shape)
        console.log("QUIZ DATA RAW:", quizData);

        if (Array.isArray(quizData) && quizData.length > 0) {
            currentQuizQuestionIndex = 0;
            showModal('Generated Quiz', 'Answer the questions below.', '', true);
            displayQuizQuestion();
        } else {
            showModal('No Quiz', 'Gemini could not generate any quiz questions from the audio.');
        }
    }
}

// Robust, single displayQuizQuestion implementation (accepts various shapes)
function displayQuizQuestion() {
    if (!Array.isArray(quizData) || quizData.length === 0) return;

    const raw = quizData[currentQuizQuestionIndex] || {};

    // Normalize various possible fields to a consistent shape
    const questionText = raw.question || raw.prompt || raw.q || "Untitled question";

    // optionsObj will be a mapping like { "A": "choice text", "B": "choice text", ... }
    let optionsObj = {};
    let correctLetter = raw.correct_answer || raw.correct || null;

    // Case A: options is an object, e.g. { A: "...", B: "..." }
    if (raw.options && typeof raw.options === 'object' && !Array.isArray(raw.options)) {
        optionsObj = raw.options;
    }
    // Case B: options is an array -> convert to A, B, C...
    else if (Array.isArray(raw.options) && raw.options.length > 0) {
        const letters = ['A','B','C','D','E','F','G','H'];
        raw.options.forEach((opt, idx) => {
            optionsObj[letters[idx] || String(idx+1)] = opt;
        });
    }

    // Case C: choices may be an object ({A:..}) or array [...]
    if (!raw.options && raw.choices) {
        if (typeof raw.choices === 'object' && !Array.isArray(raw.choices)) {
            // choices is an object mapping letters -> text
            optionsObj = raw.choices;
        } else if (Array.isArray(raw.choices) && raw.choices.length > 0) {
            const letters = ['A','B','C','D','E','F','G','H'];
            raw.choices.forEach((opt, idx) => {
                optionsObj[letters[idx] || String(idx+1)] = opt;
            });
        }
    }

    // Case D: answers array variant
    if (!raw.options && !raw.choices && Array.isArray(raw.answers) && raw.answers.length > 0) {
        const letters = ['A','B','C','D','E','F','G','H'];
        raw.answers.forEach((opt, idx) => {
            optionsObj[letters[idx] || String(idx+1)] = opt;
        });
    }

    // If the model provided an index for the correct answer, convert it to a letter
    if ((raw.answer_index !== undefined || raw.correct_index !== undefined) && !correctLetter) {
        const idx = (raw.answer_index !== undefined) ? raw.answer_index : raw.correct_index;
        const letters = ['A','B','C','D','E','F','G','H'];
        if (typeof idx === 'number' && idx >= 0) {
            correctLetter = letters[idx] || String(idx+1);
        }
    }

    // If the model provided correct_text, try to find a matching option
    if (!correctLetter && raw.correct_text) {
        for (const [k, v] of Object.entries(optionsObj)) {
            if (v && raw.correct_text && v.trim().toLowerCase() === raw.correct_text.trim().toLowerCase()) {
                correctLetter = k;
                break;
            }
        }
    }

    // Build HTML for options
    let optionsHtml = '';
    const optionKeys = Object.keys(optionsObj);
    if (optionKeys.length === 0) {
        optionsHtml = `<p><em>No answer choices were returned for this question.</em></p>`;
    } else {
        for (const key of optionKeys) {
            const labelText = optionsObj[key];
            optionsHtml += `
                <label>
                    <input type="radio" name="quiz-option" value="${escapeHtml(key)}">
                    ${escapeHtml(key)}. ${escapeHtml(labelText)}
                </label>
            `;
        }
    }

    // Render modal content
    modalMessage.textContent = `Question ${currentQuizQuestionIndex + 1} of ${quizData.length}`;
    modalBodyContent.innerHTML = `
        <div class="quiz-question-container">
            <p>${escapeHtml(questionText)}</p>
            <div class="quiz-options">
                ${optionsHtml}
            </div>
            <button id="submit-answer-btn" class="submit-button">Submit Answer</button>
            <div id="quiz-feedback-area" class="quiz-feedback"></div>
        </div>
    `;

    // Hook up submit button behavior
    const submitBtn = document.getElementById('submit-answer-btn');
    const feedbackArea = document.getElementById('quiz-feedback-area');

    submitBtn.onclick = function() {
        const selectedOption = document.querySelector('input[name="quiz-option"]:checked');
        if (!selectedOption) {
            feedbackArea.textContent = 'Please select an answer.';
            feedbackArea.className = 'quiz-feedback';
            return;
        }

        const userAnswer = selectedOption.value;

        if (correctLetter && userAnswer === correctLetter) {
            feedbackArea.textContent = 'Correct!';
            feedbackArea.className = 'quiz-feedback correct';
        } else if (correctLetter) {
            feedbackArea.textContent = `Incorrect! Correct: ${correctLetter}.`;
            feedbackArea.className = 'quiz-feedback incorrect';
        } else {
            feedbackArea.textContent = 'Answer recorded.';
            feedbackArea.className = 'quiz-feedback';
        }

        submitBtn.disabled = true;
        document.querySelectorAll('input[name="quiz-option"]').forEach(input => input.disabled = true);
    };

    updateModalNavigation();
}

// Helper to escape HTML to avoid accidental injection
function escapeHtml(str) {
    if (str === undefined || str === null) return '';
    return String(str)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

// --- Interactive Display Functions (Modal Content) ---

function displayFlashcard() {
    if (flashcardsData.length === 0) return;

    const flashcard = flashcardsData[currentFlashcardIndex];
    modalMessage.textContent = `Flashcard ${currentFlashcardIndex + 1} of ${flashcardsData.length}. Click to flip!`;

    modalBodyContent.innerHTML = `
        <div class="flashcard-container">
            <div class="flashcard" id="current-flashcard">
                <div class="flashcard-face flashcard-front">
                    <div class="flashcard-content">${escapeHtml(flashcard.front)}</div>
                </div>
                <div class="flashcard-face flashcard-back">
                    <div class="flashcard-content">${escapeHtml(flashcard.back)}</div>
                </div>
            </div>
        </div>
    `;

    // Add event listener to flip card
    const el = document.getElementById('current-flashcard');
    if (el) {
        el.onclick = function() {
            this.classList.toggle('flipped');
        };
    }

    updateModalNavigation();
}

function updateModalNavigation() {
    prevBtn.disabled = true;
    nextBtn.disabled = true;

    if (flashcardsData.length > 0) { // Flashcard navigation
        if (currentFlashcardIndex > 0) prevBtn.disabled = false;
        if (currentFlashcardIndex < flashcardsData.length - 1) nextBtn.disabled = false;
    } else if (quizData.length > 0) { // Quiz navigation
        if (currentQuizQuestionIndex > 0) prevBtn.disabled = false;
        if (currentQuizQuestionIndex < quizData.length - 1) nextBtn.disabled = false;
    }
}

// --- Event Listeners ---

// File Upload Area (Drag & Drop)
dropArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropArea.classList.add('highlight');
});

dropArea.addEventListener('dragleave', () => {
    dropArea.classList.remove('highlight');
});

dropArea.addEventListener('drop', (e) => {
    e.preventDefault();
    dropArea.classList.remove('highlight');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        fileInput.files = files; // Assign files to input element
        handleFile(files[0]);
    }
});

// File Input Click
fileBrowseBtn.addEventListener('click', () => {
    fileInput.click();
});

fileInput.addEventListener('change', (e) => {
    handleFile(e.target.files[0]);
});

// Generation Buttons
generateNotesBtn.addEventListener('click', generateNotesAndSummary);
generateFlashcardsBtn.addEventListener('click', generateFlashcards);
generateQuizzesBtn.addEventListener('click', generateQuizzes);

// Notes Download Button
downloadNotesBtn.addEventListener('click', () => {
    const notesText = notesContentArea.value;
    if (notesText) {
        const blob = new Blob([notesText], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'class_notes.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url); // Clean up
    }
});

// Modal Close Button
closeButton.addEventListener('click', hideModal);
modal.addEventListener('click', (e) => {
    if (e.target === modal) { // Close if clicked outside modal-content
        hideModal();
    }
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
        hideModal();
    }
});

// Modal Navigation Buttons
prevBtn.addEventListener('click', () => {
    if (flashcardsData.length > 0) {
        if (currentFlashcardIndex > 0) {
            currentFlashcardIndex--;
            displayFlashcard();
        }
    } else if (quizData.length > 0) {
        if (currentQuizQuestionIndex > 0) {
            currentQuizQuestionIndex--;
            displayQuizQuestion();
        }
    }
});

nextBtn.addEventListener('click', () => {
    if (flashcardsData.length > 0) {
        if (currentFlashcardIndex < flashcardsData.length - 1) {
            currentFlashcardIndex++;
            displayFlashcard();
        }
    } else if (quizData.length > 0) {
        if (currentQuizQuestionIndex < quizData.length - 1) {
            currentQuizQuestionIndex++;
            displayQuizQuestion();
        }
    }
});

// --- Initial Setup ---
disableControlButtons(); // Buttons are disabled until a file is uploaded