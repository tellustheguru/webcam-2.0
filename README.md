# Webcam 2.0
**Self-healing YouTube livestream supervisor for RTSP-capable cameras**

Webcam 2.0 är ett Python-baserat system som automatiskt streamar från RTSP-kameror till YouTube Live (RTMPS).
Om kameran tappar kontakt eller nätverket går ner, växlar systemet automatiskt till en lokal fallback-video och återgår till kameran när den är tillgänglig igen.

Projektet fungerar med alla RTSP-kompatibla IP-kameror, inklusive TP-Link Tapo, Reolink, Hikvision, Dahua och liknande.

---


## Aktuell driftversion – uppdaterad 2026-10-08

Ändringarna från 2026-10-07 finns på kameraservern i `/opt/webcam-2.0`. Den aktuella källkoden är `webcam_onvif_supervisor.py`, YouTube-hanteraren och `gordalen-live-v2/`. Det äldre `webcam-supervisor.py` och gamla backupfiler har arkiverats utanför repot. Konfiguration och OAuth-filer ligger kvar lokalt på servern.

### Stabilare kamera- och YouTube-övervakning

Servern kör `webcam_onvif_supervisor.py`, som läser `webcam-supervisor.conf` bredvid skriptet. Miljövariabeln `WEBCAM_SUPERVISOR_CONF` kan ange en annan sökväg. `config.txt` var en äldre konfigurationsfil och har arkiverats; den aktuella versionen använder `webcam-supervisor.conf`.

- Schemalagda kameraomstarter är avstängda med `proactive_camera_restart_every=0`.
- YouTube HLS-uppslag använder 10 sekunders socket-timeout, en retry och högst 25 sekunder för subprocessen.
- Ett misslyckat HLS-uppslag bedöms som okänd tittarhälsa. Vid tröskeln för upprepade fel nollställs stall-räknarna, medan kamera- och ffmpeg-övervakningen fortsätter. Enbart otillgänglig HLS utlöser inte kameraomstart eller fallback.
- Bekräftade HLS-stopp och faktiska kamera-/ffmpeg-fel behåller sin återställningshantering.

### Joomla/YOOtheme och YouTube Live

På servern finns `gordalen-live-v2/` med Gordalen Live Player 2.0.0. Pluginet installeras via Joomlas vanliga installationsfunktion. Det använder YOOthemes vanliga Video-element med kanalens permanenta YouTube-adress och behåller elementets layoutinställningar. Inga Joomla- eller YOOtheme-kärnfiler ändras.

`publish_youtube_live.py` körs ungefär varje minut via systemd-timer. Det säkerställer sändningen och publicerar aktuellt video-ID över HTTPS till Joomlas `com_ajax`-endpoint. POST kräver publisher-nyckeln. API- eller nätverksfel behåller senast publicerad status; ett uttryckligt resultat utan livesändning publicerar null. Spelaren upptäcker ersättningssändningar och återgår till livekanten.

Nya sändningar skapas med `enableDvr=false`. YouTube tillåter inte avstängd inspelning för den här kanalen. Sändningshanteraren raderar därför avslutade sändningar där både webbkamerans exakta titel och bundna stream-ID matchar. Andra videor lämnas kvar. Radering kan fördröjas vid API-fel.

Vid PHP-deploy på den aktuella webbservern (`opcache.validate_timestamps=0`) behöver ändrade pluginfiler invalideras i FPM:s OPcache, eller FPM laddas om. Enbart rensning av Joomla-cache räcker inte. Fullständig integrationsdokumentation finns i [gordalen-live-v2/README.md](gordalen-live-v2/README.md).

### Konfiguration och GitHub

`.gitignore` utesluter `config.txt`, `webcam-supervisor.conf`, `publisher.json`, `.env`, YouTube OAuth-filer och deras säkerhetskopior, även i undermappar. Verkliga nycklar och lösenord ska finnas lokalt på servern. Konfigurationsfilerna var inte spårade på `main` när repot kontrollerades 2026-10-08.

Kontrollera en fil med `git check-ignore -v -- <sökväg>` och `git ls-files -- <sökväg>`. Om den redan är spårad i ett annat checkout: kör `git rm --cached -- <sökväg>` och committa ändringen. Den lokala filen behålls. Ignorering tar inte bort tidigare innehåll ur Git-historiken.

## Drift och utveckling på servern

Servermappen `/opt/webcam-2.0` är kopplad till detta repo. `main` följer `origin/main`; hämtning använder HTTPS och push använder serverns separata SSH deploy key. Git kan användas som `andersj` utan sudo. Driftfilerna ägs fortfarande av root.

- `webcam_onvif_supervisor.py`: kameraövervakning, ffmpeg och fallback.
- `youtube_live_manager.py`: hantering av YouTube-sändningar och avslutade arkiv.
- `youtube_oauth_authorize.py`: lokal OAuth-auktorisering.
- `gordalen-live-v2/`: Joomla-plugin, publisher, byggskript och tester.
- `fallback.mp4` och `gordalen_nu_logo.png`: driftens mediafiler.
- `webcam-supervisor.conf`, `.env`, OAuth-JSON och `gordalen-live-v2/publisher.json`: lokal konfiguration som inte ska committas.

Kontrollera kameraövervakningen med `systemctl status webcam-2.0-yt.service` och loggarna med `journalctl -u webcam-2.0-yt.service -f`. Publiceringens timer heter `gordalen-live-publish.timer`.

Bygg Joomla-paketet med `python3 gordalen-live-v2/build.py`. ZIP-filen skapas från `plugin/`, installeras via Joomla och ignoreras av Git eftersom den kan byggas från källkoden.

Backupfiler (`*.bak`, `*.orig`, `*.rej`, `*.before-*`) och pensionerade v1-mappar ignoreras också. De befintliga gamla filerna flyttades 2026-10-08 till ett skyddat arkiv under `/opt/webcam-2.0-archive/`, utanför repot. Ingen commit eller push görs automatiskt vid städning.
