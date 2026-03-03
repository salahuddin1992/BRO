"""
Helen WiFi - WebSocket Mesh Communication
Persistent WebSocket connections between mesh nodes for real-time sync.
Replaces HTTP polling with bidirectional WebSocket channels.
Smart reconnection with exponential backoff + optional zlib compression.
"""
import asyncio
import json
import logging
import threading
import time
import zlib

import websockets

logger = logging.getLogger("BRO.ws_mesh")


class WebSocketMeshBridge:
    """WebSocket-based mesh communication for real-time inter-server sync."""

    def __init__(self, server_id, host, port, secret_key):
        self.server_id = server_id
        self.host = host
        self.port = port
        self.ws_port = port + 2  # WebSocket on server_port + 2 (e.g. 8402)
        self.secret_key = secret_key
        self._connections = {}  # {peer_id: websocket}
        self._server = None
        self._loop = None
        self._thread = None
        self._running = False
        self._on_message = None
        self._on_peer_connected = None
        self._on_peer_disconnected = None
        # Smart reconnection
        self._reconnect_peers = {}  # {(host, ws_port): {attempts, next_retry, peer_id}}
        self._max_reconnect_attempts = 10
        # Compression
        self._compress = True

    def start(self, on_message=None, on_peer_connected=None, on_peer_disconnected=None):
        """Start WebSocket mesh server in a background thread."""
        self._on_message = on_message
        self._on_peer_connected = on_peer_connected
        self._on_peer_disconnected = on_peer_disconnected
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"WebSocket mesh started on port {self.ws_port}")

    def stop(self):
        """Stop WebSocket mesh server."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run_loop(self):
        """Run asyncio event loop in background thread."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._start_server())
            # Start reconnection monitor
            self._loop.create_task(self._reconnect_monitor())
            self._loop.run_forever()
        except RuntimeError as e:
            # Eventlet monkey-patching can conflict with asyncio event loops
            logger.debug(f"WebSocket mesh deferred (eventlet conflict): {e}")
        except Exception as e:
            logger.warning(f"WebSocket mesh loop error: {e}")
        finally:
            try:
                if self._loop and not self._loop.is_closed():
                    # Cancel pending tasks to avoid RuntimeWarning
                    pending = asyncio.all_tasks(self._loop)
                    for task in pending:
                        task.cancel()
                    self._loop.close()
            except Exception:
                pass

    async def _start_server(self):
        """Start WebSocket server for incoming mesh connections."""
        try:
            self._server = await websockets.serve(
                self._handle_connection,
                "0.0.0.0",
                self.ws_port,
                ping_interval=20,
                ping_timeout=10,
                compression="deflate",
            )
            logger.info(f"WebSocket mesh server listening on :{self.ws_port}")
        except OSError as e:
            logger.warning(f"WebSocket mesh bind failed on port {self.ws_port}: {e}")

    async def _reconnect_monitor(self):
        """Periodically attempt to reconnect to lost peers with exponential backoff."""
        while self._running:
            await asyncio.sleep(5)
            now = time.time()
            for key, info in list(self._reconnect_peers.items()):
                if info["attempts"] >= self._max_reconnect_attempts:
                    # Give up after max attempts
                    self._reconnect_peers.pop(key, None)
                    continue
                if now < info.get("next_retry", 0):
                    continue
                # Check if already connected
                peer_id = info.get("peer_id")
                if peer_id and peer_id in self._connections:
                    self._reconnect_peers.pop(key, None)
                    continue
                host, ws_port = key
                info["attempts"] += 1
                # Exponential backoff: 2^attempts seconds, max 120s
                delay = min(2 ** info["attempts"], 120)
                info["next_retry"] = now + delay
                logger.debug(f"Reconnect attempt {info['attempts']} to {host}:{ws_port}")
                try:
                    await self._connect(host, ws_port)
                    # Success - remove from reconnect list
                    self._reconnect_peers.pop(key, None)
                except Exception:
                    pass

    def _schedule_reconnect(self, host, ws_port, peer_id=None):
        """Schedule a peer for reconnection."""
        key = (host, ws_port)
        if key not in self._reconnect_peers:
            self._reconnect_peers[key] = {
                "attempts": 0,
                "next_retry": time.time() + 2,
                "peer_id": peer_id,
            }

    async def _handle_connection(self, websocket):
        """Handle an incoming WebSocket connection from a peer."""
        peer_id = None
        try:
            # First message must be auth
            auth_msg = await asyncio.wait_for(websocket.recv(), timeout=5)
            auth_data = json.loads(auth_msg)

            if auth_data.get("secret") != self.secret_key:
                await websocket.close(4001, "Unauthorized")
                return

            peer_id = auth_data.get("server_id")
            if not peer_id or peer_id == self.server_id:
                await websocket.close(4002, "Invalid peer")
                return

            self._connections[peer_id] = websocket
            logger.info(f"WS mesh peer connected: {peer_id}")

            if self._on_peer_connected:
                self._on_peer_connected(peer_id)

            # Send welcome
            await websocket.send(json.dumps({
                "type": "welcome",
                "server_id": self.server_id,
            }))

            # Listen for messages
            async for message in websocket:
                try:
                    # Try decompressing first
                    if isinstance(message, bytes):
                        try:
                            message = zlib.decompress(message).decode('utf-8')
                        except zlib.error:
                            message = message.decode('utf-8')
                    data = json.loads(message)
                    data["_from_peer"] = peer_id
                    if self._on_message:
                        self._on_message(data)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        except websockets.ConnectionClosed:
            pass
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.debug(f"WS mesh connection error: {e}")
        finally:
            if peer_id:
                self._connections.pop(peer_id, None)
                logger.info(f"WS mesh peer disconnected: {peer_id}")
                if self._on_peer_disconnected:
                    self._on_peer_disconnected(peer_id)

    def connect_to_peer(self, host, port):
        """Initiate a WebSocket connection to a peer server."""
        if not self._loop:
            return
        ws_port = port + 2
        asyncio.run_coroutine_threadsafe(
            self._connect(host, ws_port), self._loop
        )

    async def _connect(self, host, ws_port):
        """Establish outgoing WebSocket connection to a peer."""
        uri = f"ws://{host}:{ws_port}"
        try:
            websocket = await websockets.connect(
                uri,
                ping_interval=20,
                ping_timeout=10,
                compression="deflate",
            )
            # Authenticate
            await websocket.send(json.dumps({
                "secret": self.secret_key,
                "server_id": self.server_id,
            }))

            # Wait for welcome
            welcome = await asyncio.wait_for(websocket.recv(), timeout=5)
            welcome_data = json.loads(welcome)
            peer_id = welcome_data.get("server_id")

            if peer_id:
                self._connections[peer_id] = websocket
                logger.info(f"WS mesh connected to peer: {peer_id} at {host}:{ws_port}")

                if self._on_peer_connected:
                    self._on_peer_connected(peer_id)

                # Listen for messages
                try:
                    async for message in websocket:
                        try:
                            if isinstance(message, bytes):
                                try:
                                    message = zlib.decompress(message).decode('utf-8')
                                except zlib.error:
                                    message = message.decode('utf-8')
                            data = json.loads(message)
                            data["_from_peer"] = peer_id
                            if self._on_message:
                                self._on_message(data)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            pass
                except websockets.ConnectionClosed:
                    pass
                finally:
                    self._connections.pop(peer_id, None)
                    if self._on_peer_disconnected:
                        self._on_peer_disconnected(peer_id)
                    # Schedule reconnection
                    if self._running:
                        self._schedule_reconnect(host, ws_port, peer_id)

        except Exception as e:
            logger.debug(f"WS mesh connect to {host}:{ws_port} failed: {e}")
            # Schedule reconnection on failure
            if self._running:
                self._schedule_reconnect(host, ws_port)

    def send_to_peer(self, peer_id, data):
        """Send a message to a specific peer."""
        ws = self._connections.get(peer_id)
        if ws and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._send(ws, data), self._loop
            )
            return True
        return False

    def broadcast_to_peers(self, data):
        """Send a message to all connected peers."""
        for peer_id in list(self._connections.keys()):
            self.send_to_peer(peer_id, data)

    async def _send(self, websocket, data):
        """Send JSON data through a WebSocket connection, optionally compressed."""
        try:
            payload = json.dumps(data)
            # Compress large messages
            if self._compress and len(payload) > 512:
                compressed = zlib.compress(payload.encode('utf-8'))
                if len(compressed) < len(payload):
                    await websocket.send(compressed)
                    return
            await websocket.send(payload)
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            logger.debug(f"WS mesh send error: {e}")

    def get_connected_peers(self):
        """Return list of connected peer IDs."""
        return list(self._connections.keys())

    def is_peer_connected(self, peer_id):
        """Check if a peer is connected via WebSocket."""
        return peer_id in self._connections

    def get_stats(self):
        """Return WebSocket mesh stats."""
        return {
            "ws_port": self.ws_port,
            "connected_peers": len(self._connections),
            "peer_ids": list(self._connections.keys()),
            "pending_reconnects": len(self._reconnect_peers),
            "compression": self._compress,
        }
