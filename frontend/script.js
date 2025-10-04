// --- Configuration ---
const BACKEND_URL = 'http://127.0.0.1:5000'; // Our Flask backend URL
const ESTIMATED_PROCESSING_TIME_SECONDS = 60 * 2; // Approx 2 minutes for a 15 min audio, adjust as needed

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

        uploadedAudioFile = file;
        fileNameDisplay.textContent = `Selected file: ${file.name}`;
        enableControlButtons();
        notesOutput.classList.add('hidden'); // Hide notes if new file uploaded
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
            displayFlashcard();
            showModal('Generated Flashcards', 'Click the card to flip!', '', true);
        } else {
            showModal('No Flashcards', 'Gemini could not generate any flashcards from the audio.');
        }
    }
}

async function generateQuizzes() {
    const data = await sendAudioToBackend('/generate_quizzes');
    if (data && data.quiz) {
        quizData = data.quiz;
        if (quizData.length > 0) {
            currentQuizQuestionIndex = 0;
            displayQuizQuestion();
            showModal('Generated Quiz', 'Answer the questions below.', '', true);
        } else {
            showModal('No Quiz', 'Gemini could not generate any quiz questions from the audio.');
        }
    }
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
                    <div class="flashcard-content">${flashcard.front}</div>
                </div>
                <div class="flashcard-face flashcard-back">
                    <div class="flashcard-content">${flashcard.back}</div>
                </div>
            </div>
        </div>
    `;

    // Add event listener to flip card
    document.getElementById('current-flashcard').onclick = function() {
        this.classList.toggle('flipped');
    };

    updateModalNavigation();
}

function displayQuizQuestion() {
    if (quizData.length === 0) return;

    const question = quizData[currentQuizQuestionIndex];
    modalMessage.textContent = `Question ${currentQuizQuestionIndex + 1} of ${quizData.length}`;

    let optionsHtml = '';
    for (const key in question.options) {
        optionsHtml += `
            <label>
                <input type="radio" name="quiz-option" value="${key}">
                ${key}. ${question.options[key]}
            </label>
        `;
    }

    modalBodyContent.innerHTML = `
        <div class="quiz-question-container">
            <p>${question.question}</p>
            <div class="quiz-options">
                ${optionsHtml}
            </div>
            <button id="submit-answer-btn" class="submit-button">Submit Answer</button>
            <div id="quiz-feedback-area" class="quiz-feedback"></div>
        </div>
    `;

    const submitBtn = document.getElementById('submit-answer-btn');
    const feedbackArea = document.getElementById('quiz-feedback-area');

    submitBtn.onclick = function() {
        const selectedOption = document.querySelector('input[name="quiz-option"]:checked');
        if (!selectedOption) {
            feedbackArea.textContent = 'Please select an answer.';
            feedbackArea.className = 'quiz-feedback'; // Reset for warnings
            return;
        }

        const userAnswer = selectedOption.value;
        if (userAnswer === question.correct_answer) {
            feedbackArea.textContent = 'Correct!';
            feedbackArea.className = 'quiz-feedback correct';
        } else {
            feedbackArea.textContent = 'Incorrect! Please review this concept.';
            feedbackArea.className = 'quiz-feedback incorrect';
        }
        submitBtn.disabled = true; // Prevent re-submission
        // Optionally, highlight correct answer or disable other options
        document.querySelectorAll('input[name="quiz-option"]').forEach(input => input.disabled = true);
    };

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