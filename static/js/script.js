document.addEventListener('DOMContentLoaded', function() {
    // DOM elements
    const runWorkflowBtn = document.getElementById('run-workflow');
    const clearLogsBtn = document.getElementById('clear-logs');
    const taskInput = document.getElementById('task-input');
    const logsContainer = document.getElementById('logs');
    const streamFrame = document.getElementById('stream-frame');
    const streamPlaceholder = document.getElementById('stream-placeholder');
    const sandboxIdSpan = document.getElementById('sandbox-id');
    const exampleTaskBtns = document.querySelectorAll('.example-task');
    const stopDesktopBtn = document.getElementById('stop-desktop');
    const sandboxTimerSpan = document.getElementById('sandbox-timer');
    const sandboxControlsDiv = document.getElementById('sandbox-controls');
    
    // Session management
    const sessionId = generateSessionId();
    
    // WebSocket connection and timer variables
    let socket = null;
    let timerInterval = null;
    let sandboxTimeout = 1200; // Default timeout in seconds (will be updated from server)
    
    // Generate unique session ID
    function generateSessionId() {
        return 'browser_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }
    
    // Display session info
    function displaySessionInfo() {
        const sessionInfo = document.createElement('div');
        sessionInfo.className = 'alert alert-info mt-2';
        sessionInfo.innerHTML = `<small><strong>Browser Session ID:</strong> ${sessionId}</small>`;
        
        const controlsCard = document.querySelector('.card-body');
        if (controlsCard) {
            controlsCard.insertBefore(sessionInfo, controlsCard.firstChild);
        }
    }
    
    // Initialize session info display
    displaySessionInfo();
    
    // Connect to WebSocket
    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        addLog('Attempting to connect to WebSocket...', 'info');
        
        try {
            socket = new WebSocket(wsUrl);
            
            socket.onopen = function(e) {
                addLog(`WebSocket connection established (Session: ${sessionId})`, 'success');
                
                // Send session identification message
                socket.send(JSON.stringify({
                    action: 'identify_session',
                    session_id: sessionId
                }));
            };
        
        socket.onmessage = function(event) {
            const data = JSON.parse(event.data);
            
            switch(data.type) {
                case 'stdout':
                    addLog(data.data, 'stdout', data.timestamp);
                    break;
                case 'stderr':
                    addLog(data.data, 'stderr', data.timestamp);
                    break;
                case 'info':
                    addLog(data.data, 'info');
                    break;
                case 'error':
                    addLog(data.data, 'error');
                    break;
                case 'desktop_started':
                    handleDesktopStarted(data.data);
                    break;
                case 'desktop_killed':
                    handleDesktopKilled();
                    break;
                case 'task_completed':
                    addLog(data.data, 'success');
                    break;
                default:
                    addLog(JSON.stringify(data), 'info');
            }
        };
        
        socket.onclose = function(event) {
            if (event.wasClean) {
                addLog(`WebSocket connection closed cleanly, code=${event.code}, reason=${event.reason}`, 'info');
            } else {
                // Check for authentication errors (code 1008 is policy violation)
                if (event.code === 1008) {
                    addLog('WebSocket authentication failed. Please log in again.', 'error');
                    // Redirect to login page after a short delay
                    setTimeout(() => {
                        window.location.href = '/login';
                    }, 3000);
                } else {
                    addLog(`WebSocket connection died unexpectedly. Code: ${event.code}`, 'error');
                    // Try to reconnect after a delay for non-auth errors
                    setTimeout(connectWebSocket, 3000);
                }
            }
        };
        
        socket.onerror = function(error) {
            // Handle WebSocket errors - note that the error object might not have a message property
            addLog(`WebSocket connection error. Please check your network connection and try refreshing the page.`, 'error');
            console.error('WebSocket error:', error);
            
            // Check if cookies are enabled
            if (!navigator.cookieEnabled) {
                addLog('Cookies are disabled in your browser. Please enable cookies for WebSocket authentication to work.', 'error');
            }
        };
        } catch (err) {
            addLog(`Failed to create WebSocket connection: ${err.message}`, 'error');
            console.error('WebSocket creation error:', err);
        }
    }
    
    // Add log entry to the logs container
    function addLog(message, type = 'info', timestamp = null) {
        const logEntry = document.createElement('div');
        logEntry.className = `log-entry log-${type}`;
        
        if (timestamp) {
            const timestampSpan = document.createElement('span');
            timestampSpan.className = 'log-timestamp';
            timestampSpan.textContent = `[${timestamp}]`;
            logEntry.appendChild(timestampSpan);
        } else {
            const now = new Date();
            const timestampStr = now.toTimeString().split(' ')[0];
            const timestampSpan = document.createElement('span');
            timestampSpan.className = 'log-timestamp';
            timestampSpan.textContent = `[${timestampStr}]`;
            logEntry.appendChild(timestampSpan);
        }
        
        const messageSpan = document.createElement('span');
        messageSpan.textContent = message;
        logEntry.appendChild(messageSpan);
        
        logsContainer.appendChild(logEntry);
        logsContainer.scrollTop = logsContainer.scrollHeight;
    }
    
    // Handle desktop started event
    function handleDesktopStarted(data) {
        // Update UI
        
        // Show sandbox ID and session info
        if (data.sandbox_id) {
            const sessionInfo = data.session_id ? ` (Session: ${data.session_id})` : '';
            sandboxIdSpan.textContent = `Sandbox ID: ${data.sandbox_id}${sessionInfo}`;
        }
        
        // Load stream URL in iframe
        if (data.stream_url) {
            streamFrame.src = data.stream_url;
            streamFrame.style.display = 'block';
            streamPlaceholder.style.display = 'none';
        }
        
        // Enable stop button
        stopDesktopBtn.disabled = false;
        stopDesktopBtn.classList.add('btn-danger');
        stopDesktopBtn.classList.remove('btn-secondary');
        
        // Show sandbox controls
        sandboxControlsDiv.style.display = 'flex';
        
        // Start timer if timeout is provided
        if (data.timeout) {
            sandboxTimeout = parseInt(data.timeout);
            startSandboxTimer(sandboxTimeout);
        } else {
            startSandboxTimer(sandboxTimeout); // Use default timeout
        }
        
        addLog('Desktop started successfully', 'success');
    }
    
    // Start sandbox timer
    function startSandboxTimer(timeoutSeconds) {
        // Clear any existing timer
        if (timerInterval) {
            clearInterval(timerInterval);
        }
        
        // Set initial time
        let remainingSeconds = timeoutSeconds;
        updateTimerDisplay(remainingSeconds);
        
        // Start the timer
        timerInterval = setInterval(() => {
            remainingSeconds--;
            
            if (remainingSeconds <= 0) {
                // Timer expired
                clearInterval(timerInterval);
                timerInterval = null;
                addLog('Sandbox timeout reached', 'warning');
                // The desktop will be automatically killed by the server
            }
            
            updateTimerDisplay(remainingSeconds);
        }, 1000);
    }
    
    // Update timer display
    function updateTimerDisplay(seconds) {
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        
        // Format as MM:SS
        const formattedTime = `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
        
        // Update display
        sandboxTimerSpan.textContent = formattedTime;
        
        // Change color based on remaining time
        if (seconds < 60) {
            sandboxTimerSpan.className = 'badge bg-danger me-2'; // Less than 1 minute
        } else if (seconds < 300) {
            sandboxTimerSpan.className = 'badge bg-warning me-2'; // Less than 5 minutes
        } else {
            sandboxTimerSpan.className = 'badge bg-secondary me-2'; // More than 5 minutes
        }
    }
    
    // Handle desktop killed event
    function handleDesktopKilled() {
        // Update UI
        
        // Clear sandbox ID
        sandboxIdSpan.textContent = '';
        
        // Hide iframe and show placeholder
        streamFrame.src = '';
        streamFrame.style.display = 'none';
        streamPlaceholder.style.display = 'flex';
        
        // Disable stop button
        stopDesktopBtn.disabled = true;
        stopDesktopBtn.classList.remove('btn-danger');
        stopDesktopBtn.classList.add('btn-secondary');
        
        // Hide sandbox controls
        sandboxControlsDiv.style.display = 'none';
        
        // Stop timer
        if (timerInterval) {
            clearInterval(timerInterval);
            timerInterval = null;
        }
        
        // Reset timer display
        sandboxTimerSpan.textContent = '00:00';
        sandboxTimerSpan.className = 'badge bg-secondary me-2';
        
        addLog('Desktop killed successfully', 'success');
    }
    
    // Run full workflow
    // Run full workflow
    runWorkflowBtn.addEventListener('click', async function() {
        const query = taskInput.value.trim();
        
        if (!query) {
            addLog('Please enter a task prompt', 'error');
            return;
        }
        
        // Show sandbox controls when task is started
        sandboxControlsDiv.style.display = 'flex';
        
        addLog(`Starting full workflow with task: ${query}`, 'info');
        
        try {
            const formData = new FormData();
            formData.append('query', query);
            formData.append('session_id', sessionId);
            
            const response = await fetch('/run-workflow', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (data.status === 'error') {
                addLog(`Error running workflow: ${data.message}`, 'error');
            } else {
                addLog('Workflow started successfully', 'success');
            }
        } catch (error) {
            addLog(`Error running workflow: ${error.message}`, 'error');
        }
    });
    
    // Clear logs function
    function clearLogs() {
        logsContainer.innerHTML = '';
        // Send message to server to clear logs buffer
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({action: 'clear_logs'}));
        }
        addLog('Logs cleared', 'info');
    }
    
    // Clear logs on page load
    function clearLogsOnPageLoad() {
        // Wait for WebSocket connection to be established
        setTimeout(() => {
            if (socket && socket.readyState === WebSocket.OPEN) {
                clearLogs();
            } else {
                // If WebSocket isn't ready yet, try again in a second
                setTimeout(clearLogsOnPageLoad, 1000);
            }
        }, 500);
    }
    
    // Clear logs button click handler
    clearLogsBtn.addEventListener('click', clearLogs);
    
    // Example task buttons
    exampleTaskBtns.forEach(button => {
        button.addEventListener('click', function() {
            const prompt = this.getAttribute('data-prompt');
            if (prompt) {
                // Set the prompt in the task input
                taskInput.value = prompt;
                
                // Highlight the selected button
                exampleTaskBtns.forEach(btn => btn.classList.remove('active', 'btn-secondary'));
                this.classList.add('active', 'btn-secondary');
                this.classList.remove('btn-outline-secondary');
                
                // Log the selection
                addLog(`Example task selected: ${this.textContent}`, 'info');
                
                // Run the task automatically
                runWorkflowBtn.click();
            }
        });
    });
    
    // Stop desktop button
    stopDesktopBtn.addEventListener('click', async function() {
        if (confirm('Are you sure you want to stop the desktop?')) {
            addLog('Stopping desktop...', 'info');
            
            try {
                const formData = new FormData();
                formData.append('session_id', sessionId);
                
                const response = await fetch('/kill-desktop', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.status === 'error') {
                    addLog(`Error stopping desktop: ${data.message}`, 'error');
                }
                // Success will be handled by the WebSocket message
            } catch (error) {
                addLog(`Error stopping desktop: ${error.message}`, 'error');
            }
        }
    });
    
    // Initialize WebSocket connection
    connectWebSocket();
    
    // Clear logs on page load
    clearLogsOnPageLoad();
    
    // Initial log
    addLog('WebUI initialized. Ready to start desktop.', 'info');
    
    // Image enlargement functionality
    const architectureImages = document.querySelectorAll('.architecture-img');
    const imageModal = new bootstrap.Modal(document.getElementById('imageModal'));
    const modalImage = document.getElementById('modalImage');
    const modalTitle = document.getElementById('imageModalLabel');
    
    // Function to initialize image click handlers
    function initializeImageModals() {
        // Get all architecture images again (in case new ones were added dynamically)
        const allArchitectureImages = document.querySelectorAll('.architecture-img');
        
        allArchitectureImages.forEach(img => {
            // Remove any existing click listeners to avoid duplicates
            img.removeEventListener('click', handleImageClick);
            
            // Add styling
            img.style.cursor = 'pointer';
            img.title = 'Click to enlarge';
            
            // Add click event
            img.addEventListener('click', handleImageClick);
        });
    }
    
    // Image click handler function
    function handleImageClick() {
        modalImage.src = this.src;
        
        // Set modal title based on image context
        if (this.alt) {
            modalTitle.textContent = this.alt;
        } else {
            // Try to find a heading before the image
            const prevHeading = this.previousElementSibling;
            if (prevHeading && (prevHeading.tagName === 'H4' || prevHeading.tagName === 'H3')) {
                modalTitle.textContent = prevHeading.textContent;
            } else {
                modalTitle.textContent = 'Enlarged Image';
            }
        }
        
        // Show the modal
        imageModal.show();
    }
    
    // Initialize all image modals
    initializeImageModals();
    
    // Re-initialize on page changes or dynamic content loading
    document.addEventListener('DOMContentLoaded', initializeImageModals);
});
