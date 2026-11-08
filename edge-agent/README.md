# Sentinel Edge Agent

Windows salon package: `packaging/README_RU.txt`. Version 0.2.0 registers a visible boot task and does not reinstall dependencies on every start. The agent sends JSON events only. It does not recognize faces and it does not upload video.

Local video processing agent for Sentinel-Next. Runs in each salon, captures RTSP camera streams, runs YOLOv11 detection + ByteTrack, and sends events to the central server.

## Quick Start

```bash
# 1. Configure. Values are data, not shell commands.
cp packaging/env.example .env
# Set SENTINEL_API_KEY and SENTINEL_API_URL. `sentinel-edge run` reads ./.env.

# 2. Install
pip install -e .

# 3. Run
sentinel-edge start
```

## Docker

```bash
docker build -t sentinel-edge .

docker run -d --name sentinel-edge \
  --env-file .env \
  --restart unless-stopped \
  sentinel-edge
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SENTINEL_API_URL` | `http://localhost:8000` | Central server URL |
| `SENTINEL_API_KEY` | (required) | Tenant API key from admin panel |
| `SENTINEL_AGENT_ID` | auto-generated | Unique agent identifier |
| `SENTINEL_AGENT_NAME` | `edge-1` | Human-readable name |
| `SENTINEL_CAMERAS` | `0` | Comma-separated RTSP URLs or webcam indices |
| `SENTINEL_FPS_INFERENCE` | `10` | Frames per second for inference |
| `SENTINEL_YOLO_MODEL` | `yolo11n.pt` | YOLO model file |
| `SENTINEL_YOLO_CONFIDENCE` | `0.35` | Detection confidence threshold |
| `SENTINEL_HEARTBEAT_INTERVAL` | `30` | Heartbeat interval (seconds) |

## Where it has to run

The agent opens `SENTINEL_CAMERAS` from the machine it runs on. A private recorder address is reachable only on that LAN (same network as the NVR). A central server on a public host does not pull those URLs and must not invent a placeholder host.

`Camera <id> opened` means OpenCV opened the source. It is not a frame. Wait for `Camera <id> first frame received`. The URL is not written to the log.

The process reads `SENTINEL_API_URL`, `SENTINEL_API_KEY` and `SENTINEL_CAMERAS` only.

## How It Works

1. Agent captures frames from local cameras via OpenCV
2. YOLOv11 detects people, ByteTrack assigns persistent track IDs
3. Events (`client.entered`, `person.lost`, `occupancy.update`) are batched
4. Batches are sent to the central server via `POST /api/v1/agent/events`
5. Heartbeat pings `POST /api/v1/agent/heartbeat` every 30s
6. Face embeddings can be synced via `GET /api/v1/agent/faces`

## Multiple Cameras

```bash
SENTINEL_CAMERAS="rtsp://admin:pass@192.168.1.100:554/Streaming/Channels/101,rtsp://admin:pass@192.168.1.101:554/Streaming/Channels/101"
```
