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
sudo apt install -y ffmpeg python3 python3-venv git
```

### 2. Klona projektet
```bash
cd /opt
sudo git clone https://github.com/<DITT-GITHUB-ANVÄNDARNAMN>/webcam-2.0.git
cd webcam-2.0
```

### 3. Konfigurera
Redigera `webcam-supervisor.py` och uppdatera följande värden:

```python
RTSP_USER  = "kamerans-användare"
RTSP_PASS  = "kamerans-lösenord"
YT_KEY     = "din-youtube-streamnyckel"
TARGET_MAC = "xx:xx:xx:xx:xx:xx"   # kamerans MAC-adress
```

Placera en fallback-video här (spelas upp om kameran inte är tillgänglig):

```
/opt/webcam-2.0/fallback.mp4
```

### 4. Gör filen körbar
```bash
sudo chmod +x /opt/webcam-2.0/webcam-supervisor.py
```

### 5. Installera som systemd-tjänst (om filen redan finns i repo)
```bash
sudo cp systemd/webcam-2.0-yt.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable webcam-2.0-yt
sudo systemctl start webcam-2.0-yt
```

Visa loggar i realtid:
```bash
sudo journalctl -u webcam-2.0-yt -f
```

---

## Skapa systemd-tjänsten manuellt

Om du inte har `systemd/webcam-2.0-yt.service` i repot, kan du skapa den själv.

1. Öppna en ny fil:
   ```bash
   sudo nano /etc/systemd/system/webcam-2.0-yt.service
   ```

2. Klistra in detta innehåll:

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
   # Om du vill läsa variabler från fil:
   # EnvironmentFile=/etc/webcam-2.0.env

   [Install]
   WantedBy=multi-user.target
   ```

3. Ladda om systemd och starta tjänsten:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable webcam-2.0-yt
   sudo systemctl start webcam-2.0-yt
   ```

4. Kolla loggen:

   ```bash
   sudo journalctl -u webcam-2.0-yt -f
   ```

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
- Optimerad för LTE och instabila nätverk  
- Körs som systemd-tjänst  
- Självläkande: återstartar automatiskt efter fel  

---

## Mappstruktur

```text
/opt/webcam-2.0/
├── webcam-supervisor.py   # Python-huvudscript
├── fallback.mp4           # Spelas vid kameraproblem
└── systemd/
    └── webcam-2.0-yt.service
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