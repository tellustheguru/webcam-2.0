# 🎥 Gördalen Webcam → YouTube Live
**Self-healing livestream for TP-Link Tapo and other RTSP-compatible cameras**

Automated Python-based livestream system designed for **TP-Link Tapo** cameras  
(but works with any IP camera that supports **RTSP**).  

It automatically:
- detects the camera via **MAC address**
- restreams **RTSP → YouTube Live (RTMPS)**
- monitors the connection
- switches to a **fallback video** if the camera or connection drops  
- and returns to the camera stream automatically when it comes back online.

Originally built for **Gördalen, Sweden**, this setup keeps a YouTube Live feed  
running 24/7 even in unreliable 4G/LTE networks.

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
sudo apt update
sudo apt install -y ffmpeg python3 python3-venv git
