#!/usr/bin/env python3
import configparser
import json, os, shlex, signal, socket, subprocess, time, select
from ipaddress import ip_network, ip_address
from pathlib import Path

# ========= KONFIG =========
CONFIG_FILE = Path(
    os.environ.get(
        "WEBCAM_SUPERVISOR_CONF",
        str(Path(__file__).with_name("webcam-supervisor.conf")),
    )
)

DEFAULTS = {
    "auth": {
        "rtsp_user": "<ANVANDARE>",
        "rtsp_pass": "<LOSENORD>",
        "target_mac": "<MAC-ADDRESS>",
    },
    "youtube": {
        "yt_key": "<YOUTUBE-STREAM-KEY>",
        "use_backup": "false",
        "enable_yt_healthcheck": "true",
        "yt_channel_id": "<YOUTUBE-CHANNEL-ID>",
        "yt_healthcheck_every": "30",
        "yt_stall_grace": "3",
        "yt_post_restart_cooldown": "90",
        "yt_stall_camera_recoveries": "2",
        "yt_probe_fail_grace": "3",
        "yt_probe_fail_camera_recoveries": "1",
        "yt_fallback_min_seconds": "45",
        "yt_recovery_check_interval": "10",
        "yt_recovery_max_wait": "1800",
        "yt_ingest_retry_initial": "120",
        "yt_ingest_retry_max": "600",
        "yt_ingest_retry_stable": "120",
    },
    "paths": {
        "fallback_mp4": "/opt/webcam-2.0/fallback.mp4",
        "watermark_path": "/opt/webcam-2.0/gordalen_nu_logo.png",
        "label_font": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    },
    "video": {
        "fps": "15",
        "vbps": "1800k",
        "maxrate": "2000k",
        "bufsize": "3500k",
    },
    "monitoring": {
        "scan_interval": "2",
        "ping_interval": "2",
        "camera_probe_every": "30",
        "camera_probe_fail_grace": "3",
    },
    "overlay": {
        "label_text": "<VALFRI-TEXT>",
        "label_font_size": "30",
        "label_text_color": "0x0F2C5C",
        "label_offset": "5",
        "label_padding": "4",
        "label_bg_alpha": "0.6",
    },
    "watermark": {
        "watermark_enabled": "true",
        "watermark_max_size": "300",
        "watermark_margin": "14",
    },
    "restarts": {
        "camera_death_restart_limit": "4",
        "camera_death_restart_window": "90",
        "recoverable_restart_limit": "4",
        "recoverable_restart_window": "600",
        "proactive_camera_restart_every": "0",
        "proactive_camera_restart_min_uptime": "600",
    },
    "network": {
        "static_cidr": "192.168.0.0/24",
    },
    "ffmpeg": {
        "recoverable_patterns": (
            "Error in the push function|Broken pipe|IO error: End of file|"
            "The specified session has been invalidated"
        ),
        "fatal_patterns": "Slave muxer #0 failed|Slave muxer #1 failed|All tee outputs failed",
    },
}


def _load_config(path):
    cfg = configparser.ConfigParser(defaults=None, interpolation=None)
    cfg.read_dict(DEFAULTS)
    cfg.read(path, encoding="utf-8")
    return cfg


def _split_patterns(value):
    return tuple(part.strip() for part in value.split("|") if part.strip())


_CONFIG_GUARDRAIL_NOTES = []


def _clamp_int_setting(name, value, min_value=None, max_value=None):
    original = value
    if min_value is not None and value < min_value:
        value = min_value
    if max_value is not None and value > max_value:
        value = max_value
    if value != original:
        _CONFIG_GUARDRAIL_NOTES.append(
            f"{name} justerades från {original} till {value} (guardrail)"
        )
    return value


_CFG = _load_config(CONFIG_FILE)

RTSP_USER = _CFG.get("auth", "rtsp_user")
RTSP_PASS = _CFG.get("auth", "rtsp_pass")
TARGET_MAC = _CFG.get("auth", "target_mac").lower()

YT_KEY = _CFG.get("youtube", "yt_key")
YT_PRIMARY = _CFG.get(
    "youtube", "yt_primary", fallback=f"rtmps://a.rtmp.youtube.com/live2/{YT_KEY}"
)
YT_BACKUP = _CFG.get(
    "youtube",
    "yt_backup",
    fallback=f"rtmps://b.rtmp.youtube.com/live2?backup=1/{YT_KEY}",
)
USE_BACKUP = _CFG.getboolean("youtube", "use_backup")
ENABLE_YT_HEALTHCHECK = _CFG.getboolean("youtube", "enable_yt_healthcheck")
YT_CHANNEL_ID = _CFG.get("youtube", "yt_channel_id")
YT_HEALTHCHECK_EVERY = _CFG.getint("youtube", "yt_healthcheck_every")
YT_STALL_GRACE = _CFG.getint("youtube", "yt_stall_grace")
YT_POST_RESTART_COOLDOWN = _CFG.getint("youtube", "yt_post_restart_cooldown")
YT_STALL_CAMERA_RECOVERIES = _CFG.getint("youtube", "yt_stall_camera_recoveries")
YT_PROBE_FAIL_GRACE = _CFG.getint("youtube", "yt_probe_fail_grace")
YT_PROBE_FAIL_CAMERA_RECOVERIES = _CFG.getint(
    "youtube", "yt_probe_fail_camera_recoveries"
)
YT_FALLBACK_MIN_SECONDS = _CFG.getint("youtube", "yt_fallback_min_seconds")
YT_RECOVERY_CHECK_INTERVAL = _CFG.getint("youtube", "yt_recovery_check_interval")
YT_RECOVERY_MAX_WAIT = _CFG.getint("youtube", "yt_recovery_max_wait")
YT_INGEST_RETRY_INITIAL = _CFG.getint("youtube", "yt_ingest_retry_initial")
YT_INGEST_RETRY_MAX = _CFG.getint("youtube", "yt_ingest_retry_max")
YT_INGEST_RETRY_STABLE = _CFG.getint("youtube", "yt_ingest_retry_stable")

# Guardrails: tillat inte for langsam recovery som riskerar stream-timeout.
YT_HEALTHCHECK_EVERY = _clamp_int_setting(
    "youtube.yt_healthcheck_every", YT_HEALTHCHECK_EVERY, min_value=10
)
YT_POST_RESTART_COOLDOWN = _clamp_int_setting(
    "youtube.yt_post_restart_cooldown",
    YT_POST_RESTART_COOLDOWN,
    min_value=20,
)
YT_PROBE_FAIL_GRACE = _clamp_int_setting(
    "youtube.yt_probe_fail_grace", YT_PROBE_FAIL_GRACE, min_value=2, max_value=4
)
YT_PROBE_FAIL_CAMERA_RECOVERIES = _clamp_int_setting(
    "youtube.yt_probe_fail_camera_recoveries",
    YT_PROBE_FAIL_CAMERA_RECOVERIES,
    min_value=0,
    max_value=1,
)
YT_FALLBACK_MIN_SECONDS = _clamp_int_setting(
    "youtube.yt_fallback_min_seconds",
    YT_FALLBACK_MIN_SECONDS,
    min_value=10,
)
YT_RECOVERY_CHECK_INTERVAL = _clamp_int_setting(
    "youtube.yt_recovery_check_interval",
    YT_RECOVERY_CHECK_INTERVAL,
    min_value=5,
    max_value=15,
)
YT_INGEST_RETRY_INITIAL = _clamp_int_setting(
    "youtube.yt_ingest_retry_initial", YT_INGEST_RETRY_INITIAL, min_value=2
)
YT_INGEST_RETRY_MAX = _clamp_int_setting(
    "youtube.yt_ingest_retry_max",
    YT_INGEST_RETRY_MAX,
    min_value=YT_INGEST_RETRY_INITIAL,
)
YT_INGEST_RETRY_STABLE = _clamp_int_setting(
    "youtube.yt_ingest_retry_stable", YT_INGEST_RETRY_STABLE, min_value=30
)

FALLBACK_MP4 = _CFG.get("paths", "fallback_mp4")
WATERMARK_PATH = _CFG.get("paths", "watermark_path")
LABEL_FONT = _CFG.get("paths", "label_font")

FPS = _CFG.getint("video", "fps")
GOP = FPS * 2
VBPS = _CFG.get("video", "vbps")
MAXRATE = _CFG.get("video", "maxrate")
BUFSIZE = _CFG.get("video", "bufsize")

CAMERA_PROBE_EVERY = _clamp_int_setting(
    "monitoring.camera_probe_every",
    _CFG.getint("monitoring", "camera_probe_every"),
    min_value=10,
)
CAMERA_PROBE_FAIL_GRACE = _clamp_int_setting(
    "monitoring.camera_probe_fail_grace",
    _CFG.getint("monitoring", "camera_probe_fail_grace"),
    min_value=2,
)
SCAN_INTERVAL = _CFG.getfloat("monitoring", "scan_interval")
PING_INTERVAL = _CFG.getfloat("monitoring", "ping_interval")

LABEL_TEXT = _CFG.get("overlay", "label_text")
LABEL_FONT_SIZE = _CFG.getint("overlay", "label_font_size")
LABEL_TEXT_COLOR = _CFG.get("overlay", "label_text_color")
LABEL_OFFSET = _CFG.getint("overlay", "label_offset")
LABEL_PADDING = _CFG.getint("overlay", "label_padding")
LABEL_BG_ALPHA = _CFG.getfloat("overlay", "label_bg_alpha")

WATERMARK_ENABLED = _CFG.getboolean("watermark", "watermark_enabled")
WATERMARK_MAX_SIZE = _CFG.getint("watermark", "watermark_max_size")
WATERMARK_MARGIN = _CFG.getint("watermark", "watermark_margin")

CAMERA_DEATH_RESTART_LIMIT = _CFG.getint("restarts", "camera_death_restart_limit")
CAMERA_DEATH_RESTART_WINDOW = _CFG.getint("restarts", "camera_death_restart_window")
RECOVERABLE_RESTART_LIMIT = _CFG.getint("restarts", "recoverable_restart_limit")
RECOVERABLE_RESTART_WINDOW = _CFG.getint("restarts", "recoverable_restart_window")
PROACTIVE_CAMERA_RESTART_EVERY = _CFG.getint(
    "restarts", "proactive_camera_restart_every"
)
PROACTIVE_CAMERA_RESTART_MIN_UPTIME = _CFG.getint(
    "restarts", "proactive_camera_restart_min_uptime"
)

STATIC_CIDR = _CFG.get("network", "static_cidr")

FFMPEG_RECOVERABLE_PATTERNS = _split_patterns(
    _CFG.get("ffmpeg", "recoverable_patterns")
)
FFMPEG_FATAL_PATTERNS = _split_patterns(_CFG.get("ffmpeg", "fatal_patterns"))


def _looks_like_placeholder(value):
    if value is None:
        return True
    value = str(value).strip()
    if not value:
        return True
    return value.startswith("<") and value.endswith(">")


def validate_required_config():
    missing = []
    checks = {
        "auth.rtsp_user": RTSP_USER,
        "auth.rtsp_pass": RTSP_PASS,
        "auth.target_mac": TARGET_MAC,
        "youtube.yt_key": YT_KEY,
        "youtube.yt_channel_id": YT_CHANNEL_ID,
    }
    for key, value in checks.items():
        if _looks_like_placeholder(value):
            missing.append(key)
    return missing

# ========= HJÄLPARE =========
def log(msg):
    print(f"[gordalen] {msg}", flush=True)

def ensure_youtube_live():
    """Create and bind a new YouTube broadcast when none remains."""
    try:
        from youtube_live_manager import ensure_youtube_broadcast

        ensure_youtube_broadcast(
            channel_id=YT_CHANNEL_ID,
            stream_title="Webcam 2.0",
            logger=log,
        )
        return True
    except Exception as exc:
        log(f"YouTube API-reparation misslyckades: {exc}")
        return False


def run(cmd):
    return subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)

def popen(cmd, inherit=False):
    if inherit:
        return subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)
    return subprocess.Popen(
        cmd, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, preexec_fn=os.setsid
    )

def kill_tree(p):
    if p and p.poll() is None:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except:
            pass
        try:
            p.wait(timeout=2)
        except:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except:
                pass

def ffprobe_has_video(rtsp_url):
    cmd = (
        f'timeout -k 2 3 '
        f'ffprobe -v error -rtsp_transport tcp '
        f'-select_streams v -show_streams -of json {shlex.quote(rtsp_url)}'
    )
    r = run(cmd)
    out = (r.stdout or "") + (r.stderr or "")
    if '"codec_type":"video"' in out or '"codec_type": "video"' in out:
        return True
    try:
        data = json.loads(r.stdout or "{}")
        return any(s.get("codec_type") == "video" for s in data.get("streams", []))
    except Exception:
        return False

def default_cidr():
    r = run("ip -j route show default")
    try:
        routes = json.loads(r.stdout)
        if routes and "dev" in routes[0]:
            dev = routes[0]["dev"]
            js = json.loads(run(f"ip -j -4 addr show dev {shlex.quote(dev)}").stdout)
            for a in js[0].get("addr_info", []):
                if a.get("family") == "inet":
                    return f"{a['local']}/{a['prefixlen']}"
    except Exception:
        pass
    r = run("ip -j -4 addr show up")
    try:
        js = json.loads(r.stdout)
        for it in js:
            if it.get("ifname") == "lo":
                continue
            for a in it.get("addr_info", []):
                if a.get("family") == "inet":
                    return f"{a['local']}/{a['prefixlen']}"
    except Exception:
        pass
    return STATIC_CIDR

def normalize_net(cidr_str):
    net = ip_network(cidr_str, strict=False)
    if net.prefixlen < 24:
        net = ip_network(f"{net.network_address}/24", strict=False)
    return net

def tcp_port_open(ip, port=554, timeout=0.5):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((str(ip), port))
            return True
        except Exception:
            return False

def arp_table():
    r = run("ip -json neigh")
    out = {}
    try:
        for row in json.loads(r.stdout or "[]"):
            ip = row.get("dst")
            mac = (row.get("lladdr") or "").lower()
            if ip and mac:
                out[ip] = mac
    except Exception:
        pass
    return out

def ping_sweep(net):
    for ip in net.hosts():
        subprocess.Popen(f"ping -c1 -W1 {ip} >/dev/null 2>&1", shell=True)
    time.sleep(2)

def find_ip_by_mac(target_mac, net):
    if not target_mac:
        return None
    ping_sweep(net)
    table = arp_table()
    for ip, mac in table.items():
        if mac.lower() == target_mac:
            try:
                if ip_address(ip) in net:
                    return ip
            except ValueError:
                pass
    return None

def make_rtsp_urls(ip):
    base = f"rtsp://{RTSP_USER}:{RTSP_PASS}@{ip}:554"
    return [f"{base}/stream1", f"{base}/stream2"]


def safe_rtsp_url(url):
    """Mask credentials before an RTSP URL is written to logs."""
    if not url or "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    return f"{scheme}://<credentials>@{rest.split('@', 1)[1]}"


def find_camera_by_mac(target_mac):
    cidr = default_cidr() or STATIC_CIDR
    net = normalize_net(cidr)
    log(f"söker kamera i {net.network_address}/{net.prefixlen} …")

    ip = find_ip_by_mac(target_mac, net) if target_mac else None
    if ip:
        log(f"MAC-träff: {ip} ({target_mac}) – provar RTSP")
        for url in make_rtsp_urls(ip):
            log(f"provar {safe_rtsp_url(url)}")
            if ffprobe_has_video(url):
                log(f"hittade kamera (MAC match): {ip} via {safe_rtsp_url(url)}")
                return True, url

    ping_sweep(net)
    table = arp_table()
    arp_ips = [i for i in table.keys() if ip_address(i) in net]
    if arp_ips:
        log(f"provar ARP-IP:er först: {arp_ips[:8]}{' …' if len(arp_ips)>8 else ''}")
        for ip in arp_ips:
            for url in make_rtsp_urls(ip):
                log(f"provar {safe_rtsp_url(url)}")
                if ffprobe_has_video(url):
                    log(f"hittade kamera: {ip} via {safe_rtsp_url(url)}")
                    return True, url

    candidates = []
    for host in net.hosts():
        sip = str(host)
        if sip in arp_ips:
            continue
        if tcp_port_open(sip, 554):
            candidates.append(sip)

    if candidates:
        log(f"kandidater via port 554: {candidates[:8]}{' …' if len(candidates)>8 else ''}")
        for ip in candidates:
            for url in make_rtsp_urls(ip):
                log(f"provar {safe_rtsp_url(url)}")
                if ffprobe_has_video(url):
                    log(f"hittade kamera: {ip} via {safe_rtsp_url(url)}")
                    return True, url

    return False, None

def out_mux():
    if USE_BACKUP:
        return ('-f tee '
                f'"[f=flv:flvflags=no_duration_filesize:onfail=ignore]{YT_PRIMARY}|'
                f'[f=flv:flvflags=no_duration_filesize:onfail=ignore]{YT_BACKUP}"')
    return f'-f flv "{YT_PRIMARY}"'


def _rounded_alpha_expr(width, height, radius):
    right = width - radius - 1
    bottom = height - radius - 1
    return (
        f"if(between(X,{radius},{width - radius - 1})*between(Y,{radius},{height - radius - 1}),255,"
        f"if(lte(hypot(X-{radius},Y-{radius}),{radius}),255,"
        f"if(lte(hypot(X-{right},Y-{radius}),{radius}),255,"
        f"if(lte(hypot(X-{radius},Y-{bottom}),{radius}),255,"
        f"if(lte(hypot(X-{right},Y-{bottom}),{radius}),255,0)))))"
    )


def _ffmpeg_escape(text):
    return (text
            .replace("\\", r"\\\\")
            .replace(":", r"\:")
            .replace("'", r"\'")
            .replace("[", r"\[")
            .replace("]", r"\]")
            )


def build_filter_graph(base_chain, include_label=True, include_watermark=False, wm_input_index=1):
    text = _ffmpeg_escape(LABEL_TEXT)
    fontfile = LABEL_FONT.replace(':', r'\:')
    text_x = LABEL_OFFSET + LABEL_PADDING
    text_y = f"{LABEL_OFFSET + LABEL_PADDING}+text_h"
    parts = [f"[0:v]{base_chain},format=rgba[base]"]
    current = "base"

    if include_watermark:
        parts.append(
            f"[{wm_input_index}:v]scale=w='min(iw,{WATERMARK_MAX_SIZE})':"
            f"h='min(ih,{WATERMARK_MAX_SIZE})':force_original_aspect_ratio=decrease,"
            f"format=rgba[wm]"
        )
        parts.append(
            f"[{current}][wm]overlay=W-w-{WATERMARK_MARGIN}:"
            f"H-h-{WATERMARK_MARGIN}[withwm]"
        )
        current = "withwm"

    if include_label:
        parts.append(
            f"[{current}]drawtext=fontfile='{fontfile}':text='{text}':"
            f"fontsize={LABEL_FONT_SIZE}:fontcolor={LABEL_TEXT_COLOR}:"
            f"x={text_x}:y={text_y}:"
            f"box=1:boxcolor=white@{LABEL_BG_ALPHA}:boxborderw={LABEL_PADDING * 2}" \
            f"[withtext]"
        )
        current = "withtext"

    parts.append(f"[{current}]format=yuv420p[vout]")
    return ";".join(parts)

def cmd_from_rtsp(rtsp):
    base_chain = (
        f'scale=1280:720:force_original_aspect_ratio=decrease:in_range=full:out_range=tv,'
        f'pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps={FPS},setsar=1'
    )
    use_wm = WATERMARK_ENABLED and os.path.exists(WATERMARK_PATH)
    audio_input_index = 2 if use_wm else 1

    inputs = [f'-i "{rtsp}"']
    if use_wm:
        inputs.append(f'-loop 1 -i "{WATERMARK_PATH}"')
    inputs.append('-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100')

    wm_input_index = 1 if use_wm else None
    filter_graph = build_filter_graph(
        base_chain,
        include_label=True,
        include_watermark=use_wm,
        wm_input_index=wm_input_index,
    )
    return (
        'ffmpeg '
        '-hide_banner -loglevel error -strict -1 '
        '-fflags nobuffer -fflags +genpts '
        '-use_wallclock_as_timestamps 1 '
        '-rtsp_transport tcp -rtsp_flags prefer_tcp '
        '-thread_queue_size 1024 -probesize 1M -analyzeduration 20M '
        '-rtbufsize 512M '
        + " ".join(inputs) + ' '
        f'-filter_complex "{filter_graph}" '
        f'-fps_mode cfr -r {FPS} '
        '-c:v libx264 -preset veryfast -profile:v high -tune zerolatency '
        f'-x264-params keyint={GOP}:min-keyint={GOP}:scenecut=0 '
        f'-g {GOP} -keyint_min {GOP} -sc_threshold 0 '
        f'-b:v {VBPS} -maxrate {MAXRATE} -bufsize {BUFSIZE} '
        '-c:a aac -b:a 128k -ar 44100 -ac 2 '
        '-colorspace bt709 -color_primaries bt709 -color_trc bt709 '
        f'-map "[vout]" -map {audio_input_index}:a:0 '
        '-flush_packets 1 -muxpreload 0 -muxdelay 0 '
        '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
        + out_mux()
    )

def cmd_from_fallback():
    base_chain = (
        f'scale=1280:720:force_original_aspect_ratio=increase:in_range=full:out_range=tv,'
        f'crop=1280:720,fps={FPS},setsar=1'
    )
    filter_graph = build_filter_graph(base_chain, include_label=False, include_watermark=False)
    return (
        'ffmpeg '
        '-hide_banner -loglevel error -strict -1 '
        f'-stream_loop -1 -re -i "{FALLBACK_MP4}" '
        '-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 '
        f'-filter_complex "{filter_graph}" '
        f'-fps_mode cfr -r {FPS} '
        f'-c:v libx264 -preset veryfast -profile:v high -tune zerolatency '
        f'-x264-params keyint={GOP}:min-keyint={GOP}:scenecut=0 '
        f'-g {GOP} -keyint_min {GOP} -sc_threshold 0 '
        f'-b:v {VBPS} -maxrate {MAXRATE} -bufsize {BUFSIZE} '
        '-c:a aac -b:a 128k -ar 44100 -ac 2 '
        '-colorspace bt709 -color_primaries bt709 -color_trc bt709 '
        '-map "[vout]" -map 1:a:0 '
        '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
        + out_mux()
    )

def start_camera_stream(rtsp_url):
    log("startar ffmpeg (kamera)")
    return popen(cmd_from_rtsp(rtsp_url), inherit=False)

def start_fallback_stream():
    log("startar ffmpeg (fallback)")
    return popen(cmd_from_fallback(), inherit=False)

def ffmpeg_output_has_error(proc):
    if proc is None or proc.poll() is not None:
        return False
    try:
        rlist, _, _ = select.select([proc.stdout], [], [], 0)
    except Exception:
        return False
    if proc.stdout in rlist:
        line = proc.stdout.readline()
        if line:
            line = line.strip()
            log(line)
            for pat in FFMPEG_RECOVERABLE_PATTERNS:
                if pat in line:
                    return "recoverable"
            for pat in FFMPEG_FATAL_PATTERNS:
                if pat in line:
                    return "fatal"
    return None

# ----- YouTube HLS healthcheck (playlist-förändring) -----
_cached_hls = None
_last_seg = None

def get_youtube_live_hls(channel_id):
    global _cached_hls
    if _cached_hls:
        return _cached_hls
    try:
        r = subprocess.run(
            ["yt-dlp", "--socket-timeout", "10", "--retries", "1", "-g",
             f"https://www.youtube.com/channel/{channel_id}/live"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=25,
        )
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    urls = (r.stdout or "").strip().splitlines()
    for u in urls:
        if ".m3u8" in u:
            _cached_hls = u
            return u
    return None

def hls_last_segment_id(hls_url):
    if not hls_url:
        return None
    r = run(f'curl -L --silent --max-time 10 {shlex.quote(hls_url)}')
    text = r.stdout or ""
    if "#EXTM3U" not in text:
        return None
    last = None
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            last = line
    return last

# ========= HUVUDLOOP =========
def main():
    global _last_seg, _cached_hls

    log(f"konfigfil: {CONFIG_FILE} ({'hittad' if CONFIG_FILE.exists() else 'saknas'})")
    for note in _CONFIG_GUARDRAIL_NOTES:
        log(f"konfig-guardrail: {note}")

    missing = validate_required_config()
    if missing:
        log("FEL: obligatoriska konfigvärden saknas eller är placeholders:")
        for key in missing:
            log(f" - {key}")
        log("Uppdatera webcam-supervisor.conf och starta om tjänsten.")
        return 1

    if not os.path.exists(FALLBACK_MP4):
        log(f"FEL: fallback saknas: {FALLBACK_MP4}")
        return 1

    log("kontrollerar YouTube-broadcast via API")
    ensure_youtube_live()

    mode = "fallback"   # "fallback" | "camera"
    ff   = start_fallback_stream()
    current_rtsp = None
    fallback_started_at = time.time()
    fallback_retry_at = 0
    fallback_retry_delay = YT_INGEST_RETRY_INITIAL

    last_yt_check = 0
    yt_stall_count = 0
    yt_probe_fail_count = 0
    yt_probe_fail_camera_restarts = 0
    last_restart_time = 0
    recoverable_restart_times = []
    yt_stall_camera_restarts = 0
    fallback_hold_until = 0
    awaiting_yt_recovery = False
    yt_recovery_wait_started = 0
    last_recovery_check = 0
    yt_recovery_wait_last_log = 0
    camera_death_restart_times = []
    camera_started_at = 0
    last_camera_probe = 0
    camera_probe_fail_count = 0

    def go_to_fallback(require_recovery):
        nonlocal ff, mode, current_rtsp, yt_stall_count, yt_probe_fail_count, last_restart_time
        nonlocal recoverable_restart_times, fallback_hold_until
        nonlocal awaiting_yt_recovery, yt_recovery_wait_started, last_recovery_check
        nonlocal fallback_started_at, fallback_retry_at, fallback_retry_delay
        nonlocal yt_recovery_wait_last_log
        nonlocal yt_stall_camera_restarts, yt_probe_fail_camera_restarts
        nonlocal camera_death_restart_times, camera_started_at
        global _cached_hls, _last_seg

        kill_tree(ff)
        if require_recovery:
            log("kontrollerar om YouTube-broadcast behöver återskapas")
            ensure_youtube_live()
        now = time.time()
        ff = None
        fallback_started_at = 0
        mode = "fallback"
        current_rtsp = None
        camera_started_at = 0
        yt_stall_count = 0
        yt_probe_fail_count = 0
        yt_stall_camera_restarts = 0
        yt_probe_fail_camera_restarts = 0
        camera_death_restart_times = []
        recoverable_restart_times = []
        last_restart_time = now
        _cached_hls = None
        _last_seg = None
        if require_recovery:
            awaiting_yt_recovery = True
            yt_recovery_wait_started = now
            fallback_hold_until = 0
            fallback_retry_at = now + fallback_retry_delay
            log(f"stoppar all YouTube-trafik i {fallback_retry_delay}s för ingest-reset")
            fallback_retry_delay = min(fallback_retry_delay * 2, YT_INGEST_RETRY_MAX)
        else:
            awaiting_yt_recovery = False
            yt_recovery_wait_started = 0
            fallback_hold_until = 0
            fallback_retry_at = now
        last_recovery_check = 0
        yt_recovery_wait_last_log = 0

    while True:
        try:
            now = time.time()
            if mode == "fallback" and ff is not None and ff.poll() is not None:
                exit_code = ff.returncode
                ff = None
                fallback_retry_at = now + fallback_retry_delay
                log(
                    f"fallback-processen dog (exit={exit_code}); "
                    f"tyst YouTube-reset i {fallback_retry_delay}s"
                )
                fallback_retry_delay = min(
                    fallback_retry_delay * 2, YT_INGEST_RETRY_MAX
                )
                continue

            if mode == "fallback" and ff is None:
                if now < fallback_retry_at:
                    time.sleep(min(SCAN_INTERVAL, fallback_retry_at - now))
                    continue
                log("tyst YouTube-reset klar; startar fallback-ingest")
                ff = start_fallback_stream()
                fallback_started_at = now
                fallback_retry_at = 0
                if awaiting_yt_recovery:
                    fallback_hold_until = now + YT_FALLBACK_MIN_SECONDS
                time.sleep(SCAN_INTERVAL)
                continue
            err_kind = ffmpeg_output_has_error(ff)
            if err_kind:
                if mode == "fallback":
                    log("fallback tappade YouTube-ingest -> tyst reset")
                    go_to_fallback(require_recovery=True)
                    time.sleep(SCAN_INTERVAL)
                    continue

                if mode == "camera":
                    log("YouTube-ingest tappades -> tyst reset innan återanslutning")
                    go_to_fallback(require_recovery=True)
                    time.sleep(SCAN_INTERVAL)
                    continue


            if mode == "camera":
                if ff.poll() is not None:
                    log("kameraprocess dog")
                    kill_tree(ff)
                    now = time.time()
                    camera_death_restart_times = [
                        t for t in camera_death_restart_times
                        if now - t < CAMERA_DEATH_RESTART_WINDOW
                    ]
                    if current_rtsp and ffprobe_has_video(current_rtsp):
                        if len(camera_death_restart_times) >= CAMERA_DEATH_RESTART_LIMIT:
                            log("kameraprocess dog upprepade gånger -> OMEDELBAR FALLBACK")
                            go_to_fallback(require_recovery=True)
                            time.sleep(SCAN_INTERVAL)
                            continue

                        camera_death_restart_times.append(now)
                        log("kameran svarar, försöker kamera-restart utan fallback")
                        ff = start_camera_stream(current_rtsp)
                        camera_started_at = time.time()
                        last_restart_time = time.time()
                        yt_stall_count = 0
                        yt_probe_fail_count = 0
                        yt_stall_camera_restarts = 0
                        yt_probe_fail_camera_restarts = 0
                        _cached_hls = None
                        _last_seg = None
                        time.sleep(PING_INTERVAL)
                        continue

                    log("kameraprocess dog -> OMEDELBAR FALLBACK")
                    go_to_fallback(require_recovery=True)
                    time.sleep(SCAN_INTERVAL)
                    continue

                now = time.time()
                if now - last_camera_probe >= CAMERA_PROBE_EVERY:
                    last_camera_probe = now
                    if not ffprobe_has_video(current_rtsp):
                        camera_probe_fail_count += 1
                        log(
                            f"kamera-probe misslyckades "
                            f"(#{camera_probe_fail_count}/{CAMERA_PROBE_FAIL_GRACE})"
                        )
                        if camera_probe_fail_count >= CAMERA_PROBE_FAIL_GRACE:
                            log("kamera-probe misslyckades upprepade gånger -> fallback")
                            go_to_fallback(require_recovery=False)
                            time.sleep(SCAN_INTERVAL)
                            continue
                    else:
                        camera_probe_fail_count = 0
                if (
                    PROACTIVE_CAMERA_RESTART_EVERY > 0
                    and camera_started_at > 0
                    and (now - camera_started_at) >= PROACTIVE_CAMERA_RESTART_EVERY
                    and (now - last_restart_time) >= PROACTIVE_CAMERA_RESTART_MIN_UPTIME
                ):
                    mins = int(PROACTIVE_CAMERA_RESTART_EVERY // 60)
                    log(f"proaktiv kamera-restart efter {mins} min för att förebygga HLS-stopp")
                    kill_tree(ff)
                    ff = start_camera_stream(current_rtsp)
                    camera_started_at = time.time()
                    last_restart_time = camera_started_at
                    yt_stall_count = 0
                    yt_probe_fail_count = 0
                    yt_stall_camera_restarts = 0
                    yt_probe_fail_camera_restarts = 0
                    _cached_hls = None
                    _last_seg = None
                    time.sleep(PING_INTERVAL)
                    continue

                if ENABLE_YT_HEALTHCHECK and (now - last_restart_time) >= YT_POST_RESTART_COOLDOWN:
                    if now - last_yt_check >= YT_HEALTHCHECK_EVERY:
                        last_yt_check = now
                        try:
                            hls = get_youtube_live_hls(YT_CHANNEL_ID)
                            seg = hls_last_segment_id(hls)
                            if not seg:
                                yt_probe_fail_count += 1
                                _cached_hls = None
                                log(f"YouTube HLS kunde inte läsas (#{yt_probe_fail_count}), hoppar över stall-bedömning")
                                if yt_probe_fail_count >= YT_PROBE_FAIL_GRACE:
                                    # Missing HLS is unknown health, not failed ingest.
                                    yt_probe_fail_count = 0
                                    yt_stall_count = 0
                                    _last_seg = None
                                    log("YouTube HLS-kontrollen är otillgänglig; "
                                        "behåller sändningen och fortsätter kamera-/ffmpeg-övervakning")
                                time.sleep(PING_INTERVAL)
                                continue

                            yt_probe_fail_count = 0
                            yt_probe_fail_camera_restarts = 0
                            if _last_seg is None:
                                _last_seg = seg
                                yt_stall_count = 0
                                yt_stall_camera_restarts = 0
                                log("YouTube HLS baseline satt")
                            elif seg != _last_seg:
                                _last_seg = seg
                                yt_stall_count = 0
                                yt_stall_camera_restarts = 0
                                log("YouTube HLS rör sig (ok)")
                            else:
                                yt_stall_count += 1
                                log(f"YouTube HLS verkar stannat (#{yt_stall_count})")
                                if yt_stall_count >= YT_STALL_GRACE:
                                    if yt_stall_camera_restarts < YT_STALL_CAMERA_RECOVERIES:
                                        attempt = yt_stall_camera_restarts + 1
                                        log(f"HLS stannat flera gånger → kamera-restart {attempt}/{YT_STALL_CAMERA_RECOVERIES}")
                                        yt_stall_camera_restarts = attempt
                                        kill_tree(ff)
                                        ff = start_camera_stream(current_rtsp)
                                        camera_started_at = time.time()
                                        last_restart_time = time.time()
                                        yt_stall_count = 0
                                        yt_probe_fail_count = 0
                                        yt_probe_fail_camera_restarts = 0
                                        _cached_hls = None
                                        _last_seg = None
                                        time.sleep(PING_INTERVAL)
                                        continue

                                    log("HLS stannat flera gånger → kort fallback, låt skannern hitta kameran")
                                    # Låt fallback-loopens MAC-skanning ta över, det är robustare
                                    go_to_fallback(require_recovery=True)
                                    time.sleep(30)  # liten “cooldown” så YT hinner rensa buffert/ghost
                                    continue
                        except Exception as e:
                            log(f"YT-healthcheck exception: {e}")

                time.sleep(PING_INTERVAL)

            else:
                now = time.time()
                if (ff is not None and ff.poll() is None and
                        now - fallback_started_at >= YT_INGEST_RETRY_STABLE and
                        fallback_retry_delay != YT_INGEST_RETRY_INITIAL):
                    log("YouTube-ingest är stabil igen; återställer retry-backoff")
                    fallback_retry_delay = YT_INGEST_RETRY_INITIAL
                    fallback_retry_at = 0

                if awaiting_yt_recovery:
                    if (YT_RECOVERY_MAX_WAIT > 0 and
                            yt_recovery_wait_started and
                            (now - yt_recovery_wait_started) >= YT_RECOVERY_MAX_WAIT):
                        log("YouTube recovery-timeout nådd -> restartar fallback och fortsätter automatiskt")
                        kill_tree(ff)
                        ff = start_fallback_stream()
                        fallback_started_at = time.time()
                        last_restart_time = time.time()
                        awaiting_yt_recovery = False
                        yt_recovery_wait_started = 0
                        yt_recovery_wait_last_log = 0
                        fallback_hold_until = 0
                        last_recovery_check = 0
                        _cached_hls = None
                        _last_seg = None
                        time.sleep(SCAN_INTERVAL)
                        continue

                    if now < fallback_hold_until:
                        time.sleep(SCAN_INTERVAL)
                        continue
                    log("fallback-minimitid klar; återgår utan att kräva publikt HLS")
                    awaiting_yt_recovery = False
                    yt_recovery_wait_started = 0
                    yt_recovery_wait_last_log = 0

                found, url = find_camera_by_mac(TARGET_MAC)
                if found and url:
                    log("kamera uppe -> byter till RTSP")
                    kill_tree(ff)
                    current_rtsp = url
                    ff = start_camera_stream(url)
                    mode = "camera"
                    camera_started_at = time.time()
                    _cached_hls = None
                    _last_seg = None
                    yt_stall_camera_restarts = 0
                    yt_probe_fail_camera_restarts = 0
                    yt_probe_fail_count = 0
                    awaiting_yt_recovery = False
                    yt_recovery_wait_started = 0
                    fallback_hold_until = 0
                    last_recovery_check = 0
                    yt_recovery_wait_last_log = 0
                    camera_death_restart_times = []
                    last_restart_time = time.time()
                    time.sleep(PING_INTERVAL)
                    continue

                time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"exception: {e}")
            time.sleep(2)

    kill_tree(ff)
    return 0

if __name__ == "__main__":
    log("supervisor startar …")
    raise SystemExit(main())
