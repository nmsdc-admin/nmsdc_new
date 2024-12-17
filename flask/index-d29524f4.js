const baseUrl = "http://localhost:8084/api/v0";

function addMessageToChat(sender, message) {
    const chatWindow = document.getElementById("chat-window");
    const messageDiv = document.createElement("div");
    messageDiv.classList.add("chat-message");

    const avatar = document.createElement("img");
    avatar.classList.add("message-avatar");
    avatar.alt = sender === "user" ? "User Avatar" : "Bot Avatar";
    avatar.src = sender === "user" 
        ? "https://cdn.icon-icons.com/icons2/1378/PNG/512/avatardefault_92824.png" 
        : "https://st5.depositphotos.com/72897924/62255/v/450/depositphotos_622556394-stock-illustration-robot-web-icon-vector-illustration.jpg";

    const messageContent = document.createElement("div");
    messageContent.classList.add("message-content");

    if (sender === "user") {
        messageDiv.classList.add("user-message");
        messageContent.textContent = message;
    } else {
        messageDiv.classList.add("bot-message");

        if (message.toLowerCase().includes("sql") || message.includes("SELECT") || message.includes("FROM")) {
            messageContent.innerHTML = `<strong>${message}</strong>`;
        } else {
            messageContent.innerHTML = message;
        }

        // Show the "Start New Conversation" button when the bot replies
        createNewConversationButton();
    }

    const timeSpan = document.createElement("span");
    timeSpan.classList.add("message-time");
    timeSpan.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    messageContent.appendChild(timeSpan);

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(messageContent);
    chatWindow.appendChild(messageDiv);
    chatWindow.scrollTop = chatWindow.scrollHeight; 
}

function createNewConversationButton() {
    // Check if the button already exists
    if (document.getElementById("start-new-conversation-btn")) return;

    const button = document.createElement("button");
    button.id = "start-new-conversation-btn";
    button.textContent = "Start New Conversation";
    button.classList.add("start-new-conversation");
    button.onclick = startNewConversation;

    button.style.marginRight = "10px"; // Add margin to the right
    button.style.fontSize = "0.4rem"; // Smaller font size
    button.style.borderRadius = "8px"; // Rounded corners
    button.style.padding = "5px 10px"; // Padding for a rectangular shape
    button.style.border = "1px solid #007BFF"; // Optional border color
    button.style.backgroundColor = "#007BFF"; // Background color
    button.style.color = "#FFFFFF"; // Text color
    button.style.cursor = "pointer"; // Pointer cursor on hover
    // Append the button to the chat input div
    const chatInputDiv = document.querySelector(".chat-input");
    chatInputDiv.appendChild(button);
}

function startNewConversation() {
    const chatWindow = document.getElementById("chat-window");
    chatWindow.innerHTML = ""; // Clear chat window
    const defaultMessage = "How can I help you?";
    addMessageToChat("user", defaultMessage);

    // Remove the button after starting a new conversation
    const button = document.getElementById("start-new-conversation-btn");
    if (button) {
        button.remove(); // Remove the button
    }
}


let lastQuestion = "";

async function sendMessage() {
    const inputField = document.getElementById("user-input");
    const userMessage = inputField.value.trim();

    if (userMessage === "") return; 

    addMessageToChat("user", userMessage);
    inputField.value = ""; 

    showThinkingAnimation();

    let combinedQuestion;
    if (lastQuestion) {
        combinedQuestion = await generateRewrittenQuestion(lastQuestion, userMessage);
    } else {
        combinedQuestion = userMessage; // Initialize combinedQuestion with userMessage if lastQuestion is empty
    }
    combinedQuestion = combinedQuestion.replace("Combined question: ", "").trim();

    // Debugging: Check the value of combinedQuestion
    console.log("Combined Question:", combinedQuestion);

    lastQuestion = combinedQuestion; // Ensure lastQuestion is updated

    removeThinkingAnimation();

    // Add the rewritten question to chat for user visibility (optional)
    addMessageToChat("bot", `Interpreted question: ${combinedQuestion}`);

    showThinkingAnimation();

    // Pass the rewritten question to getBotResponse
    const botResponse = await getBotResponse(combinedQuestion);

    removeThinkingAnimation();

    addMessageToChat("bot", botResponse.text);

    // Check if botResponse.id is defined before calling runSqlQuery
    if (botResponse.id) {
        await runSqlQuery(botResponse.id);
    } else {
        console.error("No ID returned from bot response");
    }
}


async function generateRewrittenQuestion(lastQuestion, newQuestion) {
    const apiUrl = `${baseUrl}/generate_rewritten_question`;
    const params = new URLSearchParams({
        last_question: lastQuestion,
        new_question: newQuestion
    });

    try {
        const response = await fetch(`${apiUrl}?${params}`, { method: "GET" });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        
        // Check if the response format is correct
        if (data && data.question) {
            return data.question; // Return the question from the response
        } else {
            console.warn("Unexpected response format:", data);
            return `${lastQuestion} ${newQuestion}`; // Fallback to combining questions
        }
    } catch (error) {
        console.error("Error generating rewritten question:", error);
        return `${lastQuestion} ${newQuestion}`; // Fallback to combining questions
    }
}


async function getBotResponse(userMessage) {
    const apiUrl = `${baseUrl}/generate_sql?user=root&question=${encodeURIComponent(userMessage)}`;
    try {
        const response = await fetch(apiUrl, { method: "GET" });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json(); 
        return data; 
    } catch (error) {
        console.error("Error fetching response from API:", error);
        return { text: "Sorry, I couldn't process your request." }; 
    }
}

async function runSqlQuery(id) {
    const apiUrl = `${baseUrl}/run_sql?id=${id}`;
    try {
        const response = await fetch(apiUrl, { method: "GET" });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const dataFrame = await response.json(); 
        console.log("DataFrame received from run_sql API:", dataFrame);

        const tableHtml = generateTableHtml(dataFrame.df, id); 
        addMessageToChat("bot", tableHtml); 
    } catch (error) {
        console.error("Error running SQL query:", error);
        addMessageToChat("bot", "Error retrieving data for the table."); 
    }
}

function generateTableHtml(dataFrame, id) {
    const parsedData = JSON.parse(dataFrame); 
    if (!Array.isArray(parsedData) || parsedData.length === 0) {
        return "<p>No data available.</p>"; 
    }

    let tableHtml = `
        <div class="table-container"> <!-- Only use the table-container class here -->
            <table>
                <thead><tr>`;

    Object.keys(parsedData[0]).forEach(key => {
        tableHtml += `<th>${key}</th>`;
    });
    tableHtml += '</tr></thead><tbody>';

    const maxRowsToShow = 5; 
    const rowsToDisplay = parsedData.slice(0, maxRowsToShow);

    rowsToDisplay.forEach(row => {
        tableHtml += '<tr>';
        Object.values(row).forEach(value => {
            tableHtml += `<td>${value}</td>`;
        });
        tableHtml += '</tr>';
    });

    tableHtml += '</tbody></table></div>'; 

    tableHtml += `
        <div class="table-buttons">
            <button onclick="viewAllRows('${id}')">View All</button>
            <button onclick="downloadCSV('${id}')">Download CSV</button>
        </div>
    `;

    return tableHtml;
}

function viewAllRows(id) {

    window.open(`/view_all?id=${id}`, '_blank');
}

async function downloadCSV(id) {
    const apiUrl = `${baseUrl}/download_csv?id=${id}`;
    try {
        const response = await fetch(apiUrl, { method: "GET", headers: { "accept": "application/json" } });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const contentDisposition = response.headers.get("Content-Disposition");
        let fileName = "download.csv";
        if (contentDisposition && contentDisposition.includes("filename=")) {
            fileName = contentDisposition.split("filename=")[1].replace(/"/g, "");
        }

        const blob = await response.blob();

        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = fileName; 
        document.body.appendChild(link); 
        link.click(); 
        document.body.removeChild(link); 

    } catch (error) {
        console.error("Error downloading CSV:", error);
        alert("Failed to download CSV. Please try again.");
    }
}

async function fetchConversationHistory() {
    const apiUrl = `${baseUrl}/get_question_history`;
    try {
        const response = await fetch(apiUrl, { method: "GET" });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const historyData = await response.json();
        populateHistoryList(historyData.questions);
    } catch (error) {
        console.error("Error fetching conversation history:", error);
        alert("Failed to fetch conversation history.");
    }
}

function populateHistoryList(questions) {
    const historyList = document.getElementById("history-list");
    historyList.innerHTML = ""; 

    questions.forEach((question) => {
        const listItem = document.createElement("li");
        listItem.innerHTML = `
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" class="chat-icon" width="10" height="10">
    <path d="M160 368c26.5 0 48 21.5 48 48l0 16 72.5-54.4c8.3-6.2 18.4-9.6 28.8-9.6L448 368c8.8 0 16-7.2 16-16l0-288c0-8.8-7.2-16-16-16L64 48c-8.8 0-16 7.2-16 16l0 288c0 8.8 7.2 16 16 16l96 0zm48 124l-.2 .2-5.1 3.8-17.1 12.8c-4.8 3.6-11.3 4.2-16.8 1.5s-8.8-8.2-8.8-14.3l0-21.3 0-6.4 0-.3 0-4 0-48-48 0-48 0c-35.3 0-64-28.7-64-64L0 64C0 28.7 28.7 0 64 0L448 0c35.3 0 64 28.7 64 64l0 288c0 35.3-28.7 64-64 64l-138.7 0L208 492z"/>
  </svg> 
  ${question.question}`;

        listItem.onclick = () => loadConversation(question.id); 
        historyList.appendChild(listItem);
    });
}

async function loadConversation(id) {
    try {
        // Fetch data from the new API endpoint
        const response = await fetch(`http://localhost:8084/api/v0/load_question?id=${id}`);
        const data = await response.json();

        // Check if the response contains a valid question
        if (data && data.question) {
            const inputField = document.getElementById("user-input");
            inputField.value = data.question; // Set the input field with the question
            sendMessage(); // Call sendMessage to submit the question
        } else {
            console.error('No valid question found for ID:', id);
        }
    } catch (error) {
        console.error('Error fetching question:', error);
    }
}



function displayChatResult(conversation) {
    const chatWindow = document.getElementById('chat-window');
    chatWindow.innerHTML = ''; 

    conversation.forEach((message) => {
        const chatMessage = document.createElement('div');
        chatMessage.classList.add('chat-message');

        if (message.sender === 'SQL') {
            chatMessage.innerHTML = `
              <strong>${message.sender}:</strong> <span class="sql-response">${message.text}</span>
            `;
        } else {
            chatMessage.innerHTML = `
              <strong>${message.sender}:</strong> ${message.text}
            `;
        }

        chatWindow.appendChild(chatMessage);
    });

    chatWindow.scrollTop = chatWindow.scrollHeight;
}

function showThinkingAnimation() {
    const chatWindow = document.getElementById("chat-window");
    const thinkingDiv = document.createElement("div");
    thinkingDiv.classList.add("chat-message", "bot-message", "thinking");
    thinkingDiv.innerHTML = `
        <img src="https://st5.depositphotos.com/72897924/62255/v/450/depositphotos_622556394-stock-illustration-robot-web-icon-vector-illustration.jpg" 
             alt="Bot Avatar" class="message-avatar">
        <div class="message-content">
            Thinking
            <div class="thinking-dots">
                <div class="thinking-dot"></div>
                <div class="thinking-dot"></div>
                <div class="thinking-dot"></div>
            </div>
        </div>
    `;
    chatWindow.appendChild(thinkingDiv);
    chatWindow.scrollTop = chatWindow.scrollHeight; 
}

function removeThinkingAnimation() {
    const thinkingMessages = document.querySelectorAll(".thinking");
    thinkingMessages.forEach(message => message.remove());
}

document.addEventListener("DOMContentLoaded", () => {
    fetchConversationHistory(); 

    const inputField = document.getElementById("user-input");
    inputField.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            sendMessage();
        }
    });

    const sendButton = document.getElementById("send-button");
    sendButton.addEventListener("click", sendMessage);
});