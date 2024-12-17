import StreamingAvatar, {
  AvatarQuality,
  StreamingEvents,
  TaskType,
} from "@heygen/streaming-avatar";

// DOM elements
const videoElement = document.getElementById("avatarVideo") as HTMLVideoElement;
const endButton = document.getElementById("endSession") as HTMLButtonElement;
const micIndicator = document.getElementById("micIndicator") as HTMLDivElement;
const floatingContainer = document.getElementById("floatingContainer") as HTMLDivElement;
const placeholder = document.querySelector('.avatar-placeholder') as HTMLDivElement;
const userInput = document.getElementById("userInput") as HTMLInputElement;
const sendButton = document.getElementById("sendButton") as HTMLButtonElement;
const messageContainer = document.getElementById("messageContainer") as HTMLDivElement;

// State variables
let avatar: StreamingAvatar | null = null;
let sessionData: any = null;
let avatarMessageBuffer: string = "";
let micPermissionGranted = false;
let lastUserMessage = "";
let isAvatarLoaded = false;

// Helper function to check and request microphone permissions
async function checkMicrophonePermission(): Promise<boolean> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach(track => track.stop());
    micPermissionGranted = true;
    return true;
  } catch (error) {
    console.error("Microphone permission error:", error);
    micPermissionGranted = false;
    return false;
  }
}

// Helper function to fetch access token
async function fetchAccessToken(): Promise<string> {
  try {
    const apiKey = import.meta.env.VITE_HEYGEN_API_KEY;
    const response = await fetch("https://api.heygen.com/v1/streaming.create_token", {
      method: "POST",
      headers: { "x-api-key": apiKey },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch token: ${response.statusText}`);
    }

    const { data } = await response.json();
    return data.token;
  } catch (error) {
    console.error("Error fetching access token:", error);
    throw error;
  }
}

// Initialize streaming avatar session
async function initializeAvatarSession() {
  try {
    const token = await fetchAccessToken();
    avatar = new StreamingAvatar({ token });

    sessionData = await avatar.createStartAvatar({
      quality: AvatarQuality.Low,
      avatarName: "Wayne_20240711",
      knowledgeId: 'bfac7de4f7cf42e09024f13c520bd7ca',
    });

    console.log("Session initialized:", sessionData);

    // Update UI state
    endButton.disabled = false;
    isAvatarLoaded = true;

    // Set up event listeners
    setupAvatarEventListeners();
    
    // Automatically start voice chat after avatar is loaded
    await startVoiceChat();
  } catch (error) {
    console.error("Failed to initialize avatar session:", error);
    alert("Failed to initialize avatar session. Please try again.");
    resetUIState();
  }
}

// Helper function to send an initial "Hi" message
async function sendInitialMessage() {
  if (avatar) {
    const requestData = {
      text: "Hi",
    };
    await avatar.speak(requestData);
    displayMessage("Hi", "user");
    console.log("Sent 'Hi' to avatar");
  }
}

// Handle stream ready event
function handleStreamReady(event: any) {
  if (event.detail && videoElement) {
    videoElement.srcObject = event.detail;
    videoElement.onloadedmetadata = () => {
      videoElement.play().catch(console.error);

      // Hide the loading message once avatar is ready
      const loadingMessage = document.getElementById("loadingMessage");
      if (loadingMessage) {
        loadingMessage.style.display = 'none';
      }

      sendInitialMessage();
    };
  } else {
    console.error("Stream is not available");
  }
}


// Handle stream disconnection
function handleStreamDisconnected() {
  console.log("Stream disconnected");
  resetUIState();
}

// Handle user talking message
function handleUserTalkingMessage(event: CustomEvent) {
  const userMessage = event.detail.message;
  console.log('User message:', userMessage);
  lastUserMessage = userMessage;
}

function handleAvatarTalkingMessage(event: any) {
  const chunk = event.detail.message;
  avatarMessageBuffer += chunk;

  const normalizedBuffer = avatarMessageBuffer.toLowerCase();

  // If the avatar says "bye", wait 3 seconds, then end the session and collapse the container
  if (normalizedBuffer.includes("bye")) {
    console.log("Avatar said 'bye'. Ending session in 3 seconds...");

    // Delay session termination by 3 seconds
    setTimeout(() => {
      // Trigger end session
      terminateAvatarSession();

      // Collapse the floating container
      floatingContainer.classList.remove('expanded');
      placeholder.style.display = 'block';
      videoElement.style.display = 'none';

      avatarMessageBuffer = "";
    }, 3000); // 3 seconds delay

    return;  // Exit after scheduling the timeout
  }

  // Existing functionality: processing "processing your request"
  if (normalizedBuffer.includes("processing your request")) {
    console.log("Found 'processing your request'. Sending message...");

    const inputField = document.getElementById("user-input");
    if (inputField) {
      inputField.value = lastUserMessage;

      // Call the globally available sendMessage function
      window.sendMessage();
    }

    avatarMessageBuffer = "";
  }

  if (chunk.endsWith('.')) {
    console.log('Avatar message:', avatarMessageBuffer.trim());
    avatarMessageBuffer = "";
  }
}



// Display messages in the message container
function displayMessage(message: string, type: 'user' | 'avatar') {
  const messageElement = document.createElement("div");
  messageElement.classList.add("message", `${type}-message`);
  messageElement.textContent = `${type === 'user' ? 'You' : 'Avatar'}: ${message}`;
  messageContainer.appendChild(messageElement);
  scrollToBottom();
}

// Function to scroll to the bottom of the chat
function scrollToBottom() {
  messageContainer.scrollTop = messageContainer.scrollHeight;
}

// Handle user speech
async function handleUserSpeak() {
  if (avatar && userInput.value) {
    const userMessage = userInput.value;
    await avatar.speak({ text: userMessage });
    displayMessage(userMessage, 'user');
    userInput.value = "";
  }
}

// Send message (placeholder function referenced in handleAvatarTalkingMessage)
function sendMessage() {
  console.log("Sending message...");
}

// Start voice chat automatically
async function startVoiceChat() {
  if (!avatar) {
    console.error("Avatar not initialized");
    return;
  }

  try {
    const hasPermission = await checkMicrophonePermission();
    if (!hasPermission) {
      alert("Microphone permission is required for voice chat.");
      return;
    }

    await avatar.startVoiceChat();
    micIndicator.classList.add('active');
    console.log("Voice chat started automatically");
  } catch (error) {
    console.error("Error starting voice chat:", error);
    alert("Failed to start voice chat. Please try again.");
    resetUIState();
  }
}

// Reset UI state
function resetUIState() {
  if (videoElement) {
    videoElement.srcObject = null;
  }
  endButton.disabled = true;
  micIndicator.classList.remove('active');
  avatarMessageBuffer = "";
  isAvatarLoaded = false;
}

async function terminateAvatarSession() {
  if (!avatar || !sessionData) return;

  try {
    if (avatar) {
      await avatar.closeVoiceChat();
    }
    await avatar.stopAvatar();
    avatar = null;
    sessionData = null;
    resetUIState();

    // Hide the End Session button
    endButton.style.display = 'none';

    floatingContainer.classList.remove('expanded');
    placeholder.style.display = 'block';
    videoElement.style.display = 'none';
    console.log("Avatar session terminated successfully");
  } catch (error) {
    console.error("Error terminating avatar session:", error);
    resetUIState();
  }
}


// Set up avatar event listeners
function setupAvatarEventListeners() {
  if (!avatar) return;

  avatar.on(StreamingEvents.STREAM_READY, handleStreamReady);
  avatar.on(StreamingEvents.STREAM_DISCONNECTED, handleStreamDisconnected);
  avatar.on(StreamingEvents.USER_TALKING_MESSAGE, handleUserTalkingMessage);
  avatar.on(StreamingEvents.AVATAR_TALKING_MESSAGE, handleAvatarTalkingMessage);
}

floatingContainer.addEventListener('click', async () => {
  if (!floatingContainer.classList.contains('expanded')) {
    console.log("Expanding floating container");
    floatingContainer.classList.add('expanded');
    placeholder.style.display = 'none';
    videoElement.style.display = 'block';

    // Show the loading message
    const loadingMessage = document.getElementById("loadingMessage");
    if (loadingMessage) {
      loadingMessage.style.display = 'block';
    }

    // Show the End Session button when expanded
    endButton.style.display = 'block';

    console.log("Starting session...");
    try {
      await initializeAvatarSession();
    } catch (error) {
      console.error("Error during session initialization:", error);
    }
  }
});

endButton.addEventListener("click", (e) => {
  e.stopPropagation();
  terminateAvatarSession();
});

sendButton.addEventListener("click", handleUserSpeak);

// Add event listener for Enter key in input
userInput.addEventListener("keypress", (event) => {
  if (event.key === "Enter") {
    handleUserSpeak();
  }
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
  if (avatar) {
    terminateAvatarSession();
  }
});