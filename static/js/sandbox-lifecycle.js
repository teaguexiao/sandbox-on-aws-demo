/**
 * Sandbox Lifecycle UI JavaScript
 * Handles the split-view layout and sandbox lifecycle management
 */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize syntax highlighting
    document.querySelectorAll('pre code').forEach((block) => {
        hljs.highlightElement(block);
    });
    
    // Tab switching functionality
    const tabs = document.querySelectorAll('.sdk-tab');
    const tabContents = {
        'create': document.getElementById('create-tab-content'),
        'use': document.getElementById('use-tab-content'),
        'manage': document.getElementById('manage-tab-content')
    };
    
    tabs.forEach(tab => {
        tab.addEventListener('click', function() {
            const tabName = this.getAttribute('data-tab');
            
            // Update active tab
            tabs.forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            
            // Show selected tab content, hide others
            Object.keys(tabContents).forEach(key => {
                tabContents[key].style.display = key === tabName ? 'block' : 'none';
            });
        });
    });
    
    // Copy button functionality
    document.querySelectorAll('.copy-btn').forEach(button => {
        button.addEventListener('click', function() {
            const code = this.getAttribute('data-code');
            navigator.clipboard.writeText(code).then(() => {
                // Change button text temporarily
                const originalText = this.textContent;
                this.textContent = 'Copied!';
                setTimeout(() => {
                    this.textContent = originalText;
                }, 2000);
            });
        });
    });
    
    // Sandbox state variables
    let sandboxState = {
        id: null,
        status: 'none', // none, creating, active, stopped, destroyed
        creationTime: null,
        uptime: 0,
        uptimeInterval: null
    };
    
    // Update UI based on sandbox state
    function updateSandboxUI() {
        const statusIndicator = document.getElementById('status-indicator');
        const statusText = document.getElementById('sandbox-status-text');
        const sandboxId = document.getElementById('sandbox-id');
        const sandboxUptime = document.getElementById('sandbox-uptime');
        const stopBtn = document.getElementById('stop-btn');
        const resumeBtn = document.getElementById('resume-btn');
        const destroyBtn = document.getElementById('destroy-btn');
        
        // Update status indicator
        statusIndicator.className = 'status-indicator';
        if (sandboxState.status !== 'none') {
            statusIndicator.classList.add(sandboxState.status);
        }
        
        // Update status text
        switch(sandboxState.status) {
            case 'none':
                statusText.textContent = 'No active sandbox';
                break;
            case 'creating':
                statusText.textContent = 'Creating sandbox...';
                break;
            case 'active':
                statusText.textContent = 'Sandbox active';
                break;
            case 'stopped':
                statusText.textContent = 'Sandbox stopped';
                break;
            case 'destroyed':
                statusText.textContent = 'Sandbox destroyed';
                break;
        }
        
        // Update sandbox ID
        if (sandboxState.id) {
            sandboxId.textContent = `ID: ${sandboxState.id}`;
        } else {
            sandboxId.textContent = '';
        }
        
        // Update buttons
        stopBtn.disabled = sandboxState.status !== 'active';
        resumeBtn.disabled = sandboxState.status !== 'stopped';
        destroyBtn.disabled = sandboxState.status === 'none' || sandboxState.status === 'destroyed';
        
        // Update uptime display
        if (sandboxState.status === 'active' && sandboxState.creationTime) {
            if (!sandboxState.uptimeInterval) {
                sandboxState.uptimeInterval = setInterval(updateUptime, 1000);
            }
        } else {
            if (sandboxState.uptimeInterval) {
                clearInterval(sandboxState.uptimeInterval);
                sandboxState.uptimeInterval = null;
            }
            sandboxUptime.textContent = '';
        }
    }
    
    // Update uptime display
    function updateUptime() {
        if (!sandboxState.creationTime) return;
        
        const now = new Date();
        const uptime = Math.floor((now - sandboxState.creationTime) / 1000);
        const hours = Math.floor(uptime / 3600);
        const minutes = Math.floor((uptime % 3600) / 60);
        const seconds = uptime % 60;
        
        const formattedUptime = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        document.getElementById('sandbox-uptime').textContent = `Uptime: ${formattedUptime}`;
    }
    
    // Add execution result to the results panel
    function addExecutionResult(command, result, isError = false) {
        const resultsContainer = document.getElementById('execution-results');
        
        // Clear placeholder if it exists
        if (resultsContainer.querySelector('.text-center.text-muted')) {
            resultsContainer.innerHTML = '';
        }
        
        const resultElement = document.createElement('div');
        resultElement.className = 'execution-result';
        
        const commandElement = document.createElement('div');
        commandElement.className = 'execution-command';
        commandElement.textContent = `> ${command}`;
        resultElement.appendChild(commandElement);
        
        const outputElement = document.createElement('div');
        outputElement.className = isError ? 'execution-output execution-error' : 'execution-output';
        outputElement.textContent = result;
        resultElement.appendChild(outputElement);
        
        resultsContainer.appendChild(resultElement);
        resultsContainer.scrollTop = resultsContainer.scrollHeight;
    }
    
    // Run button functionality
    document.querySelectorAll('.run-btn').forEach(button => {
        button.addEventListener('click', async function() {
            const action = this.getAttribute('data-action');
            const originalText = this.textContent;
            
            // Show loading state
            this.disabled = true;
            this.innerHTML = '<span class="spinner"></span> Running...';
            
            try {
                switch(action) {
                    case 'create_sandbox':
                        await handleCreateSandbox();
                        break;
                    case 'create_custom_sandbox':
                        await handleCreateCustomSandbox();
                        break;
                    case 'run_code':
                        await handleRunCode();
                        break;
                    case 'exec_command':
                        await handleExecCommand();
                        break;
                    case 'file_operations':
                        await handleFileOperations();
                        break;
                    case 'stop_sandbox':
                        await handleStopSandbox();
                        break;
                    case 'resume_sandbox':
                        await handleResumeSandbox();
                        break;
                    case 'destroy_sandbox':
                        await handleDestroySandbox();
                        break;
                }
            } catch (error) {
                addExecutionResult(action, `Error: ${error.message}`, true);
            } finally {
                // Reset button state
                this.disabled = false;
                this.textContent = originalText;
            }
        });
    });
    
    // Action button handlers
    document.getElementById('stop-btn').addEventListener('click', handleStopSandbox);
    document.getElementById('resume-btn').addEventListener('click', handleResumeSandbox);
    document.getElementById('destroy-btn').addEventListener('click', handleDestroySandbox);
    document.getElementById('clear-btn').addEventListener('click', function() {
        document.getElementById('execution-results').innerHTML = `
            <div class="text-center text-muted py-5">
                <p>Select an example from the left panel and click "Run" to see the results here.</p>
            </div>
        `;
    });
    
    // Handler functions for sandbox operations
    async function handleCreateSandbox() {
        // Update sandbox state
        sandboxState.status = 'creating';
        updateSandboxUI();
        
        try {
            // Call API to create sandbox
            const response = await fetch('/api/e2b/reset', {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.success) {
                // Update sandbox state
                sandboxState.id = result.sandbox_id;
                sandboxState.status = 'active';
                sandboxState.creationTime = new Date();
                updateSandboxUI();
                
                // Add result to execution panel
                addExecutionResult(
                    'from e2b import Sandbox\nsandbox = Sandbox()',
                    `Sandbox created successfully\nID: ${result.sandbox_id}\nCreation Time: ${sandboxState.creationTime.toLocaleString()}`
                );
            } else {
                // Handle error
                sandboxState.status = 'none';
                updateSandboxUI();
                addExecutionResult(
                    'from e2b import Sandbox\nsandbox = Sandbox()',
                    `Error: ${result.error}`,
                    true
                );
            }
        } catch (error) {
            // Handle error
            sandboxState.status = 'none';
            updateSandboxUI();
            addExecutionResult(
                'from e2b import Sandbox\nsandbox = Sandbox()',
                `Error: ${error.message}`,
                true
            );
        }
    }
    
    async function handleCreateCustomSandbox() {
        // Update sandbox state
        sandboxState.status = 'creating';
        updateSandboxUI();
        
        try {
            // Call API to create sandbox
            const response = await fetch('/api/e2b/reset', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    template: 'base-python',
                    timeout: 3600
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                // Update sandbox state
                sandboxState.id = result.sandbox_id;
                sandboxState.status = 'active';
                sandboxState.creationTime = new Date();
                updateSandboxUI();
                
                // Add result to execution panel
                addExecutionResult(
                    'from e2b import Sandbox\nsandbox = Sandbox(template="base-python", timeout=3600)',
                    `Sandbox created successfully\nID: ${result.sandbox_id}\nTemplate: base-python\nTimeout: 3600 seconds\nCreation Time: ${sandboxState.creationTime.toLocaleString()}`
                );
            } else {
                // Handle error
                sandboxState.status = 'none';
                updateSandboxUI();
                addExecutionResult(
                    'from e2b import Sandbox\nsandbox = Sandbox(template="base-python", timeout=3600)',
                    `Error: ${result.error}`,
                    true
                );
            }
        } catch (error) {
            // Handle error
            sandboxState.status = 'none';
            updateSandboxUI();
            addExecutionResult(
                'from e2b import Sandbox\nsandbox = Sandbox(template="base-python", timeout=3600)',
                `Error: ${error.message}`,
                true
            );
        }
    }
    
    async function handleRunCode() {
        if (sandboxState.status !== 'active') {
            addExecutionResult(
                'sandbox.process.code_run("print(\\"Hello World!\\")")',
                'Error: No active sandbox. Please create a sandbox first.',
                true
            );
            return;
        }
        
        try {
            // Call API to execute code
            const response = await fetch('/api/e2b/execute', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    code: 'print("Hello World!")'
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                // Add result to execution panel
                addExecutionResult(
                    'sandbox.process.code_run("print(\\"Hello World!\\")")',
                    result.output
                );
            } else {
                // Handle error
                addExecutionResult(
                    'sandbox.process.code_run("print(\\"Hello World!\\")")',
                    `Error: ${result.error}`,
                    true
                );
            }
        } catch (error) {
            // Handle error
            addExecutionResult(
                'sandbox.process.code_run("print(\\"Hello World!\\")")',
                `Error: ${error.message}`,
                true
            );
        }
    }
    
    async function handleExecCommand() {
        if (sandboxState.status !== 'active') {
            addExecutionResult(
                'sandbox.process.exec("echo \'Hello from shell!\'")',
                'Error: No active sandbox. Please create a sandbox first.',
                true
            );
            return;
        }
        
        try {
            // Call API to execute command
            const response = await fetch('/api/e2b/execute', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    code: 'import subprocess\nresult = subprocess.run(["echo", "Hello from shell!"], capture_output=True, text=True)\nprint(result.stdout)'
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                // Add result to execution panel
                addExecutionResult(
                    'sandbox.process.exec("echo \'Hello from shell!\'")',
                    result.output
                );
            } else {
                // Handle error
                addExecutionResult(
                    'sandbox.process.exec("echo \'Hello from shell!\'")',
                    `Error: ${result.error}`,
                    true
                );
            }
        } catch (error) {
            // Handle error
            addExecutionResult(
                'sandbox.process.exec("echo \'Hello from shell!\'")',
                `Error: ${error.message}`,
                true
            );
        }
    }
    
    async function handleFileOperations() {
        if (sandboxState.status !== 'active') {
            addExecutionResult(
                'sandbox.fs.upload_file("/home/user/data.txt", "Hello, World!")',
                'Error: No active sandbox. Please create a sandbox first.',
                true
            );
            return;
        }
        
        try {
            // Call API to execute file operations
            const response = await fetch('/api/e2b/execute', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    code: 'with open("/tmp/data.txt", "w") as f:\n    f.write("Hello, World!")\n\nwith open("/tmp/data.txt", "r") as f:\n    content = f.read()\n    print(f"File content: {content}")'
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                // Add result to execution panel
                addExecutionResult(
                    'sandbox.fs.upload_file("/home/user/data.txt", "Hello, World!")\nresult = sandbox.process.exec("cat /home/user/data.txt")',
                    result.output
                );
            } else {
                // Handle error
                addExecutionResult(
                    'sandbox.fs.upload_file("/home/user/data.txt", "Hello, World!")\nresult = sandbox.process.exec("cat /home/user/data.txt")',
                    `Error: ${result.error}`,
                    true
                );
            }
        } catch (error) {
            // Handle error
            addExecutionResult(
                'sandbox.fs.upload_file("/home/user/data.txt", "Hello, World!")\nresult = sandbox.process.exec("cat /home/user/data.txt")',
                `Error: ${error.message}`,
                true
            );
        }
    }
    
    async function handleStopSandbox() {
        if (sandboxState.status !== 'active') {
            addExecutionResult(
                'sandbox.stop()',
                'Error: No active sandbox to stop.',
                true
            );
            return;
        }
        
        // In a real implementation, we would call an API to stop the sandbox
        // For this demo, we'll simulate it
        
        // Update sandbox state
        sandboxState.status = 'stopped';
        updateSandboxUI();
        
        // Add result to execution panel
        addExecutionResult(
            'sandbox.stop()',
            `Sandbox ${sandboxState.id} stopped successfully.`
        );
    }
    
    async function handleResumeSandbox() {
        if (sandboxState.status !== 'stopped') {
            addExecutionResult(
                'sandbox.resume()',
                'Error: No stopped sandbox to resume.',
                true
            );
            return;
        }
        
        // In a real implementation, we would call an API to resume the sandbox
        // For this demo, we'll simulate it
        
        // Update sandbox state
        sandboxState.status = 'active';
        updateSandboxUI();
        
        // Add result to execution panel
        addExecutionResult(
            'sandbox.resume()',
            `Sandbox ${sandboxState.id} resumed successfully.`
        );
    }
    
    async function handleDestroySandbox() {
        if (sandboxState.status === 'none' || sandboxState.status === 'destroyed') {
            addExecutionResult(
                'sandbox.kill()',
                'Error: No sandbox to destroy.',
                true
            );
            return;
        }
        
        try {
            // Call API to destroy sandbox
            const response = await fetch('/api/e2b/reset', {
                method: 'POST'
            });
            
            const result = await response.json();
            
            // Update sandbox state
            sandboxState.status = 'destroyed';
            updateSandboxUI();
            
            // Add result to execution panel
            addExecutionResult(
                'sandbox.kill()',
                `Sandbox ${sandboxState.id} destroyed successfully.`
            );
            
            // Reset sandbox state after a delay
            setTimeout(() => {
                sandboxState.id = null;
                sandboxState.status = 'none';
                sandboxState.creationTime = null;
                updateSandboxUI();
            }, 3000);
        } catch (error) {
            // Handle error
            addExecutionResult(
                'sandbox.kill()',
                `Error: ${error.message}`,
                true
            );
        }
    }
    
    // Initialize UI
    updateSandboxUI();
});
