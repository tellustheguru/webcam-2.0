#!/usr/bin/env python3
import json, os, shlex, signal, socket, subprocess, time, select
from ipaddress import ip_network, ip_address

# ========= KONFIG =========
RTSP_USER = "<ANVÄNDARE>"
RTSP_PASS = "<LÖSENORD>"

YT_KEY     = "<YOUTUBE-STREAM-KEY>"
YT_PRIMARY = f"rtmps://a.rtmp.youtube.com/live2/{YT_KEY}"
YT_BACKUP  = f"rtmps://b.rtmp.youtube.com/live2?backup=1/{YT_KEY}"

FALLBACK_MP4 = "/opt/webcam-2.0/fallback.mp4"

# Video
FPS = 15
GOP = FPS * 2
VBPS = "1800k"
MAXRATE = "2000k"
BUFSIZE = "3500k"

# Övervakning
SCAN_INTERVAL = 2     # s mellan sök i fallback-läge
PING_INTERVAL = 2     # s mellan “lever kameran?” i kamera-läge

# ❗ Skicka endast till primär YouTube-URL (minskar varningar & “ghost”-sessioner)
USE_BACKUP = False

# HLS-healthcheck (YouTube)
ENABLE_YT_HEALTHCHECK = True
YT_CHANNEL_ID         = "<YOUTUBE-CHANNEL-ID>"
YT_HEALTHCHECK_EVERY  = 120
YT_STALL_GRACE        = 3
YT_POST_RESTART_COOLDOWN = 240  # lite längre cooldown så vi inte loopsnurrar
YT_STALL_CAMERA_RECOVERIES = 2  # snabba kamera-restarts innan vi går till fallback
YT_FALLBACK_MIN_SECONDS    = 120  # håll fallback ett tag så YouTube hinner vakna
YT_RECOVERY_CHECK_INTERVAL = 15   # hur ofta vi kollar HLS under fallback innan kamera

# Label-overlay
LABEL_TEXT = "<VALFRI-TEXT>"
LABEL_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
LABEL_FONT_SIZE = 30
LABEL_TEXT_COLOR = "0x0F2C5C" # Valfri hex-färg
LABEL_OFFSET = 5
LABEL_PADDING = 4
LABEL_BG_ALPHA = 0.6

# Watermark (kamera-läget)
WATERMARK_ENABLED = True
WATERMARK_PATH = "/opt/webcam-2.0/gordalen_nu_logo.png"
WATERMARK_MAX_SIZE = 300   # max-bredd/höjd i px
WATERMARK_MARGIN = 14      # px från höger/underkant

# Kamera-restart vid upprepade ffmpeg-dödsfall
CAMERA_DEATH_RESTART_LIMIT = 4
CAMERA_DEATH_RESTART_WINDOW = 90

# Snabb MAC-upptäckt
TARGET_MAC = "<MAC-ADDRESS>".lower()

# Fallback-CIDR
STATIC_CIDR = "192.168.0.0/24"

# Mönster för RTMPS-/tee-fel
FFMPEG_RECOVERABLE_PATTERNS = (
    "Error in the push function",
    "Broken pipe",
    "IO error: End of file",
    "The specified session has been invalidated",
)

FFMPEG_FATAL_PATTERNS = (
    "Slave muxer #0 failed",
    "Slave muxer #1 failed",
    "All tee outputs failed",
)

RECOVERABLE_RESTART_LIMIT = 4
RECOVERABLE_RESTART_WINDOW = 600

# ========= HJÄLPARE =========
def log(msg):
    print(f"[gordalen] {msg}", flush=True)

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

def find_camera_by_mac(target_mac):
    cidr = default_cidr() or STATIC_CIDR
    net = normalize_net(cidr)
    log(f"söker kamera i {net.network_address}/{net.prefixlen} …")

    ip = find_ip_by_mac(target_mac, net) if target_mac else None
    if ip:
        log(f"MAC-träff: {ip} ({target_mac}) – provar RTSP")
        for url in make_rtsp_urls(ip):
            log(f"provar {url}")
            if ffprobe_has_video(url):
                log(f"hittade kamera (MAC match): {ip} via {url}")
                return True, url

    ping_sweep(net)
    table = arp_table()
    arp_ips = [i for i in table.keys() if ip_address(i) in net]
    if arp_ips:
        log(f"provar ARP-IP:er först: {arp_ips[:8]}{' …' if len(arp_ips)>8 else ''}")
        for ip in arp_ips:
            for url in make_rtsp_urls(ip):
                log(f"provar {url}")
                if ffprobe_has_video(url):
                    log(f"hittade kamera: {ip} via {url}")
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
                log(f"provar {url}")
                if ffprobe_has_video(url):
                    log(f"hittade kamera: {ip} via {url}")
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
    r = run(f'yt-dlp -g "https://www.youtube.com/channel/{channel_id}/live"')
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

    if not os.path.exists(FALLBACK_MP4):
        log(f"FEL: fallback saknas: {FALLBACK_MP4}")
        return 1

    mode = "fallback"   # "fallback" | "camera"
    ff   = start_fallback_stream()
    current_rtsp = None

    last_yt_check = 0
    yt_stall_count = 0
    last_restart_time = 0
    recoverable_restart_times = []
    yt_stall_camera_restarts = 0
    fallback_hold_until = 0
    awaiting_yt_recovery = False
    last_recovery_check = 0
    camera_death_restart_times = []

    def go_to_fallback(require_recovery):
        nonlocal ff, mode, current_rtsp, yt_stall_count, last_restart_time
        nonlocal recoverable_restart_times, fallback_hold_until
        nonlocal awaiting_yt_recovery, last_recovery_check
        nonlocal yt_stall_camera_restarts, camera_death_restart_times
        global _cached_hls, _last_seg

        kill_tree(ff)
        ff = start_fallback_stream()
        mode = "fallback"
        current_rtsp = None
        yt_stall_count = 0
        yt_stall_camera_restarts = 0
        camera_death_restart_times = []
        recoverable_restart_times = []
        last_restart_time = time.time()
        _cached_hls = None
        _last_seg = None
        if require_recovery:
            awaiting_yt_recovery = True
            fallback_hold_until = last_restart_time + YT_FALLBACK_MIN_SECONDS
        else:
            awaiting_yt_recovery = False
            fallback_hold_until = 0
        last_recovery_check = 0

    while True:
        try:
            err_kind = ffmpeg_output_has_error(ff)
            if err_kind:
                if (mode == "camera" and current_rtsp and
                        err_kind == "recoverable"):
                    now = time.time()
                    recoverable_restart_times = [
                        t for t in recoverable_restart_times
                        if now - t < RECOVERABLE_RESTART_WINDOW
                    ]
                    if len(recoverable_restart_times) >= RECOVERABLE_RESTART_LIMIT:
                        log("för många RTMP/TLS-fel nyligen -> OMEDELBAR FALLBACK")
                    else:
                        log("ffmpeg tappade RTMP-utgången, försöker kamera-restart utan fallback")
                        recoverable_restart_times.append(now)
                        kill_tree(ff)
                        ff = start_camera_stream(current_rtsp)
                        last_restart_time = now
                        yt_stall_count = 0
                        _cached_hls = None
                        _last_seg = None
                        time.sleep(PING_INTERVAL)
                        continue

                log("ffmpeg rapporterade RTMP/tee-fel -> OMEDELBAR FALLBACK")
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
                        last_restart_time = time.time()
                        yt_stall_count = 0
                        yt_stall_camera_restarts = 0
                        _cached_hls = None
                        _last_seg = None
                        time.sleep(PING_INTERVAL)
                        continue

                    log("kameraprocess dog -> OMEDELBAR FALLBACK")
                    go_to_fallback(require_recovery=True)
                    time.sleep(SCAN_INTERVAL)
                    continue

                if not ffprobe_has_video(current_rtsp):
                    log("kamera-probe misslyckades -> OMEDELBAR FALLBACK")
                    go_to_fallback(require_recovery=False)
                    time.sleep(SCAN_INTERVAL)
                    continue

                now = time.time()
                if ENABLE_YT_HEALTHCHECK and (now - last_restart_time) >= YT_POST_RESTART_COOLDOWN:
                    if now - last_yt_check >= YT_HEALTHCHECK_EVERY:
                        last_yt_check = now
                        try:
                            hls = get_youtube_live_hls(YT_CHANNEL_ID)
                            seg = hls_last_segment_id(hls)
                            if seg and seg != _last_seg:
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
                                        last_restart_time = time.time()
                                        yt_stall_count = 0
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
                if awaiting_yt_recovery:
                    now = time.time()
                    if now < fallback_hold_until:
                        time.sleep(SCAN_INTERVAL)
                        continue
                    if ENABLE_YT_HEALTHCHECK:
                        if now - last_recovery_check < YT_RECOVERY_CHECK_INTERVAL:
                            time.sleep(SCAN_INTERVAL)
                            continue
                        last_recovery_check = now
                        try:
                            hls = get_youtube_live_hls(YT_CHANNEL_ID)
                            seg = hls_last_segment_id(hls)
                            prev_seg = _last_seg
                            if seg and prev_seg and seg != prev_seg:
                                awaiting_yt_recovery = False
                                _last_seg = seg
                                log("YouTube HLS rör sig igen efter fallback")
                            else:
                                if seg and not prev_seg:
                                    _last_seg = seg
                                log("väntar på att YouTube HLS ska röra sig igen innan kamerabyte")
                                time.sleep(SCAN_INTERVAL)
                                continue
                        except Exception as e:
                            log(f"YT-recovery check exception: {e}")
                            time.sleep(SCAN_INTERVAL)
                            continue
                    else:
                        awaiting_yt_recovery = False

                found, url = find_camera_by_mac(TARGET_MAC)
                if found and url:
                    log("kamera uppe -> byter till RTSP")
                    kill_tree(ff)
                    current_rtsp = url
                    ff = start_camera_stream(url)
                    mode = "camera"
                    _cached_hls = None
                    _last_seg = None
                    yt_stall_camera_restarts = 0
                    awaiting_yt_recovery = False
                    fallback_hold_until = 0
                    last_recovery_check = 0
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
