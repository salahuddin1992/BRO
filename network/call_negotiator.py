"""
Helen WiFi - Cross-Server Call Negotiation System
When users on different servers want to make a call, this system:
1. Collects server capability scores from all involved servers
2. Elects the best server to host the call
3. Finds relay paths for servers that can't reach the host directly
4. Handles failover if the host goes down

Scoring weights:
  CPU available:   30%
  RAM available:   25%
  Connectivity:    25%
  Latency:         15%
  Current load:     5%
  SFU bonus:       +10 points if aiortc is available
"""
import logging
import threading
import time
import uuid
from collections import deque

logger = logging.getLogger("BRO.call_negotiator")


class ServerScore:
    """Encapsulates a server's capability assessment for hosting a call."""

    __slots__ = (
        "server_id", "cpu_available", "ram_available_gb", "total_ram_gb",
        "connectivity", "total_servers", "avg_latency_ms", "active_calls",
        "has_sfu", "timestamp", "score",
    )

    def __init__(self, server_id, cpu_available=0.5, ram_available_gb=4.0,
                 total_ram_gb=8.0, connectivity=1, total_servers=1,
                 avg_latency_ms=50.0, active_calls=0, has_sfu=False):
        self.server_id = server_id
        self.cpu_available = cpu_available          # 0.0 - 1.0 (fraction available)
        self.ram_available_gb = ram_available_gb
        self.total_ram_gb = total_ram_gb
        self.connectivity = connectivity            # number of directly reachable peers
        self.total_servers = max(total_servers, 1)
        self.avg_latency_ms = avg_latency_ms
        self.active_calls = active_calls
        self.has_sfu = has_sfu
        self.timestamp = time.time()
        self.score = 0.0

    def compute(self):
        """Compute weighted score (0-100 scale + SFU bonus)."""
        # CPU (30%): linear mapping, 1.0 available = 30 points
        cpu_score = self.cpu_available * 30.0

        # RAM (25%): linear mapping up to 16GB = 25 points, bonus for >32GB
        ram_score = min(self.ram_available_gb / 16.0, 1.0) * 25.0
        if self.total_ram_gb > 32:
            ram_score += 2.0  # slight bonus for high-memory servers

        # Connectivity (25%): fraction of reachable peers
        if self.total_servers > 1:
            conn_score = (self.connectivity / (self.total_servers - 1)) * 25.0
        else:
            conn_score = 25.0  # single server is fully connected by definition

        # Latency (15%): lower is better (0ms=15, 500ms+=0)
        latency_score = max(0.0, (1.0 - self.avg_latency_ms / 500.0)) * 15.0

        # Load (5%): fewer active calls is better (0=5, 10+=0)
        load_score = max(0.0, (1.0 - self.active_calls / 10.0)) * 5.0

        self.score = cpu_score + ram_score + conn_score + latency_score + load_score

        # SFU bonus
        if self.has_sfu:
            self.score += 10.0

        return self.score

    def to_dict(self):
        return {
            "server_id": self.server_id,
            "cpu_available": self.cpu_available,
            "ram_available_gb": self.ram_available_gb,
            "total_ram_gb": self.total_ram_gb,
            "connectivity": self.connectivity,
            "total_servers": self.total_servers,
            "avg_latency_ms": self.avg_latency_ms,
            "active_calls": self.active_calls,
            "has_sfu": self.has_sfu,
            "score": self.score,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d):
        s = cls(
            server_id=d["server_id"],
            cpu_available=d.get("cpu_available", 0.5),
            ram_available_gb=d.get("ram_available_gb", 4.0),
            total_ram_gb=d.get("total_ram_gb", 8.0),
            connectivity=d.get("connectivity", 1),
            total_servers=d.get("total_servers", 1),
            avg_latency_ms=d.get("avg_latency_ms", 50.0),
            active_calls=d.get("active_calls", 0),
            has_sfu=d.get("has_sfu", False),
        )
        s.score = d.get("score", 0.0)
        s.timestamp = d.get("timestamp", time.time())
        return s


class CallNegotiation:
    """Represents an ongoing cross-server call negotiation."""

    PHASE_COLLECTING = "collecting"
    PHASE_ELECTED = "elected"
    PHASE_ACTIVE = "active"
    PHASE_FAILED = "failed"
    PHASE_ENDED = "ended"

    def __init__(self, call_id, initiator_server, participants, call_type="audio"):
        self.call_id = call_id
        self.initiator_server = initiator_server
        self.call_type = call_type  # 'audio' or 'video'
        self.participants = participants  # [{username, server_id, sid}]
        self.scores = {}  # {server_id: ServerScore}
        self.phase = self.PHASE_COLLECTING
        self.host_server = None
        self.relay_paths = {}  # {server_id: [server_id, ...]} BFS paths to host
        self.created_at = time.time()
        self.elected_at = None
        self.expected_servers = set()  # servers we're waiting for scores from
        self._lock = threading.Lock()

    def add_score(self, score):
        """Add a server's score. Returns True if all scores collected."""
        with self._lock:
            self.scores[score.server_id] = score
            score.compute()
            return len(self.scores) >= len(self.expected_servers)

    def elect_host(self):
        """Elect the best server to host the call. Returns the winner."""
        with self._lock:
            if not self.scores:
                self.phase = self.PHASE_FAILED
                return None

            # Compute all scores
            for s in self.scores.values():
                s.compute()

            # Sort by score descending
            ranked = sorted(self.scores.values(), key=lambda s: s.score, reverse=True)
            self.host_server = ranked[0].server_id
            self.phase = self.PHASE_ELECTED
            self.elected_at = time.time()

            logger.info(
                "Call %s: elected host %s (score=%.1f) from %d candidates",
                self.call_id[:8], self.host_server, ranked[0].score, len(ranked),
            )
            return self.host_server

    def get_ranking(self):
        """Get servers ranked by score."""
        return sorted(self.scores.values(), key=lambda s: s.score, reverse=True)

    def to_dict(self):
        return {
            "call_id": self.call_id,
            "initiator_server": self.initiator_server,
            "call_type": self.call_type,
            "participants": self.participants,
            "scores": {sid: s.to_dict() for sid, s in self.scores.items()},
            "phase": self.phase,
            "host_server": self.host_server,
            "relay_paths": self.relay_paths,
            "created_at": self.created_at,
            "elected_at": self.elected_at,
        }


class CrossServerCallNegotiator:
    """
    Manages cross-server call negotiations.

    Lifecycle:
    1. User initiates cross-server call
    2. Initiating server creates CallNegotiation, requests scores from involved servers
    3. Each server computes its ServerScore and sends back
    4. Once all scores collected, host is elected
    5. BFS relay paths computed for servers that can't reach host directly
    6. All servers notified of host election and relay paths
    7. WebRTC signaling begins through CrossServerRouter

    Failover:
    - If host goes down, re-election triggers automatically
    - Second-best server takes over within seconds
    """

    # Timeout for score collection (seconds)
    SCORE_TIMEOUT = 10.0
    # Max age for a negotiation before cleanup
    NEGOTIATION_TTL = 300.0  # 5 minutes
    # Cleanup interval
    CLEANUP_INTERVAL = 60.0

    def __init__(self, server_id, mesh_node, sfu_manager=None):
        self.server_id = server_id
        self.mesh = mesh_node
        self.sfu = sfu_manager
        self.negotiations = {}  # {call_id: CallNegotiation}
        self._lock = threading.Lock()
        self._active_calls = {}  # {call_id: host_server_id} - currently active calls
        self._on_host_elected = None  # callback(negotiation)
        self._on_failover = None  # callback(call_id, old_host, new_host)
        self._running = False
        self._cleanup_thread = None

        # Adjacency graph for BFS: {server_id: set(server_id)}
        self._adjacency = {}
        self._adj_lock = threading.Lock()

    def start(self, on_host_elected=None, on_failover=None):
        """Start the negotiator with callbacks."""
        self._on_host_elected = on_host_elected
        self._on_failover = on_failover
        self._running = True
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="call-neg-cleanup"
        )
        self._cleanup_thread.start()
        logger.info("CrossServerCallNegotiator started for server %s", self.server_id)

    def stop(self):
        """Stop the negotiator."""
        self._running = False
        logger.info("CrossServerCallNegotiator stopped")

    def update_adjacency(self, server_id, reachable_peers):
        """Update the connectivity graph. Called when mesh topology changes."""
        with self._adj_lock:
            self._adjacency[server_id] = set(reachable_peers)

    def get_adjacency(self):
        """Get a copy of the adjacency graph."""
        with self._adj_lock:
            return {k: set(v) for k, v in self._adjacency.items()}

    # ---------- negotiation lifecycle ----------

    def initiate_negotiation(self, participants, call_type="audio"):
        """
        Start a new cross-server call negotiation.

        Args:
            participants: list of {username, server_id, sid}
            call_type: 'audio' or 'video'

        Returns:
            CallNegotiation instance
        """
        call_id = str(uuid.uuid4())

        negotiation = CallNegotiation(
            call_id=call_id,
            initiator_server=self.server_id,
            participants=participants,
            call_type=call_type,
        )

        # Determine which servers are involved
        involved_servers = set()
        for p in participants:
            involved_servers.add(p["server_id"])
        negotiation.expected_servers = involved_servers

        with self._lock:
            self.negotiations[call_id] = negotiation

        logger.info(
            "Call negotiation %s started: %d participants across %d servers (type=%s)",
            call_id[:8], len(participants), len(involved_servers), call_type,
        )

        return negotiation

    def compute_local_score(self, call_id):
        """
        Compute this server's score for a given negotiation.
        Returns a ServerScore instance.
        """
        with self._lock:
            negotiation = self.negotiations.get(call_id)
            if not negotiation:
                return None

        # Gather system stats
        try:
            from utils.monitor import get_system_stats
            stats = get_system_stats()
            cpu_available = 1.0 - (stats.get("cpu_percent", 50) / 100.0)
            ram = stats.get("memory", {})
            ram_available_gb = ram.get("available", 4 * 1024**3) / (1024**3)
            total_ram_gb = ram.get("total", 8 * 1024**3) / (1024**3)
        except Exception:
            cpu_available = 0.5
            ram_available_gb = 4.0
            total_ram_gb = 8.0

        # Connectivity: count directly reachable peers
        with self._adj_lock:
            my_peers = self._adjacency.get(self.server_id, set())
            connectivity = len(my_peers)
            total_servers = len(negotiation.expected_servers)

        # Latency: average ping to other involved servers
        avg_latency = self._measure_avg_latency(negotiation.expected_servers)

        # Active calls count
        active_calls = len(self._active_calls)

        # SFU availability
        has_sfu = self.sfu is not None and self.sfu.has_media_relay

        score = ServerScore(
            server_id=self.server_id,
            cpu_available=cpu_available,
            ram_available_gb=ram_available_gb,
            total_ram_gb=total_ram_gb,
            connectivity=connectivity,
            total_servers=total_servers,
            avg_latency_ms=avg_latency,
            active_calls=active_calls,
            has_sfu=has_sfu,
        )
        score.compute()

        logger.info(
            "Local score for call %s: %.1f (CPU=%.0f%% RAM=%.1fGB conn=%d/%d lat=%.0fms calls=%d sfu=%s)",
            call_id[:8], score.score, cpu_available * 100, ram_available_gb,
            connectivity, total_servers, avg_latency, active_calls, has_sfu,
        )

        return score

    def receive_score(self, call_id, score_dict):
        """
        Receive a score from a remote server.
        Returns the negotiation if all scores are collected (election can proceed).
        """
        with self._lock:
            negotiation = self.negotiations.get(call_id)
            if not negotiation:
                logger.warning("Score received for unknown call %s", call_id[:8])
                return None

        score = ServerScore.from_dict(score_dict)
        all_collected = negotiation.add_score(score)

        logger.info(
            "Score received from %s for call %s: %.1f (%d/%d collected)",
            score.server_id, call_id[:8], score.score,
            len(negotiation.scores), len(negotiation.expected_servers),
        )

        if all_collected:
            return negotiation
        return None

    def elect_and_notify(self, call_id):
        """
        Elect host for a call and compute relay paths.
        Returns the negotiation with host and paths set, or None on failure.
        """
        with self._lock:
            negotiation = self.negotiations.get(call_id)
            if not negotiation:
                return None

        host = negotiation.elect_host()
        if not host:
            return None

        # Compute BFS relay paths for all involved servers
        adjacency = self.get_adjacency()
        for server_id in negotiation.expected_servers:
            if server_id == host:
                negotiation.relay_paths[server_id] = [host]
                continue
            path = self._bfs_path(adjacency, server_id, host)
            if path:
                negotiation.relay_paths[server_id] = path
            else:
                # Fallback: try direct if BFS fails (might still work)
                negotiation.relay_paths[server_id] = [server_id, host]
                logger.warning(
                    "No BFS path from %s to host %s, using direct fallback",
                    server_id, host,
                )

        # Mark active
        with self._lock:
            self._active_calls[call_id] = host
        negotiation.phase = CallNegotiation.PHASE_ACTIVE

        logger.info(
            "Call %s: host=%s, paths=%s",
            call_id[:8], host,
            {k: v for k, v in negotiation.relay_paths.items()},
        )

        # Callback
        if self._on_host_elected:
            try:
                self._on_host_elected(negotiation)
            except Exception as e:
                logger.error("on_host_elected callback error: %s", e)

        return negotiation

    def handle_failover(self, call_id, failed_server):
        """
        Handle host server failure. Re-elect from remaining servers.
        Returns new negotiation state or None.
        """
        with self._lock:
            negotiation = self.negotiations.get(call_id)
            if not negotiation:
                return None

        old_host = negotiation.host_server
        logger.warning(
            "Failover for call %s: server %s failed (was host: %s)",
            call_id[:8], failed_server, failed_server == old_host,
        )

        # Remove failed server's score
        with negotiation._lock:
            negotiation.scores.pop(failed_server, None)
            negotiation.expected_servers.discard(failed_server)
            # Remove participants on the failed server
            negotiation.participants = [
                p for p in negotiation.participants
                if p["server_id"] != failed_server
            ]

        if not negotiation.scores:
            negotiation.phase = CallNegotiation.PHASE_FAILED
            return None

        # Re-elect
        new_host = negotiation.elect_host()
        if not new_host:
            negotiation.phase = CallNegotiation.PHASE_FAILED
            return None

        # Recompute paths
        adjacency = self.get_adjacency()
        negotiation.relay_paths.clear()
        for server_id in negotiation.expected_servers:
            if server_id == new_host:
                negotiation.relay_paths[server_id] = [new_host]
                continue
            path = self._bfs_path(adjacency, server_id, new_host)
            if path:
                negotiation.relay_paths[server_id] = path
            else:
                negotiation.relay_paths[server_id] = [server_id, new_host]

        with self._lock:
            self._active_calls[call_id] = new_host

        negotiation.phase = CallNegotiation.PHASE_ACTIVE

        logger.info(
            "Failover complete for call %s: old_host=%s new_host=%s",
            call_id[:8], old_host, new_host,
        )

        if self._on_failover:
            try:
                self._on_failover(call_id, old_host, new_host)
            except Exception as e:
                logger.error("on_failover callback error: %s", e)

        return negotiation

    def end_call(self, call_id):
        """Mark a call as ended and clean up."""
        with self._lock:
            negotiation = self.negotiations.get(call_id)
            if negotiation:
                negotiation.phase = CallNegotiation.PHASE_ENDED
            self._active_calls.pop(call_id, None)
        logger.info("Call %s ended", call_id[:8] if call_id else "unknown")

    def get_negotiation(self, call_id):
        """Get a negotiation by call_id."""
        with self._lock:
            return self.negotiations.get(call_id)

    def get_active_calls(self):
        """Get list of active call IDs."""
        with self._lock:
            return dict(self._active_calls)

    def get_stats(self):
        """Get negotiator statistics."""
        with self._lock:
            return {
                "active_negotiations": len(self.negotiations),
                "active_calls": len(self._active_calls),
                "server_id": self.server_id,
            }

    # ---------- BFS relay path finder ----------

    @staticmethod
    def _bfs_path(adjacency, start, end):
        """
        Find shortest path from start to end using BFS.

        Args:
            adjacency: {server_id: set(reachable_server_ids)}
            start: source server_id
            end: destination server_id

        Returns:
            List of server_ids from start to end, or None if unreachable.
        """
        if start == end:
            return [start]

        visited = {start}
        queue = deque([(start, [start])])

        while queue:
            current, path = queue.popleft()
            neighbors = adjacency.get(current, set())

            for neighbor in neighbors:
                if neighbor == end:
                    return path + [end]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None  # no path found

    # ---------- latency measurement ----------

    def _measure_avg_latency(self, target_servers):
        """
        Measure average latency to target servers.
        Uses mesh peer ping times if available, otherwise estimates.
        """
        if not self.mesh or not target_servers:
            return 50.0  # default estimate

        latencies = []
        for server_id in target_servers:
            if server_id == self.server_id:
                continue
            peer = self.mesh.peers.get(server_id)
            if peer:
                # Use last_seen freshness as a rough latency proxy
                age = time.time() - peer.get("last_seen", 0)
                # Fresh peers (seen recently) likely have low latency
                if age < 5:
                    latencies.append(10.0)
                elif age < 15:
                    latencies.append(30.0)
                elif age < 30:
                    latencies.append(80.0)
                else:
                    latencies.append(150.0)
            else:
                latencies.append(200.0)  # unknown peer = high latency estimate

        return sum(latencies) / len(latencies) if latencies else 50.0

    # ---------- score timeout checker ----------

    def check_score_timeout(self, call_id):
        """
        Check if score collection has timed out.
        Returns True if timed out and we should proceed with partial scores.
        """
        with self._lock:
            negotiation = self.negotiations.get(call_id)
            if not negotiation:
                return False

        if negotiation.phase != CallNegotiation.PHASE_COLLECTING:
            return False

        elapsed = time.time() - negotiation.created_at
        if elapsed > self.SCORE_TIMEOUT:
            logger.warning(
                "Score timeout for call %s: got %d/%d scores in %.1fs",
                call_id[:8], len(negotiation.scores),
                len(negotiation.expected_servers), elapsed,
            )
            return True
        return False

    # ---------- cleanup ----------

    def _cleanup_loop(self):
        """Periodically clean up old negotiations."""
        while self._running:
            time.sleep(self.CLEANUP_INTERVAL)
            try:
                self._cleanup_stale()
            except Exception as e:
                logger.error("Cleanup error: %s", e)

    def _cleanup_stale(self):
        """Remove negotiations older than TTL."""
        now = time.time()
        with self._lock:
            stale = [
                cid for cid, neg in self.negotiations.items()
                if now - neg.created_at > self.NEGOTIATION_TTL
            ]
            for cid in stale:
                del self.negotiations[cid]
                self._active_calls.pop(cid, None)
        if stale:
            logger.info("Cleaned up %d stale negotiations", len(stale))


class CallNegotiationProtocol:
    """
    Protocol messages for cross-server call negotiation.
    Defines message types exchanged between servers via mesh.
    """

    # Message types
    REQUEST_SCORES = "call_negotiate_request"
    SCORE_RESPONSE = "call_score_response"
    HOST_ELECTED = "call_host_elected"
    FAILOVER_TRIGGER = "call_failover_trigger"
    CALL_END = "call_end_notification"

    @staticmethod
    def make_score_request(call_id, participants, call_type, initiator_server):
        """Create a score request message to broadcast to involved servers."""
        return {
            "type": CallNegotiationProtocol.REQUEST_SCORES,
            "call_id": call_id,
            "participants": participants,
            "call_type": call_type,
            "initiator_server": initiator_server,
        }

    @staticmethod
    def make_score_response(call_id, score_dict):
        """Create a score response message."""
        return {
            "type": CallNegotiationProtocol.SCORE_RESPONSE,
            "call_id": call_id,
            "score": score_dict,
        }

    @staticmethod
    def make_host_elected(call_id, host_server, relay_paths, ranking):
        """Create a host elected notification."""
        return {
            "type": CallNegotiationProtocol.HOST_ELECTED,
            "call_id": call_id,
            "host_server": host_server,
            "relay_paths": relay_paths,
            "ranking": [s.to_dict() for s in ranking],
        }

    @staticmethod
    def make_failover_trigger(call_id, failed_server):
        """Create a failover trigger message."""
        return {
            "type": CallNegotiationProtocol.FAILOVER_TRIGGER,
            "call_id": call_id,
            "failed_server": failed_server,
        }

    @staticmethod
    def make_call_end(call_id):
        """Create a call end notification."""
        return {
            "type": CallNegotiationProtocol.CALL_END,
            "call_id": call_id,
        }
