# Webcam 2.0
**Self-healing YouTube livestream supervisor for RTSP-capable cameras**

Webcam 2.0 är ett Python-baserat system som automatiskt streamar från RTSP-kameror till YouTube Live (RTMPS).  
Om kameran tappar kontakt eller nätverket går ner, växlar systemet automatiskt till en lokal fallback-video och återgår till kameran när den är tillgänglig igen.

Projektet fungerar med alla RTSP-kompatibla IP-kameror, inklusive TP-Link Tapo, Reolink, Hikvision, Dahua och liknande.

---

## Installation

### 1. Installera beroenden
```bash
sudo apt update
sudo apt install -y ffmpeg python3 python3-venv yt-dlp git
```

### 2. Klona projektet
```bash
cd /opt
sudo git clone https://github.com/tellustheguru/webcam-2.0.git
cd webcam-2.0
```

### 3. Konfigurera
Redigera `webcam-supervisor.py` och uppdatera följande värden:

```python
RTSP_USER  = "kamerans-användare"
RTSP_PASS  = "kamerans-lösenord"
YT_KEY     = "din-youtube-streamnyckel"
TARGET_MAC = "xx:xx:xx:xx:xx:xx"   # kamerans MAC-adress
YT_CHANNEL_ID = "Din YouTube-kanal-ID"

# Overlay-text (kameraläge)
LABEL_TEXT = "gordalen.nu"
LABEL_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
LABEL_FONT_SIZE = 30
LABEL_TEXT_COLOR = "0x0F2C5C"
LABEL_OFFSET = 5           # px från överkant/vänster
LABEL_PADDING = 4          # box-padding
LABEL_BG_ALPHA = 0.6

# Watermark (kameraläge)
WATERMARK_ENABLED = True
WATERMARK_PATH = "/opt/webcam-2.0/gordalen_nu_logo.png"
WATERMARK_MAX_SIZE = 300   # max bredd/höjd i px
WATERMARK_MARGIN = 14      # px från höger/underkant
```

Placera en fallback-video här (spelas upp om kameran inte är tillgänglig):

```
/opt/webcam-2.0/fallback.mp4

Placera vattenmärkesbilden här (används endast i kameraläge, ej i fallback):

```
/opt/webcam-2.0/gordalen_nu_logo.png
```
```

### 4. Gör filen körbar
```bash
sudo chmod +x /opt/webcam-2.0/webcam-supervisor.py
```

---

## Skapa systemd-tjänst

Systemd används för att köra Webcam 2.0 som en bakgrundsprocess som startar automatiskt vid uppstart och återstartar vid fel.

1. Skapa tjänstfilen:
   ```bash
   sudo nano /etc/systemd/system/webcam-2.0-yt.service
   ```

2. Klistra in följande innehåll:

   ```ini
   [Unit]
   Description=Webcam 2.0 - RTSP to YouTube supervisor
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=simple
   WorkingDirectory=/opt/webcam-2.0
   ExecStart=/usr/bin/python3 /opt/webcam-2.0/webcam-supervisor.py
   Restart=always
   RestartSec=5
   User=root
   # Aktivera watchdog för extra robusthet:
   WatchdogSec=30
   StartLimitIntervalSec=120
   StartLimitBurst=5
   TimeoutStopSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. Ladda om systemd och aktivera tjänsten:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable webcam-2.0-yt
   sudo systemctl start webcam-2.0-yt
   ```

4. Kontrollera att tjänsten körs:
   ```bash
   sudo systemctl status webcam-2.0-yt
   ```

5. Visa loggar i realtid:
   ```bash
   sudo journalctl -u webcam-2.0-yt -f
   ```

---

## Aktivera systemets Watchdog

För ännu högre tillförlitlighet kan du låta **systemd’s egen watchdog** automatiskt starta om hela datorn om tjänsten hänger sig.

1. Aktivera watchdog i `system.conf`:
   ```bash
   sudo nano /etc/systemd/system.conf
   ```

2. Avkommentera och ändra dessa rader:
   ```
   RuntimeWatchdogSec=20s
   ShutdownWatchdogSec=10min
   ```

3. Starta om systemd:
   ```bash
   sudo systemctl daemon-reexec
   ```

4. Kontrollera:
   ```bash
   systemctl show | grep Watchdog
   ```

Systemd kommer nu automatiskt att övervaka att tjänsten svarar — om Python-processen fryser eller inte rapporterar livstecken inom 30 sekunder, startas den om. Om hela systemet låser sig, triggas en hård reboot via kernel-watchdog.

---

## Visa livestream på webbsida
Lägg in följande iframe i din HTML:

```html
<iframe
  width="1280"
  height="720"
  src="https://www.youtube.com/embed/live_stream?channel=DITT_CHANNEL_ID&autoplay=1&mute=1&controls=0&modestbranding=1&rel=0&playsinline=1"
  frameborder="0"
  allow="autoplay; encrypted-media"
  allowfullscreen>
</iframe>
```

---

## Funktioner

- Automatisk upptäckt av kamera via MAC-adress  
- RTSP till YouTube Live (RTMPS)  
- Automatisk fallback-video vid bortkoppling  
- Overlay-text (kameraläge) med bakgrundsruta  
- Vattenmärke (kameraläge) med justerbar storlek/marginal  
- Fallback-ström visas utan overlay/vattenmärke  
- Optimerad för LTE och instabila nätverk  
- Körs som systemd-tjänst med watchdog-stöd  
- Självläkande: återstartar automatiskt efter fel  

---

## Mappstruktur

```text
/opt/webcam-2.0/
├── webcam-supervisor.py   # Python-huvudscript
└── fallback.mp4           # Spelas vid kameraproblem
```

---

## Systemöversikt

```text
[RTSP-kamera]
      │
      ▼
[Python + ffmpeg supervisor]
      │
      ▼
[YouTube Live-ström]
      │
      └──▶ fallback.mp4 (vid bortfall)
```

---

## Felsökning

| Problem | Orsak | Lösning |
|---------|--------|---------|
| YouTube visar laddningsikon | RTMPS-anslutningen tappad | Vänta, fallback startar automatiskt |
| Ingen kamera hittas | DHCP-adress ändrad / fel MAC | Kontrollera `sudo journalctl -u webcam-2.0-yt -f` |
| Ingen ljudström | Fejkljud (`anullsrc`) används så att YouTube alltid får ljud |
| Fallback saknas | Filen `/opt/webcam-2.0/fallback.mp4` finns inte | Lägg till filen och starta om tjänsten |

---

## Licens
MIT License © 2025 Webcam 2.0 Project  
Fri att använda, modifiera och distribuera – behåll attribution.