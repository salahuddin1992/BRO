# BRO - WiFi Communication Server

A complete communication server with real-time voice/video calls, messaging, file sharing, mesh networking, and a full admin control panel.

## Features

- **Voice & Video Calls** - WebRTC-based peer-to-peer calls
- **Real-time Chat** - Instant messaging (private & public)
- **File Sharing** - Upload and share files with all connected users
- **Mesh Networking** - Multiple servers interconnect automatically (up to 100+)
- **Admin Control Panel** - Full dashboard with real-time monitoring
- **Network Auto-Detection** - Works with all network types: WiFi, Ethernet, DSL, Fiber, GPON, 4G/5G, VPN, and all router types
- **Silent Mode** - Server runs in background without disturbing the user
- **EXE Builder** - One-click conversion to standalone executable

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python run.py --verbose

# Open in browser
# Client: http://localhost:8400/client
# Admin:  http://localhost:8400/admin
```

## Build EXE

```bash
python build_exe.py
# Choose option 1 for silent EXE, 2 for debug EXE
```

## Admin Login

- **Username:** admin
- **Password:** admin123

(Configure via environment variables `BRO_ADMIN_USER` and `BRO_ADMIN_PASS`)

## Architecture

```
BRO/
├── run.py              # Main entry point
├── build_exe.py        # EXE builder (PyInstaller)
├── config.py           # Global configuration
├── requirements.txt    # Python dependencies
├── server/
│   ├── bro_server.py   # Main Flask+SocketIO server
│   └── signaling.py    # WebRTC signaling handler
├── network/
│   └── detector.py     # Network interface auto-detection
├── mesh/
│   └── mesh_node.py    # Mesh networking (UDP discovery)
├── templates/
│   ├── admin.html      # Admin control panel
│   ├── client.html     # Client communication interface
│   └── login.html      # Admin login page
└── static/
    ├── css/
    ├── js/
    └── img/
```

## Supported Network Types

WiFi, Ethernet, DSL, ADSL, VDSL, Fiber, GPON, EPON, Cable, 4G, LTE, 5G, Cellular, VPN, WireGuard, PPPoE, Bridge, Bonded, USB Tethering, and all standard router types.

## Mesh Networking

Servers automatically discover each other on the local network via UDP broadcast. You can also manually connect to remote servers through the admin panel. Each server acts as a relay node, creating a fully interconnected mesh.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BRO_PORT` | 8400 | Server port |
| `BRO_SECRET` | random | Session secret key |
| `BRO_ADMIN_USER` | admin | Admin username |
| `BRO_ADMIN_PASS` | admin123 | Admin password |
| `BRO_LOG_LEVEL` | INFO | Log level |
