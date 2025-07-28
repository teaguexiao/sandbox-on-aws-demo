// Computer Use JavaScript functionality
class ComputerUseInterface {
    constructor() {
        this.ws = null;
        this.isConnected = false;
        this.sessionId = this.generateSessionId();
        this.currentSandboxId = null;
        this.currentStreamUrl = null;
        this.isTaskRunning = false;
        this.startTime = null;
        this.timerInterval = null;
        this.sandboxTimeout = 1200000; // Default timeout in seconds (will be updated from server)
        
        this.initializeEventListeners();
        this.connectWebSocket();
        this.displaySessionInfo();
    }

    generateSessionId() {
        return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    displaySessionInfo() {
        // Add session ID to the UI for debugging/monitoring
        const sessionInfo = document.createElement('div');
        sessionInfo.className = 'alert alert-info mt-2';
        sessionInfo.innerHTML = `<small><strong>Session ID:</strong> ${this.sessionId}</small>`;
        
        const controlsCard = document.querySelector('.card-body');
        if (controlsCard) {
            controlsCard.insertBefore(sessionInfo, controlsCard.firstChild);
        }
    }

    initializeEventListeners() {
        // Example task buttons
        document.querySelectorAll('.example-task').forEach(button => {
            button.addEventListener('click', (e) => {
                const prompt = e.target.dataset.prompt;
                document.getElementById('task-input').value = prompt;
            });
        });

        // Main action buttons
        document.getElementById('start-computer-use').addEventListener('click', () => {
            this.startComputerUse();
        });

        document.getElementById('run-computer-task').addEventListener('click', () => {
            this.runComputerTask();
        });

        document.getElementById('take-screenshot').addEventListener('click', () => {
            this.takeScreenshot();
        });

        document.getElementById('stop-task').addEventListener('click', () => {
            this.stopTask();
        });

        document.getElementById('stop-desktop').addEventListener('click', () => {
            this.stopDesktop();
        });

        document.getElementById('clear-logs').addEventListener('click', () => {
            this.clearLogs();
        });

        // Screenshot click handler removed since screenshot display is removed
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        // Initialize reconnection tracking if not exists
        if (!this.reconnectAttempts) {
            this.reconnectAttempts = 0;
            this.maxReconnectAttempts = 5;
            this.reconnectDelay = 3000;
        }
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected for session:', this.sessionId);
            this.isConnected = true;
            this.reconnectAttempts = 0; // Reset on successful connection
            this.addLog(`Connected to server (Session: ${this.sessionId})`, 'info');
            
            // Send session identification message
            this.ws.send(JSON.stringify({
                action: 'identify_session',
                session_id: this.sessionId
            }));
        };
        
        this.ws.onmessage = (event) => {
            try {
                this.handleWebSocketMessage(JSON.parse(event.data));
            } catch (error) {
                console.error('Error parsing WebSocket message:', error);
                this.addLog('Error parsing server message', 'error');
            }
        };
        
        this.ws.onclose = (event) => {
            console.log('WebSocket disconnected, code:', event.code, 'reason:', event.reason);
            this.isConnected = false;
            
            if (this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnectAttempts++;
                const delay = this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1);
                this.addLog(`Disconnected from server. Reconnecting in ${(delay/1000).toFixed(1)}s... (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`, 'warning');
                
                setTimeout(() => {
                    this.connectWebSocket();
                }, delay);
            } else {
                this.addLog('Max reconnection attempts reached. Please refresh the page.', 'error');
            }
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.addLog('WebSocket connection error', 'error');
        };
    }

    handleWebSocketMessage(message) {
        const { type, data, timestamp } = message;
        
        switch (type) {
            case 'desktop_started':
                this.handleDesktopStarted(data);
                break;
            case 'screenshot':
                this.handleScreenshot(data);
                break;
            case 'reasoning':
                this.handleReasoning(data);
                break;
            case 'action':
                this.handleAction(data);
                break;
            case 'action_completed':
                this.handleActionCompleted(data);
                break;
            case 'task_completed':
                this.handleTaskCompleted(data);
                break;
            case 'error':
                this.handleError(data);
                break;
            case 'info':
            case 'stdout':
            case 'stderr':
                this.addLog(data, type);
                // Check if this is a task status update
                if (data && typeof data === 'string') {
                    if (data.includes('Starting computer use task') || data.includes('Running computer use task')) {
                        this.isTaskRunning = true;
                        this.updateButtonStates();
                    } else if (data.includes('Computer task stopped') || data.includes('Task was terminated')) {
                        this.isTaskRunning = false;
                        this.updateButtonStates();
                    }
                }
                break;
            case 'desktop_killed':
                this.handleDesktopKilled();
                break;
        }
    }

    handleDesktopStarted(data) {
        this.currentSandboxId = data.sandbox_id;
        this.currentStreamUrl = data.stream_url;
        this.startTime = Date.now();
        
        // Update session ID if provided by server
        if (data.session_id) {
            this.sessionId = data.session_id;
        }
        
        // Show sandbox controls
        document.getElementById('sandbox-controls').style.display = 'flex';
        document.getElementById('sandbox-id').textContent = `ID: ${this.currentSandboxId}`;
        
        // Show stream
        const streamFrame = document.getElementById('stream-frame');
        const streamPlaceholder = document.getElementById('stream-placeholder');
        
        streamFrame.src = this.currentStreamUrl;
        streamFrame.style.display = 'block';
        streamPlaceholder.style.display = 'none';
        
        // Enable controls
        this.enableControls(true);
        
        // Start timer
        this.startTimer();
        
        this.addLog(`Desktop started: ${this.currentSandboxId} (Session: ${this.sessionId})`, 'info');
    }

    handleScreenshot(data) {
        // Screenshot functionality removed to prevent layout issues
        // The desktop stream iframe provides the visual feedback
        this.addLog('Screenshot taken (displayed in desktop stream)', 'info');
    }

    handleReasoning(data) {
        const reasoningSection = document.getElementById('reasoning-section');
        const reasoningContent = document.getElementById('reasoning-content');
        
        reasoningContent.textContent = data;
        reasoningSection.style.display = 'block';
        
        // Auto-scroll to bottom
        reasoningContent.scrollTop = reasoningContent.scrollHeight;
    }

    handleAction(data) {
        const currentAction = document.getElementById('current-action');
        const actionDescription = document.getElementById('action-description');
        
        let description = `${data.action}`;
        if (data.coordinate) {
            description += ` at (${data.coordinate[0]}, ${data.coordinate[1]})`;
        }
        if (data.text) {
            description += `: "${data.text}"`;
        }
        
        actionDescription.textContent = description;
        currentAction.style.display = 'block';
        currentAction.className = 'alert alert-warning';
        
        this.addLog(`Action: ${description}`, 'action');
    }

    handleActionCompleted(data) {
        const currentAction = document.getElementById('current-action');
        currentAction.className = 'alert alert-success';
        
        setTimeout(() => {
            currentAction.style.display = 'none';
        }, 2000);
        
        this.addLog(`Action completed: ${data.success ? 'Success' : 'Failed'}`, 'info');
    }

    handleTaskCompleted(data) {
        this.isTaskRunning = false;
        this.updateButtonStates();
        
        // Hide current action
        document.getElementById('current-action').style.display = 'none';
        
        this.addLog('Task completed successfully', 'success');
    }

    handleError(data) {
        this.isTaskRunning = false;
        this.updateButtonStates();
        
        // Hide current action
        document.getElementById('current-action').style.display = 'none';
        
        this.addLog(`Error: ${data}`, 'error');
    }

    handleDesktopKilled() {
        this.currentSandboxId = null;
        this.currentStreamUrl = null;
        this.isTaskRunning = false;
        
        // Hide sandbox controls
        document.getElementById('sandbox-controls').style.display = 'none';
        
        // Hide stream
        const streamFrame = document.getElementById('stream-frame');
        const streamPlaceholder = document.getElementById('stream-placeholder');
        
        streamFrame.style.display = 'none';
        streamPlaceholder.style.display = 'block';
        
        // Hide reasoning and action displays
        document.getElementById('reasoning-section').style.display = 'none';
        document.getElementById('current-action').style.display = 'none';
        
        // Disable controls
        this.enableControls(false);
        
        // Stop timer
        this.stopTimer();
        
        this.addLog('Desktop stopped', 'info');
    }

    handleScreenshotClick(event) {
        const rect = event.target.getBoundingClientRect();
        const x = Math.round(event.clientX - rect.left);
        const y = Math.round(event.clientY - rect.top);
        
        this.addLog(`Screenshot clicked at (${x}, ${y})`, 'info');
        
        // You could add functionality here to send click coordinates to Claude
    }

    async startComputerUse() {
        if (!this.isConnected) {
            this.addLog('Not connected to server', 'error');
            return;
        }

        const taskInput = document.getElementById('task-input').value.trim();
        if (!taskInput) {
            this.addLog('Please enter a task description', 'error');
            return;
        }

        try {
            this.addLog('Starting computer use session...', 'info');
            
            // Start desktop and run task
            const response = await fetch('/run-computer-use-task', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `query=${encodeURIComponent(taskInput)}&session_id=${encodeURIComponent(this.sessionId)}`
            });
            
            // Check if response is ok
            if (!response.ok) {
                const errorText = await response.text();
                this.addLog(`Server error (${response.status}): ${errorText}`, 'error');
                return;
            }
            
            // Check if response is JSON
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                const responseText = await response.text();
                this.addLog(`Server returned non-JSON response: ${responseText.substring(0, 200)}...`, 'error');
                return;
            }
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.isTaskRunning = true;
                this.updateButtonStates();
                this.addLog('Computer use task started', 'success');
                // Update session ID if server provided one
                if (result.session_id) {
                    this.sessionId = result.session_id;
                }
            } else {
                this.addLog(`Failed to start: ${result.message}`, 'error');
                this.isTaskRunning = false;
                this.updateButtonStates();
            }
        } catch (error) {
            this.addLog(`Error starting computer use: ${error.message}`, 'error');
        }
    }

    async runComputerTask() {
        if (!this.currentSandboxId) {
            this.addLog('No active desktop session', 'error');
            return;
        }

        const taskInput = document.getElementById('task-input').value.trim();
        if (!taskInput) {
            this.addLog('Please enter a task description', 'error');
            return;
        }

        try {
            this.isTaskRunning = true;
            this.updateButtonStates();
            
            const response = await fetch('/run-computer-task', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `query=${encodeURIComponent(taskInput)}&session_id=${encodeURIComponent(this.sessionId)}&sandbox_id=${this.currentSandboxId}`
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.addLog('Task started', 'success');
            } else {
                this.addLog(`Failed to start task: ${result.message}`, 'error');
                this.isTaskRunning = false;
                this.updateButtonStates();
            }
        } catch (error) {
            this.addLog(`Error running task: ${error.message}`, 'error');
            this.isTaskRunning = false;
            this.updateButtonStates();
        }
    }

    async takeScreenshot() {
        if (!this.currentSandboxId) {
            this.addLog('No active desktop session', 'error');
            return;
        }

        try {
            const response = await fetch('/take-computer-screenshot', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `session_id=${encodeURIComponent(this.sessionId)}&sandbox_id=${this.currentSandboxId}`
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.addLog('Screenshot requested', 'info');
            } else {
                this.addLog(`Failed to take screenshot: ${result.message}`, 'error');
            }
        } catch (error) {
            this.addLog(`Error taking screenshot: ${error.message}`, 'error');
        }
    }

    async stopTask() {
        if (!this.isTaskRunning) {
            this.addLog('No task is currently running', 'info');
            return;
        }

        try {
            this.addLog('Stopping task...', 'info');
            
            const response = await fetch('/stop-computer-task', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `session_id=${encodeURIComponent(this.sessionId)}`
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                // Don't immediately set isTaskRunning = false here
                // Wait for the WebSocket message to confirm the task stopped
                this.addLog('Task stop requested', 'info');
            } else {
                this.addLog(`Failed to stop task: ${result.message}`, 'error');
                // Only reset state if the stop request failed
                this.isTaskRunning = false;
                this.updateButtonStates();
            }
        } catch (error) {
            this.addLog(`Error stopping task: ${error.message}`, 'error');
            this.isTaskRunning = false;
            this.updateButtonStates();
        }
    }

    async stopDesktop() {
        if (!this.currentSandboxId) {
            this.addLog('No active desktop session', 'error');
            return;
        }

        try {
            const response = await fetch('/kill-computer-desktop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `session_id=${encodeURIComponent(this.sessionId)}`
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.addLog('Desktop stopping...', 'info');
            } else {
                this.addLog(`Failed to stop desktop: ${result.message}`, 'error');
            }
        } catch (error) {
            this.addLog(`Error stopping desktop: ${error.message}`, 'error');
        }
    }

    enableControls(hasDesktop) {
        // Set the current desktop state
        this.currentSandboxId = hasDesktop ? this.currentSandboxId : null;
        
        // Update all button states based on desktop and task status
        this.updateButtonStates();
    }

    updateButtonStates() {
        const startBtn = document.getElementById('start-computer-use');
        const runBtn = document.getElementById('run-computer-task');
        const stopBtn = document.getElementById('stop-task');
        const stopDesktopBtn = document.getElementById('stop-desktop');
        const takeScreenshotBtn = document.getElementById('take-screenshot');
        
        if (this.isTaskRunning) {
            // Task is running - disable start/run, enable stop
            startBtn.disabled = true;
            runBtn.disabled = true;
            stopBtn.disabled = false;
            stopDesktopBtn.disabled = true; // Don't allow killing desktop while task runs
            takeScreenshotBtn.disabled = false; // Allow screenshots during task
        } else {
            // No task running
            startBtn.disabled = !!this.currentSandboxId; // Disable if desktop exists
            runBtn.disabled = !this.currentSandboxId; // Enable only if desktop exists
            stopBtn.disabled = true; // No task to stop
            stopDesktopBtn.disabled = !this.currentSandboxId; // Enable only if desktop exists
            takeScreenshotBtn.disabled = !this.currentSandboxId; // Enable only if desktop exists
        }
    }

    startTimer() {
        this.timerInterval = setInterval(() => {
            if (this.startTime) {
                const elapsed = this.sandboxTimeout - (Date.now() - this.startTime);
                const minutes = Math.floor(elapsed / 60000);
                const seconds = Math.floor((elapsed % 60000) / 1000);
                console.log(minutes.toString() + " :" + seconds.toString())
                
                document.getElementById('sandbox-timer').textContent = 
                    `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            }
        }, 1000);
    }

    stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
        document.getElementById('sandbox-timer').textContent = '00:00';
    }

    addLog(message, type = 'info') {
        const logsDiv = document.getElementById('logs');
        const timestamp = new Date().toLocaleTimeString();
        
        const logEntry = document.createElement('div');
        logEntry.className = `log-entry log-${type}`;
        
        let badge = '';
        let textClass = '';
        
        switch (type) {
            case 'error':
                badge = '<span class="badge bg-danger">ERROR</span>';
                textClass = 'text-danger';
                break;
            case 'success':
                badge = '<span class="badge bg-success">SUCCESS</span>';
                textClass = 'text-success';
                break;
            case 'action':
                badge = '<span class="badge bg-warning">ACTION</span>';
                textClass = 'text-warning';
                break;
            case 'reasoning':
                badge = '<span class="badge bg-info">THINKING</span>';
                textClass = 'text-info';
                break;
            case 'screenshot':
                badge = '<span class="badge bg-secondary">SCREENSHOT</span>';
                textClass = 'text-secondary';
                break;
            case 'stdout':
                badge = '<span class="badge bg-primary">STDOUT</span>';
                break;
            case 'stderr':
                badge = '<span class="badge bg-warning">STDERR</span>';
                break;
            default:
                badge = '<span class="badge bg-secondary">INFO</span>';
        }
        
        logEntry.innerHTML = `<small class="text-muted">[${timestamp}]</small> ${badge} <span class="${textClass}">${this.escapeHtml(message)}</span>`;
        
        logsDiv.appendChild(logEntry);
        logsDiv.scrollTop = logsDiv.scrollHeight;
    }

    clearLogs() {
        document.getElementById('logs').innerHTML = '';
        
        if (this.ws && this.isConnected) {
            this.ws.send(JSON.stringify({ action: 'clear_logs' }));
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
    new ComputerUseInterface();
});
