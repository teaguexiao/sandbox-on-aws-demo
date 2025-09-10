// Bedrock-AgentCore Browser Viewer Module with Optimized Logging
import dcv from "../dcvjs/dcv.js";
export class BedrockAgentCoreLiveViewer {
    constructor(presignedUrl, containerId = 'dcv-display') {
        this.displayLayoutRequested = false;
        this.presignedUrl = presignedUrl;
        this.containerId = containerId;
        this.connection = null;
        this.desiredWidth = 1280;
        this.desiredHeight = 720;
        this.debugMode = false; // Set to true for verbose logging

        if (this.debugMode) {
            console.log('[BedrockAgentCoreLiveViewer] Initialized with URL:', presignedUrl);
        }
    }

    log(message, level = 'info') {
        if (this.debugMode || level === 'error' || level === 'warn') {
            console[level]('[BedrockAgentCoreLiveViewer]', message);
        }
    }

    httpExtraSearchParamsCallBack(method, url, body, returnType) {
        this.log(`httpExtraSearchParamsCallBack called: ${method} ${url}`, 'debug');
        const parsedUrl = new URL(this.presignedUrl);
        const params = parsedUrl.searchParams;
        this.log(`Returning auth params: ${params.toString()}`, 'debug');
        return params;
    }
    
    displayLayoutCallback(serverWidth, serverHeight, heads) {
        this.log(`Display layout callback: ${serverWidth}x${serverHeight}`, 'debug');

        const display = document.getElementById(this.containerId);
        display.style.width = `${this.desiredWidth}px`;
        display.style.height = `${this.desiredHeight}px`;

        if (this.connection) {
            this.log(`Requesting display layout: ${this.desiredWidth}x${this.desiredHeight}`, 'debug');
            // Only request display layout once
            if (!this.displayLayoutRequested) {
                this.connection.requestDisplayLayout([{
                name: "Main Display",
                rect: {
                    x: 0,
                    y: 0,
                    width: this.desiredWidth,
                    height: this.desiredHeight
                },
                primary: true
                }]);

                this.displayLayoutRequested = true;
                this.log(`Display layout requested: ${this.desiredWidth}x${this.desiredHeight}`, 'info');
            }
        }
    }

    async connect() {
        return new Promise((resolve, reject) => {
            if (typeof dcv === 'undefined') {
                reject(new Error('DCV SDK not loaded'));
                return;
            }

            this.log(`DCV SDK loaded, version: ${dcv.version || 'Unknown'}`, 'info');
            this.log(`Available DCV methods: ${Object.keys(dcv).join(', ')}`, 'debug');
            this.log(`Presigned URL: ${this.presignedUrl.substring(0, 50)}...`, 'debug');

            // Set appropriate logging level for DCV
            if (dcv.setLogLevel) {
                // Use INFO level instead of DEBUG to reduce DCV internal logging
                dcv.setLogLevel(this.debugMode ? dcv.LogLevel.DEBUG : dcv.LogLevel.INFO);
                this.log(`DCV log level set to ${this.debugMode ? 'DEBUG' : 'INFO'}`, 'debug');
            }

            this.log('Starting authentication...', 'info');
            
            dcv.authenticate(this.presignedUrl, {
                promptCredentials: () => {
                    this.log('DCV requested credentials - should not happen with presigned URL', 'warn');
                },
                error: (auth, error) => {
                    this.log(`DCV auth error: ${error.message || error}`, 'error');
                    if (this.debugMode) {
                        this.log(`Error details: ${JSON.stringify({
                            message: error.message || error,
                            code: error.code,
                            statusCode: error.statusCode
                        })}`, 'error');
                    }
                    reject(error);
                },
                success: (auth, result) => {
                    this.log('DCV auth success', 'info');
                    if (result && result[0]) {
                        const { sessionId, authToken } = result[0];
                        this.log(`Session ID: ${sessionId}`, 'debug');
                        this.log(`Auth token received: ${authToken ? 'Yes' : 'No'}`, 'debug');
                        this.connectToSession(sessionId, authToken, resolve, reject);
                    } else {
                        this.log('No session data in auth result', 'error');
                        reject(new Error('No session data in auth result'));
                    }
                },
                httpExtraSearchParams: this.httpExtraSearchParamsCallBack.bind(this)
            });
        });
    }

    connectToSession(sessionId, authToken, resolve, reject) {
        this.log(`Connecting to session: ${sessionId}`, 'info');

        const connectOptions = {
            url: this.presignedUrl,
            sessionId: sessionId,
            authToken: authToken,
            divId: this.containerId,
            baseUrl: "/static/dcvjs",
            callbacks: {
                firstFrame: () => {
                    this.log('First frame received - connection ready!', 'info');
                    resolve(this.connection);
                },
                error: (error) => {
                    this.log(`Connection error: ${error.message || error}`, 'error');
                    reject(error);
                },
                httpExtraSearchParams: this.httpExtraSearchParamsCallBack.bind(this),
                displayLayout: this.displayLayoutCallback.bind(this)
            }
        };

        this.log('Establishing DCV connection...', 'debug');

        dcv.connect(connectOptions)
        .then(connection => {
            this.log('Connection established successfully', 'info');
            this.connection = connection;
        })
        .catch(error => {
            this.log(`Connect failed: ${error.message || error}`, 'error');
            reject(error);
        });
    }

    setDisplaySize(width, height) {
        this.desiredWidth = width;
        this.desiredHeight = height;
        
        if (this.connection) {
            this.displayLayoutCallback(0, 0, []);
        }
    }

    disconnect() {
        if (this.connection) {
            this.connection.disconnect();
            this.connection = null;
        }
    }
}