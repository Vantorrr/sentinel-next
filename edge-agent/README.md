# Sentinel Edge Agent

Local video processing agent for Sentinel-Next. Runs in each salon, captures RTSP camera streams, runs YOLOv11 detection + ByteTrack, and sends events to the central server.

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Set SENTINEL_API_KEY (from admin panel) and SENTINEL_API_URL

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
