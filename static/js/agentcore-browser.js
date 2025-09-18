/**
 * Agentcore BrowserTool JavaScript functionality
 * Handles the Agentcore BrowserTool tab interactions and WebSocket communication
 */

// Agentcore-specific DOM elements and variables
let agentcoreSessionId = null;
let agentcoreSocket = null;
let agentcoreTimerInterval = null;
let agentcoreSessionTimeout = 1200; // 20 minutes in seconds
let agentcoreBrowserStarted = false; // Track if browser has been started to prevent duplicates

// Generate unique session ID for Agentcore
function generateAgentcoreSessionId() {
    return 'agentcore_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

// Get current time string in GMT+8 timezone with 12-hour format
function getGMT8TimeString() {
    const now = new Date();
    return now.toLocaleTimeString('en-US', {
        timeZone: 'Asia/Singapore',
        hour12: true,
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit'
    });
}

// Initialize Agentcore BrowserTool functionality
function initAgentcoreBrowserTool() {
    // Get Agentcore-specific DOM elements
    const agentcoreTaskInput = document.getElementById('agentcore-task-input');
    const runAgentcoreTaskBtn = document.getElementById('run-agentcore-task');
    const clearAgentcoreLogsBtn = document.getElementById('clear-agentcore-logs');
    const agentcoreExampleTaskBtns = document.querySelectorAll('.agentcore-example-task');
    const stopAgentcoreBrowserBtn = document.getElementById('stop-agentcore-browser');
    const agentcoreTimerSpan = document.getElementById('agentcore-timer');
    const agentcoreSessionIdSpan = document.getElementById('agentcore-session-id');
    const agentcoreControlsDiv = document.getElementById('agentcore-controls');
    const agentcoreFullscreenBtn = document.getElementById('agentcore-fullscreen-btn');
    
    // Generate session ID
    agentcoreSessionId = generateAgentcoreSessionId();
    
    // Event listeners for Agentcore tab
    if (runAgentcoreTaskBtn) {
        runAgentcoreTaskBtn.addEventListener('click', function() {
            const prompt = agentcoreTaskInput.value.trim();
            if (prompt) {
                runAgentcoreBrowserTask(prompt);
            } else {
                addAgentcoreLog('Please enter a task prompt.', 'error');
            }
        });
    }
    
    if (clearAgentcoreLogsBtn) {
        clearAgentcoreLogsBtn.addEventListener('click', clearAgentcoreLogs);
    }
    
    if (stopAgentcoreBrowserBtn) {
        stopAgentcoreBrowserBtn.addEventListener('click', stopAgentcoreBrowser);
    }

    // Fullscreen button
    if (agentcoreFullscreenBtn) {
        agentcoreFullscreenBtn.addEventListener('click', function() {
            openAgentcoreFullscreen();
        });
    }

    // Example task buttons
    agentcoreExampleTaskBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const prompt = this.getAttribute('data-prompt');
            agentcoreTaskInput.value = prompt;
            
            // Remove active class from all buttons
            agentcoreExampleTaskBtns.forEach(b => b.classList.remove('active'));
            // Add active class to clicked button
            this.classList.add('active');
        });
    });
    
    // Initialize WebSocket connection for Agentcore
    connectAgentcoreWebSocket();

    // Initialize Bootstrap tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    const tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Initial log
    addAgentcoreLog('Agentcore BrowserTool initialized. Ready to start browser session.', 'info');
}

// Connect to WebSocket for Agentcore
function connectAgentcoreWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    addAgentcoreLog('Connecting to WebSocket for Agentcore...', 'info');
    
    try {
        agentcoreSocket = new WebSocket(wsUrl);
        
        agentcoreSocket.onopen = function(e) {
            addAgentcoreLog(`Agentcore WebSocket connection established (Session: ${agentcoreSessionId})`, 'success');
            
            // Send session identification message
            agentcoreSocket.send(JSON.stringify({
                action: 'identify_session',
                session_id: agentcoreSessionId
            }));
        };
        
        agentcoreSocket.onmessage = function(event) {
            const data = JSON.parse(event.data);
            
            switch(data.type) {
                case 'agentcore_browser_started':
                    handleAgentcoreBrowserStarted(data.data);
                    break;
                case 'agentcore_browser_stopped':
                    handleAgentcoreBrowserStopped();
                    break;
                case 'agentcore_task_completed':
                    addAgentcoreLog(data.data, 'success');
                    break;
                case 'stdout':
                case 'stderr':
                case 'info':
                case 'error':
                    addAgentcoreLog(data.data, data.type, data.timestamp);
                    break;
                default:
                    addAgentcoreLog(JSON.stringify(data), 'info');
            }
        };
        
        agentcoreSocket.onclose = function(event) {
            if (event.wasClean) {
                addAgentcoreLog(`Agentcore WebSocket connection closed cleanly, code=${event.code}`, 'info');
            } else {
                if (event.code === 1008) {
                    addAgentcoreLog('Agentcore WebSocket authentication failed. Please log in again.', 'error');
                    setTimeout(() => {
                        window.location.href = '/login';
                    }, 3000);
                } else {
                    addAgentcoreLog(`Agentcore WebSocket connection died unexpectedly. Code: ${event.code}`, 'error');
                    setTimeout(connectAgentcoreWebSocket, 3000);
                }
            }
        };
        
        agentcoreSocket.onerror = function(error) {
            addAgentcoreLog('Agentcore WebSocket error occurred', 'error');
        };
        
    } catch (error) {
        addAgentcoreLog(`Failed to connect to Agentcore WebSocket: ${error.message}`, 'error');
    }
}

// Run Agentcore browser task
async function runAgentcoreBrowserTask(prompt) {
    try {
        addAgentcoreLog(`Starting Agentcore browser task: ${prompt}`, 'info');

        // First, start the browser if not already started
        const startResponse = await fetch('/start-agentcore-browser', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams({
                'session_id': agentcoreSessionId,
                'region': 'us-west-2'
            })
        });

        const startResult = await startResponse.json();
        console.log('Start browser result:', startResult);
        addAgentcoreLog(`Start browser result: ${JSON.stringify(startResult)}`, 'info');

        if (startResult.status !== 'success') {
            addAgentcoreLog(`Failed to start browser: ${startResult.message}`, 'error');
            return;
        }

        // If we get a viewer_url directly from the start response, handle it immediately
        if (startResult.viewer_url) {
            addAgentcoreLog(`Received viewer URL from start response: ${startResult.viewer_url}`, 'info');
            handleAgentcoreBrowserStarted({
                session_id: startResult.session_id,
                viewer_url: startResult.viewer_url,
                status: 'ready'
            });
        }
        
        // Then run the task
        const taskResponse = await fetch('/run-agentcore-browser-task', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams({
                'prompt': prompt,
                'session_id': agentcoreSessionId
            })
        });
        
        const taskResult = await taskResponse.json();
        if (taskResult.status === 'success') {
            addAgentcoreLog('Agentcore browser task started successfully', 'success');
        } else {
            addAgentcoreLog(`Failed to start task: ${taskResult.message}`, 'error');
        }
        
    } catch (error) {
        addAgentcoreLog(`Error running Agentcore browser task: ${error.message}`, 'error');
    }
}

// Stop Agentcore browser
async function stopAgentcoreBrowser() {
    try {
        const response = await fetch('/stop-agentcore-browser', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams({
                'session_id': agentcoreSessionId
            })
        });
        
        const result = await response.json();
        if (result.status === 'success') {
            addAgentcoreLog('Agentcore browser stopped successfully', 'success');
        } else {
            addAgentcoreLog(`Failed to stop browser: ${result.message}`, 'error');
        }
        
    } catch (error) {
        addAgentcoreLog(`Error stopping Agentcore browser: ${error.message}`, 'error');
    }
}

// Handle Agentcore browser started
function handleAgentcoreBrowserStarted(data) {
    // Prevent duplicate handling
    if (agentcoreBrowserStarted) {
        addAgentcoreLog('Browser already started, ignoring duplicate event', 'info');
        return;
    }

    const agentcoreControlsDiv = document.getElementById('agentcore-controls');
    const agentcoreSessionIdSpan = document.getElementById('agentcore-session-id');
    const agentcoreBrowserFrame = document.getElementById('agentcore-browser-frame');
    const agentcoreBrowserPlaceholder = document.getElementById('agentcore-browser-placeholder');

    // Debug logging
    console.log('handleAgentcoreBrowserStarted called with data:', data);
    addAgentcoreLog(`Received browser started event: ${JSON.stringify(data)}`, 'info');

    if (agentcoreControlsDiv) {
        agentcoreControlsDiv.style.display = 'flex';
    }

    if (agentcoreSessionIdSpan) {
        agentcoreSessionIdSpan.textContent = data.session_id;
    }

    // Show browser frame if viewer URL is available
    if (data.viewer_url && agentcoreBrowserFrame && agentcoreBrowserPlaceholder) {
        addAgentcoreLog(`Setting iframe src to: ${data.viewer_url}`, 'info');

        // Function to check if the viewer server is healthy
        async function checkViewerHealth(url, maxAttempts = 10, delay = 1000) {
            addAgentcoreLog(`Starting health checks for URL: ${url}`, 'info');
            console.log('checkViewerHealth called with URL:', url);

            for (let attempt = 1; attempt <= maxAttempts; attempt++) {
                try {
                    const healthUrl = url + '/api/health';
                    addAgentcoreLog(`Health check attempt ${attempt}/${maxAttempts}: ${healthUrl}`, 'info');
                    console.log(`Health check attempt ${attempt}: ${healthUrl}`);

                    const response = await fetch(healthUrl, {
                        method: 'GET',
                        timeout: 5000
                    });

                    console.log(`Health check response:`, response);
                    addAgentcoreLog(`Health check response status: ${response.status}`, 'info');

                    if (response.ok) {
                        const healthData = await response.json();
                        console.log('Health data:', healthData);
                        if (healthData.status === 'healthy') {
                            addAgentcoreLog(`Viewer server is healthy (attempt ${attempt}/${maxAttempts})`, 'success');
                            return true;
                        }
                    }
                } catch (error) {
                    console.error(`Health check attempt ${attempt} error:`, error);
                    addAgentcoreLog(`Health check attempt ${attempt}/${maxAttempts} failed: ${error.message}`, 'info');
                }

                if (attempt < maxAttempts) {
                    await new Promise(resolve => setTimeout(resolve, delay));
                }
            }
            return false;
        }

        // Check server health before loading iframe
        checkViewerHealth(data.viewer_url).then(isHealthy => {
            if (isHealthy) {
                // Add error handling for iframe loading
                agentcoreBrowserFrame.onload = function() {
                    addAgentcoreLog('Browser viewer loaded successfully', 'success');
                };

                agentcoreBrowserFrame.onerror = function() {
                    addAgentcoreLog('Error loading browser viewer', 'error');
                    // Fallback: show placeholder again
                    agentcoreBrowserFrame.style.display = 'none';
                    agentcoreBrowserPlaceholder.style.display = 'flex';
                    agentcoreBrowserPlaceholder.innerHTML = '<p style="color: #dc3545; margin: 0;">Failed to load browser viewer. Check console for details.</p>';
                };

                // Set the iframe source
                agentcoreBrowserFrame.src = data.viewer_url;
                agentcoreBrowserFrame.style.display = 'block';
                agentcoreBrowserPlaceholder.style.display = 'none';
            } else {
                addAgentcoreLog('Viewer server health check failed - cannot display browser', 'error');
                agentcoreBrowserPlaceholder.innerHTML = '<p style="color: #dc3545; margin: 0;">Viewer server is not responding. Please try again.</p>';
            }
        }).catch(error => {
            addAgentcoreLog(`Error during health check: ${error.message}`, 'error');
            agentcoreBrowserPlaceholder.innerHTML = '<p style="color: #dc3545; margin: 0;">Failed to verify viewer server status.</p>';
        });
    } else {
        addAgentcoreLog('No viewer URL provided or iframe elements not found', 'error');
        console.log('Debug info:', {
            viewer_url: data.viewer_url,
            iframe_exists: !!agentcoreBrowserFrame,
            placeholder_exists: !!agentcoreBrowserPlaceholder
        });
    }

    // Show fullscreen button when browser session is active
    const agentcoreFullscreenBtn = document.getElementById('agentcore-fullscreen-btn');
    if (agentcoreFullscreenBtn) {
        agentcoreFullscreenBtn.style.display = 'inline-block';
    }

    // Start timer
    startAgentcoreTimer();

    // Mark as started
    agentcoreBrowserStarted = true;

    addAgentcoreLog('Agentcore browser session started successfully', 'success');
}

// Handle Agentcore browser stopped
function handleAgentcoreBrowserStopped() {
    const agentcoreControlsDiv = document.getElementById('agentcore-controls');
    const agentcoreBrowserFrame = document.getElementById('agentcore-browser-frame');
    const agentcoreBrowserPlaceholder = document.getElementById('agentcore-browser-placeholder');
    
    if (agentcoreControlsDiv) {
        agentcoreControlsDiv.style.display = 'none';
    }
    
    if (agentcoreBrowserFrame && agentcoreBrowserPlaceholder) {
        agentcoreBrowserFrame.style.display = 'none';
        agentcoreBrowserPlaceholder.style.display = 'block';
    }

    // Hide fullscreen button when browser session is stopped
    const agentcoreFullscreenBtn = document.getElementById('agentcore-fullscreen-btn');
    if (agentcoreFullscreenBtn) {
        agentcoreFullscreenBtn.style.display = 'none';
    }

    // Stop timer
    stopAgentcoreTimer();

    // Reset started flag
    agentcoreBrowserStarted = false;

    addAgentcoreLog('Agentcore browser session stopped', 'info');
}

// Start Agentcore timer
function startAgentcoreTimer() {
    let seconds = 0;
    agentcoreTimerInterval = setInterval(() => {
        seconds++;
        updateAgentcoreTimerDisplay(agentcoreSessionTimeout - seconds);
        
        if (seconds >= agentcoreSessionTimeout) {
            stopAgentcoreTimer();
            addAgentcoreLog('Agentcore session timeout reached', 'warning');
        }
    }, 1000);
}

// Stop Agentcore timer
function stopAgentcoreTimer() {
    if (agentcoreTimerInterval) {
        clearInterval(agentcoreTimerInterval);
        agentcoreTimerInterval = null;
    }
}

// Update Agentcore timer display
function updateAgentcoreTimerDisplay(seconds) {
    const agentcoreTimerSpan = document.getElementById('agentcore-timer');
    if (!agentcoreTimerSpan) return;
    
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    
    const formattedTime = `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    agentcoreTimerSpan.textContent = formattedTime;
    
    // Change color based on remaining time
    if (seconds < 60) {
        agentcoreTimerSpan.className = 'badge bg-danger me-2 py-2 px-3 fs-6';
    } else if (seconds < 300) {
        agentcoreTimerSpan.className = 'badge bg-warning me-2 py-2 px-3 fs-6';
    } else {
        agentcoreTimerSpan.className = 'badge bg-secondary me-2 py-2 px-3 fs-6';
    }
}

// Add log entry for Agentcore
function addAgentcoreLog(message, type = 'info', timestamp = null) {
    const agentcoreLogsContainer = document.getElementById('agentcore-logs');
    if (!agentcoreLogsContainer) return;

    const logEntry = document.createElement('div');
    logEntry.className = `log-entry log-${type}`;

    let timeStr;
    if (timestamp) {
        // If timestamp is provided, try to parse it and convert to consistent format
        if (typeof timestamp === 'string' && timestamp.includes(':')) {
            // Server-sent timestamp in 24-hour format (e.g., "09:34:00")
            // Convert to 12-hour format with AM/PM
            const timeParts = timestamp.split(':');
            if (timeParts.length >= 2) {
                const hours = parseInt(timeParts[0]);
                const minutes = timeParts[1];
                const seconds = timeParts[2] || '00';

                const period = hours >= 12 ? 'PM' : 'AM';
                const displayHours = hours === 0 ? 12 : (hours > 12 ? hours - 12 : hours);

                timeStr = `${displayHours}:${minutes}:${seconds} ${period}`;
            } else {
                // Fallback to current time if parsing fails
                timeStr = new Date().toLocaleTimeString();
            }
        } else {
            // Try to parse as Date
            const date = new Date(timestamp);
            if (isNaN(date.getTime())) {
                // Invalid date, use current time in GMT+8
                timeStr = getGMT8TimeString();
            } else {
                // Convert to GMT+8 timezone
                timeStr = date.toLocaleTimeString('en-US', {
                    timeZone: 'Asia/Singapore',
                    hour12: true,
                    hour: 'numeric',
                    minute: '2-digit',
                    second: '2-digit'
                });
            }
        }
    } else {
        // No timestamp provided, use current time in GMT+8
        timeStr = getGMT8TimeString();
    }

    logEntry.innerHTML = `<span class="log-time">[${timeStr}]</span> <span class="log-message">${message}</span>`;

    agentcoreLogsContainer.appendChild(logEntry);
    agentcoreLogsContainer.scrollTop = agentcoreLogsContainer.scrollHeight;
}

// Clear Agentcore logs
function clearAgentcoreLogs() {
    const agentcoreLogsContainer = document.getElementById('agentcore-logs');
    if (agentcoreLogsContainer) {
        agentcoreLogsContainer.innerHTML = '';
    }
}

// Open Agentcore browser in fullscreen mode
function openAgentcoreFullscreen() {
    const agentcoreBrowserFrame = document.getElementById('agentcore-browser-frame');
    const agentcoreFullscreenContainer = document.getElementById('agentcore-fullscreen-container');
    const agentcoreBrowserContainer = document.getElementById('agentcore-browser-container');
    const agentcoreFullscreenModal = new bootstrap.Modal(document.getElementById('agentcoreFullscreenModal'));

    if (!agentcoreBrowserFrame || agentcoreBrowserFrame.style.display === 'none') {
        addAgentcoreLog('No active browser session to display in fullscreen.', 'warning');
        console.log('Fullscreen debug: Browser frame not found or hidden', {
            frameExists: !!agentcoreBrowserFrame,
            frameDisplay: agentcoreBrowserFrame ? agentcoreBrowserFrame.style.display : 'N/A',
            frameSrc: agentcoreBrowserFrame ? agentcoreBrowserFrame.src : 'N/A'
        });
        return;
    }

    console.log('Fullscreen debug: Opening fullscreen', {
        frameExists: !!agentcoreBrowserFrame,
        containerExists: !!agentcoreFullscreenContainer,
        frameSrc: agentcoreBrowserFrame.src,
        frameDisplay: agentcoreBrowserFrame.style.display
    });

    try {
        // Store the original parent and styles for restoration later
        agentcoreBrowserFrame.setAttribute('data-original-parent', 'agentcore-browser-container');
        agentcoreBrowserFrame.setAttribute('data-original-style', agentcoreBrowserFrame.style.cssText);

        // Move the existing iframe to fullscreen container with fullscreen styles
        agentcoreBrowserFrame.style.cssText = 'width: 100% !important; height: 100% !important; border: none !important; border-radius: 0 !important; display: block !important;';

        // Clear the fullscreen container and move the iframe there
        agentcoreFullscreenContainer.innerHTML = '';
        agentcoreFullscreenContainer.appendChild(agentcoreBrowserFrame);

        console.log('Fullscreen debug: Successfully moved iframe to fullscreen container');
    } catch (error) {
        console.error('Fullscreen debug: Error moving iframe, trying fallback approach', error);

        // Fallback: Create a new iframe with the same source
        const fallbackFrame = document.createElement('iframe');
        fallbackFrame.id = 'agentcore-browser-frame-fullscreen';
        fallbackFrame.src = agentcoreBrowserFrame.src;
        fallbackFrame.style.cssText = 'width: 100% !important; height: 100% !important; border: none !important; border-radius: 0 !important; display: block !important;';

        agentcoreFullscreenContainer.innerHTML = '';
        agentcoreFullscreenContainer.appendChild(fallbackFrame);

        // Mark as fallback mode
        agentcoreBrowserFrame.setAttribute('data-fullscreen-fallback', 'true');

        addAgentcoreLog('Using fallback method for fullscreen display.', 'info');
    }

    // Show the fullscreen modal
    agentcoreFullscreenModal.show();

    // Add event listener for when modal is hidden
    document.getElementById('agentcoreFullscreenModal').addEventListener('hidden.bs.modal', function() {
        closeAgentcoreFullscreen();
    }, { once: true });

    // Add keyboard shortcut for ESC key
    const handleEscKey = function(event) {
        if (event.key === 'Escape') {
            const modal = bootstrap.Modal.getInstance(document.getElementById('agentcoreFullscreenModal'));
            if (modal) {
                modal.hide();
            }
        }
    };
    document.addEventListener('keydown', handleEscKey);

    // Remove ESC listener when modal is hidden
    document.getElementById('agentcoreFullscreenModal').addEventListener('hidden.bs.modal', function() {
        document.removeEventListener('keydown', handleEscKey);
    }, { once: true });

    addAgentcoreLog('Browser opened in fullscreen mode. Press ESC to exit.', 'info');
}

// Close Agentcore browser fullscreen mode
function closeAgentcoreFullscreen() {
    const agentcoreFullscreenContainer = document.getElementById('agentcore-fullscreen-container');
    const agentcoreBrowserFrame = document.getElementById('agentcore-browser-frame');
    const agentcoreBrowserContainer = document.getElementById('agentcore-browser-container');

    try {
        // Check if we used fallback mode
        const isFallbackMode = agentcoreBrowserFrame && agentcoreBrowserFrame.getAttribute('data-fullscreen-fallback') === 'true';

        if (isFallbackMode) {
            // In fallback mode, just clear the fullscreen container
            // The original iframe should still be in its original location
            console.log('Fullscreen debug: Closing fallback mode');
            agentcoreBrowserFrame.removeAttribute('data-fullscreen-fallback');
        } else {
            // Normal mode: restore the iframe to its original location and styles
            if (agentcoreBrowserFrame && agentcoreBrowserContainer) {
                console.log('Fullscreen debug: Restoring iframe to original container');

                // Restore original styles
                const originalStyle = agentcoreBrowserFrame.getAttribute('data-original-style');
                if (originalStyle) {
                    agentcoreBrowserFrame.style.cssText = originalStyle;
                    agentcoreBrowserFrame.removeAttribute('data-original-style');
                } else {
                    // Fallback to default styles
                    agentcoreBrowserFrame.style.cssText = 'width: 100%; height: 100%; border: none; border-radius: 8px; display: block;';
                }

                // Move iframe back to original container
                agentcoreBrowserContainer.appendChild(agentcoreBrowserFrame);
                agentcoreBrowserFrame.removeAttribute('data-original-parent');
            }
        }
    } catch (error) {
        console.error('Fullscreen debug: Error during close operation', error);
        addAgentcoreLog('Error closing fullscreen mode, but continuing...', 'warning');
    }

    // Clear the fullscreen container
    if (agentcoreFullscreenContainer) {
        agentcoreFullscreenContainer.innerHTML = '';
    }

    addAgentcoreLog('Exited fullscreen mode.', 'info');
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Check if we're on a page with agentcore elements
    if (document.getElementById('agentcore-browser') || document.getElementById('agentcore-task-input')) {
        initAgentcoreBrowserTool();
    }
});
