/**
 * Helen WiFi - WebRTC Connection Engine
 *
 * Robust client-side WebRTC with:
 * - ICE restart on failure/network change
 * - Transport probing (UDP -> TCP -> TLS/443)
 * - Fallback policy (SFU first, then TURN transports)
 * - Connection quality monitoring
 * - ACK/Retry for signaling messages
 * - Heartbeat for session liveness
 * - Call state tracking
 * - Diagnostics reporting
 */

// ═══════════════════════════════════════════════════════════════════════════
// Signaling Reliability Layer
// ═══════════════════════════════════════════════════════════════════════════

class ReliableSignaling {
    constructor(socket) {
        this.socket = socket;
        this._pendingAcks = new Map();  // msg_id -> {resolve, timer, retries}
        this._seenMessages = new Set();
        this._seqCounters = new Map();  // target -> seq
        this._heartbeatTimer = null;
        this._heartbeatInterval = 10000;  // 10 seconds
        this._maxRetries = 3;
        this._retryDelays = [500, 1000, 2000];

        // Listen for ACK confirmations from server
        this.socket.on('signal_ack_confirm', (data) => {
            // Server confirms our ACK was received
        });

        this._setupAutoAck();
    }

    /**
     * Send signaling message with ACK/Retry guarantee.
     */
    emit(event, data, options = {}) {
        const msgId = this._generateId();
        const target = data.target || data.targetSid || '';
        const key = `${this.socket.id}-${target}`;

        if (!this._seqCounters.has(key)) this._seqCounters.set(key, 0);
        const seq = this._seqCounters.get(key) + 1;
        this._seqCounters.set(key, seq);

        const envelope = {
            ...data,
            _msg_id: msgId,
            _seq: seq,
            _ts: Date.now() / 1000,
        };

        this.socket.emit(event, envelope);

        if (options.requireAck !== false) {
            return this._waitForAck(event, envelope, msgId);
        }
        return Promise.resolve(msgId);
    }

    /**
     * Check if message is duplicate (already processed).
     */
    isDuplicate(msgId) {
        if (this._seenMessages.has(msgId)) return true;
        this._seenMessages.add(msgId);
        // Clean old entries
        if (this._seenMessages.size > 1000) {
            const arr = Array.from(this._seenMessages);
            this._seenMessages = new Set(arr.slice(-500));
        }
        return false;
    }

    /**
     * Start heartbeat to keep session alive.
     */
    startHeartbeat(username) {
        this.stopHeartbeat();
        this._heartbeatTimer = setInterval(() => {
            this.socket.emit('heartbeat', { username });
        }, this._heartbeatInterval);
    }

    stopHeartbeat() {
        if (this._heartbeatTimer) {
            clearInterval(this._heartbeatTimer);
            this._heartbeatTimer = null;
        }
    }

    _setupAutoAck() {
        // Auto-ACK received signaling messages
        const ackEvents = [
            'webrtc_offer', 'webrtc_answer', 'webrtc_ice',
            'incoming_call', 'call_accepted', 'call_rejected', 'call_ended',
            'screen_offer', 'screen_answer', 'screen_ice',
            'group_call_offer', 'group_call_answer', 'group_call_ice',
            'sfu_offer', 'sfu_answer', 'sfu_ice',
        ];
        ackEvents.forEach(event => {
            this.socket.on(event, (data) => {
                if (data && data._msg_id) {
                    this.socket.emit('signal_ack', { msg_id: data._msg_id });
                }
            });
        });
    }

    _waitForAck(event, data, msgId) {
        return new Promise((resolve) => {
            let retries = 0;
            const retry = () => {
                if (retries >= this._maxRetries) {
                    this._pendingAcks.delete(msgId);
                    resolve(msgId); // Give up but don't reject
                    return;
                }
                const delay = this._retryDelays[Math.min(retries, this._retryDelays.length - 1)];
                const timer = setTimeout(() => {
                    retries++;
                    this.socket.emit(event, data);
                    retry();
                }, delay);
                this._pendingAcks.set(msgId, { resolve, timer, retries });
            };

            // Listen for this specific ACK
            const handler = (ackData) => {
                if (ackData && ackData.msg_id === msgId) {
                    const pending = this._pendingAcks.get(msgId);
                    if (pending) {
                        clearTimeout(pending.timer);
                        this._pendingAcks.delete(msgId);
                    }
                    this.socket.off('signal_ack', handler);
                    resolve(msgId);
                }
            };
            this.socket.on('signal_ack', handler);

            // Start retry chain after initial ACK timeout
            const initialTimer = setTimeout(() => retry(), this._retryDelays[0]);
            this._pendingAcks.set(msgId, { resolve, timer: initialTimer, retries: 0 });
        });
    }

    _generateId() {
        return Math.random().toString(36).substr(2, 10);
    }
}


// ═══════════════════════════════════════════════════════════════════════════
// Transport Prober - Test which TURN transports work
// ═══════════════════════════════════════════════════════════════════════════

class TransportProber {
    constructor() {
        this._results = {};  // {url: {reachable, latency_ms, transport}}
    }

    /**
     * Probe TURN server reachability across all transports.
     * Tests: STUN -> TURN/UDP -> TURN/TCP -> TURNS/TLS
     * Returns sorted list (fastest first).
     */
    async probeAll(iceServers) {
        const probes = [];
        for (const server of iceServers) {
            const urls = Array.isArray(server.urls) ? server.urls : [server.urls];
            for (const url of urls) {
                probes.push(this._probeServer(url, server.username, server.credential));
            }
        }
        const results = await Promise.allSettled(probes);
        const reachable = results
            .filter(r => r.status === 'fulfilled' && r.value.reachable)
            .map(r => r.value)
            .sort((a, b) => a.latency - b.latency);

        return reachable;
    }

    /**
     * Probe a single TURN server URL.
     */
    async _probeServer(url, username, credential) {
        const start = performance.now();
        const transport = this._getTransport(url);

        try {
            // Create a minimal PeerConnection to test connectivity
            const config = {
                iceServers: [{
                    urls: url,
                    username: username,
                    credential: credential,
                }],
                iceTransportPolicy: url.startsWith('stun:') ? 'all' : 'relay',
            };

            const pc = new RTCPeerConnection(config);
            pc.addTransceiver('audio', { direction: 'sendonly' });

            const result = await new Promise((resolve) => {
                let gathered = false;
                const timeout = setTimeout(() => {
                    if (!gathered) resolve({ reachable: false, url, transport, latency: Infinity });
                    pc.close();
                }, 5000);

                pc.onicecandidate = (e) => {
                    if (e.candidate) {
                        const candidateType = e.candidate.type || '';
                        const isRelay = e.candidate.candidate.includes('relay');
                        const isServerReflexive = e.candidate.candidate.includes('srflx');

                        if (url.startsWith('stun:') && (isServerReflexive || candidateType === 'srflx')) {
                            gathered = true;
                            clearTimeout(timeout);
                            resolve({
                                reachable: true,
                                url,
                                transport: 'STUN',
                                latency: performance.now() - start,
                            });
                            pc.close();
                        } else if (!url.startsWith('stun:') && (isRelay || candidateType === 'relay')) {
                            gathered = true;
                            clearTimeout(timeout);
                            resolve({
                                reachable: true,
                                url,
                                transport,
                                latency: performance.now() - start,
                            });
                            pc.close();
                        }
                    }
                };

                pc.onicegatheringstatechange = () => {
                    if (pc.iceGatheringState === 'complete' && !gathered) {
                        clearTimeout(timeout);
                        resolve({ reachable: false, url, transport, latency: Infinity });
                        pc.close();
                    }
                };

                pc.createOffer().then(offer => pc.setLocalDescription(offer)).catch(() => {
                    clearTimeout(timeout);
                    resolve({ reachable: false, url, transport, latency: Infinity });
                    pc.close();
                });
            });

            return result;
        } catch (e) {
            return { reachable: false, url, transport, latency: Infinity };
        }
    }

    _getTransport(url) {
        if (url.startsWith('stun:')) return 'STUN';
        if (url.includes('transport=tcp') && url.startsWith('turns:')) return 'TLS';
        if (url.includes('transport=tcp')) return 'TCP';
        if (url.includes(':443')) return 'TLS/443';
        return 'UDP';
    }
}


// ═══════════════════════════════════════════════════════════════════════════
// WebRTC Connection Engine
// ═══════════════════════════════════════════════════════════════════════════

class WebRTCEngine {
    /**
     * @param {Object} socket - Socket.IO instance
     * @param {Object} options - Configuration
     */
    constructor(socket, options = {}) {
        this.socket = socket;
        this.signaling = new ReliableSignaling(socket);
        this.prober = new TransportProber();

        // Configuration
        this.iceServers = options.iceServers || [];
        this.preferSFU = options.preferSFU !== false;  // Default: prefer SFU
        this.forceRelay = options.forceRelay || false;
        this.enableDiagnostics = options.enableDiagnostics !== false;

        // State
        this.peerConnections = new Map();  // {target_sid: RTCPeerConnection}
        this.localStream = null;
        this.remoteStreams = new Map();     // {target_sid: MediaStream}
        this.currentCallId = null;
        this.callState = 'idle';
        this._iceQueues = new Map();       // {target_sid: [candidates]}
        this._networkChangeHandler = null;
        this._statsTimers = new Map();

        // Diagnostics
        this._diagnostics = {
            ice_states: [],
            connection_type: null,
            transport: null,
            candidates_gathered: 0,
            ice_restarts: 0,
            fallback_used: null,
        };

        // Callbacks
        this.onRemoteStream = null;        // (sid, stream) => {}
        this.onCallStateChanged = null;    // (callId, state) => {}
        this.onConnectionQuality = null;   // (sid, quality) => {}
        this.onDiagnostics = null;         // (diagnostics) => {}

        this._setupNetworkChangeDetection();
        this._setupSocketHandlers();
    }

    // ═════════════════════════════════════════════════════════════════════
    // Public API
    // ═════════════════════════════════════════════════════════════════════

    /**
     * Get local media stream.
     */
    async getLocalStream(constraints) {
        const defaultConstraints = {
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            },
            video: false,
        };
        this.localStream = await navigator.mediaDevices.getUserMedia(
            constraints || defaultConstraints
        );
        return this.localStream;
    }

    /**
     * Create a peer connection to a target with full fallback policy.
     */
    async createConnection(targetSid, isInitiator, options = {}) {
        // Determine best ICE configuration
        const iceConfig = await this._buildICEConfig(options);

        const pc = new RTCPeerConnection(iceConfig);
        this.peerConnections.set(targetSid, pc);
        this._iceQueues.set(targetSid, []);

        this._setupPeerConnection(pc, targetSid);

        // Add local tracks
        if (this.localStream) {
            this.localStream.getTracks().forEach(track => {
                pc.addTrack(track, this.localStream);
            });
        }

        if (isInitiator) {
            const offer = await pc.createOffer({
                offerToReceiveAudio: true,
                offerToReceiveVideo: options.video || false,
            });
            await pc.setLocalDescription(offer);

            this.signaling.emit('webrtc_offer', {
                sdp: offer.sdp,
                type: offer.type,
                target: targetSid,
                call_id: this.currentCallId,
            });
        }

        // Start connection quality monitoring
        if (this.enableDiagnostics) {
            this._startStatsMonitoring(targetSid, pc);
        }

        return pc;
    }

    /**
     * Handle incoming offer.
     */
    async handleOffer(data) {
        const senderSid = data.sender;
        const iceConfig = await this._buildICEConfig();

        const pc = new RTCPeerConnection(iceConfig);
        this.peerConnections.set(senderSid, pc);
        this._iceQueues.set(senderSid, []);

        this._setupPeerConnection(pc, senderSid);

        if (this.localStream) {
            this.localStream.getTracks().forEach(track => {
                pc.addTrack(track, this.localStream);
            });
        }

        await pc.setRemoteDescription(new RTCSessionDescription({
            sdp: data.sdp,
            type: data.type,
        }));

        // Process queued ICE candidates
        const queue = this._iceQueues.get(senderSid) || [];
        for (const candidate of queue) {
            try {
                await pc.addIceCandidate(new RTCIceCandidate(candidate));
            } catch (e) { /* ignore */ }
        }
        this._iceQueues.set(senderSid, []);

        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);

        this.signaling.emit('webrtc_answer', {
            sdp: answer.sdp,
            type: answer.type,
            target: senderSid,
            call_id: this.currentCallId,
        });

        if (this.enableDiagnostics) {
            this._startStatsMonitoring(senderSid, pc);
        }
    }

    /**
     * Handle incoming ICE candidate.
     */
    async handleIceCandidate(data) {
        const senderSid = data.sender;
        const pc = this.peerConnections.get(senderSid);

        if (!pc || !pc.remoteDescription) {
            // Queue candidate
            const queue = this._iceQueues.get(senderSid) || [];
            queue.push(data.candidate);
            this._iceQueues.set(senderSid, queue);
            return;
        }

        try {
            await pc.addIceCandidate(new RTCIceCandidate(data.candidate));
        } catch (e) {
            console.warn('ICE candidate error:', e);
        }
    }

    /**
     * Handle incoming answer.
     */
    async handleAnswer(data) {
        const senderSid = data.sender;
        const pc = this.peerConnections.get(senderSid);
        if (!pc) return;

        await pc.setRemoteDescription(new RTCSessionDescription({
            sdp: data.sdp,
            type: data.type,
        }));

        // Process queued ICE candidates
        const queue = this._iceQueues.get(senderSid) || [];
        for (const candidate of queue) {
            try {
                await pc.addIceCandidate(new RTCIceCandidate(candidate));
            } catch (e) { /* ignore */ }
        }
        this._iceQueues.set(senderSid, []);
    }

    /**
     * Perform ICE restart for a connection.
     */
    async iceRestart(targetSid) {
        const pc = this.peerConnections.get(targetSid);
        if (!pc) return;

        this._diagnostics.ice_restarts++;

        // Request ICE restart from server
        this.socket.emit('ice_restart_request', {
            call_id: this.currentCallId,
            target: targetSid,
        });

        // Create new offer with ICE restart flag
        const offer = await pc.createOffer({ iceRestart: true });
        await pc.setLocalDescription(offer);

        this.signaling.emit('webrtc_offer', {
            sdp: offer.sdp,
            type: offer.type,
            target: targetSid,
            call_id: this.currentCallId,
            ice_restart: true,
        });

        console.log(`ICE restart initiated for ${targetSid}`);
    }

    /**
     * Close a specific peer connection.
     */
    closeConnection(targetSid) {
        const pc = this.peerConnections.get(targetSid);
        if (pc) {
            pc.close();
            this.peerConnections.delete(targetSid);
        }
        this._iceQueues.delete(targetSid);
        this.remoteStreams.delete(targetSid);

        const timer = this._statsTimers.get(targetSid);
        if (timer) {
            clearInterval(timer);
            this._statsTimers.delete(targetSid);
        }
    }

    /**
     * Close all connections and cleanup.
     */
    closeAll() {
        for (const [sid] of this.peerConnections) {
            this.closeConnection(sid);
        }
        if (this.localStream) {
            this.localStream.getTracks().forEach(t => t.stop());
            this.localStream = null;
        }
        this.signaling.stopHeartbeat();
    }

    /**
     * Get current diagnostics.
     */
    getDiagnostics() {
        return { ...this._diagnostics };
    }

    // ═════════════════════════════════════════════════════════════════════
    // ICE Configuration with Fallback
    // ═════════════════════════════════════════════════════════════════════

    async _buildICEConfig(options = {}) {
        const config = {
            iceServers: [...this.iceServers],
            iceCandidatePoolSize: 5,
        };

        // Force relay mode for SFU or if configured
        if (this.forceRelay || options.forceRelay) {
            config.iceTransportPolicy = 'relay';
        }

        // Probe available transports if we have TURN servers
        if (this.iceServers.some(s => {
            const urls = Array.isArray(s.urls) ? s.urls : [s.urls];
            return urls.some(u => u.startsWith('turn'));
        })) {
            try {
                const probeResults = await this.prober.probeAll(this.iceServers);
                if (probeResults.length > 0) {
                    // Use only reachable servers, sorted by latency
                    const reachableUrls = new Set(probeResults.map(r => r.url));
                    config.iceServers = this.iceServers.filter(s => {
                        const urls = Array.isArray(s.urls) ? s.urls : [s.urls];
                        return urls.some(u => reachableUrls.has(u) || u.startsWith('stun:'));
                    });
                    this._diagnostics.fallback_used = probeResults[0].transport;
                }
            } catch (e) {
                console.warn('Transport probing failed, using all servers:', e);
            }
        }

        return config;
    }

    // ═════════════════════════════════════════════════════════════════════
    // Peer Connection Setup
    // ═════════════════════════════════════════════════════════════════════

    _setupPeerConnection(pc, targetSid) {
        // ICE candidate handling (Trickle ICE)
        pc.onicecandidate = (event) => {
            if (event.candidate) {
                this._diagnostics.candidates_gathered++;
                this.signaling.emit('webrtc_ice', {
                    candidate: event.candidate,
                    target: targetSid,
                    call_id: this.currentCallId,
                });
            }
        };

        // Remote track received
        pc.ontrack = (event) => {
            const stream = event.streams[0];
            if (stream) {
                this.remoteStreams.set(targetSid, stream);
                if (this.onRemoteStream) {
                    this.onRemoteStream(targetSid, stream);
                }
            }
        };

        // ICE connection state changes
        pc.oniceconnectionstatechange = () => {
            const state = pc.iceConnectionState;
            this._diagnostics.ice_states.push({
                state, timestamp: Date.now(), target: targetSid
            });

            console.log(`ICE state [${targetSid.substring(0,6)}]: ${state}`);

            // Report to server for diagnostics
            this.socket.emit('ice_state_report', {
                call_id: this.currentCallId,
                state,
                target: targetSid,
            });

            switch (state) {
                case 'connected':
                case 'completed':
                    this._onConnected(pc, targetSid);
                    break;

                case 'disconnected':
                    // Wait briefly then try ICE restart
                    setTimeout(() => {
                        if (pc.iceConnectionState === 'disconnected') {
                            console.log(`Connection still disconnected, attempting ICE restart`);
                            this.iceRestart(targetSid);
                        }
                    }, 3000);
                    break;

                case 'failed':
                    this._onFailed(pc, targetSid);
                    break;

                case 'closed':
                    this.closeConnection(targetSid);
                    break;
            }
        };

        // Connection state (more reliable than ICE state)
        pc.onconnectionstatechange = () => {
            const state = pc.connectionState;
            if (state === 'failed') {
                this._onFailed(pc, targetSid);
            }
        };
    }

    async _onConnected(pc, targetSid) {
        // Detect connection type
        try {
            const stats = await pc.getStats();
            stats.forEach(report => {
                if (report.type === 'candidate-pair' && report.state === 'succeeded') {
                    const localCandidate = stats.get(report.localCandidateId);
                    const remoteCandidate = stats.get(report.remoteCandidateId);

                    if (localCandidate) {
                        this._diagnostics.connection_type = localCandidate.candidateType;
                        this._diagnostics.transport = localCandidate.protocol;

                        this.socket.emit('ice_state_report', {
                            call_id: this.currentCallId,
                            state: 'connected',
                            connection_type: localCandidate.candidateType,
                            transport: localCandidate.protocol,
                        });
                    }
                }
            });
        } catch (e) { /* stats not critical */ }

        if (this.onDiagnostics) {
            this.onDiagnostics(this._diagnostics);
        }
    }

    async _onFailed(pc, targetSid) {
        console.warn(`Connection failed for ${targetSid}, attempting fallback`);

        // Strategy: Try ICE restart first, then recreate with relay-only
        if (this._diagnostics.ice_restarts < 2) {
            await this.iceRestart(targetSid);
        } else {
            // Fallback: Force relay mode
            console.log('Forcing relay mode after multiple ICE failures');
            this.closeConnection(targetSid);
            await this.createConnection(targetSid, true, { forceRelay: true });
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    // Network Change Detection
    // ═════════════════════════════════════════════════════════════════════

    _setupNetworkChangeDetection() {
        if (typeof window === 'undefined') return;

        this._networkChangeHandler = () => {
            console.log('Network change detected, restarting ICE for all connections');
            for (const [sid, pc] of this.peerConnections) {
                if (pc.iceConnectionState !== 'closed') {
                    this.iceRestart(sid);
                }
            }
        };

        // Listen for network changes
        if (navigator.connection) {
            navigator.connection.addEventListener('change', this._networkChangeHandler);
        }
        window.addEventListener('online', this._networkChangeHandler);
    }

    // ═════════════════════════════════════════════════════════════════════
    // Connection Quality Monitoring
    // ═════════════════════════════════════════════════════════════════════

    _startStatsMonitoring(targetSid, pc) {
        const timer = setInterval(async () => {
            if (pc.connectionState === 'closed') {
                clearInterval(timer);
                return;
            }
            try {
                const stats = await pc.getStats();
                const quality = this._analyzeStats(stats);
                if (this.onConnectionQuality) {
                    this.onConnectionQuality(targetSid, quality);
                }
            } catch (e) { /* ignore */ }
        }, 5000);

        this._statsTimers.set(targetSid, timer);
    }

    _analyzeStats(stats) {
        const quality = {
            rtt: null,
            packetsLost: 0,
            jitter: null,
            bitrate: null,
            candidateType: null,
        };

        stats.forEach(report => {
            if (report.type === 'candidate-pair' && report.state === 'succeeded') {
                quality.rtt = report.currentRoundTripTime ? report.currentRoundTripTime * 1000 : null;
            }
            if (report.type === 'inbound-rtp' && report.kind === 'audio') {
                quality.packetsLost = report.packetsLost || 0;
                quality.jitter = report.jitter ? report.jitter * 1000 : null;
            }
        });

        return quality;
    }

    // ═════════════════════════════════════════════════════════════════════
    // Socket Handlers
    // ═════════════════════════════════════════════════════════════════════

    _setupSocketHandlers() {
        // Handle ICE restart request from server/remote
        this.socket.on('ice_restart', async (data) => {
            if (data.sender) {
                const pc = this.peerConnections.get(data.sender);
                if (pc) {
                    console.log(`ICE restart requested by ${data.sender}`);
                    // Will be handled when we receive the new offer
                }
            }
        });

        // Handle call state changes from server
        this.socket.on('call_state_changed', (data) => {
            this.callState = data.state;
            if (this.onCallStateChanged) {
                this.onCallStateChanged(data.call_id, data.state);
            }
        });
    }
}


// ═══════════════════════════════════════════════════════════════════════════
// Export for use in client.html
// ═══════════════════════════════════════════════════════════════════════════

if (typeof window !== 'undefined') {
    window.WebRTCEngine = WebRTCEngine;
    window.ReliableSignaling = ReliableSignaling;
    window.TransportProber = TransportProber;
}
