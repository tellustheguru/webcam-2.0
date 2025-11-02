#!/usr/bin/env python3
import json, os, shlex, signal, socket, subprocess, time, select
from ipaddress import ip_network, ip_address

# ========== KONFIG ==========
RTSP_USER = "[Din användare]"
RTSP_PASS = "[Ditt lösenord]"

YT_KEY     = "[Din YouTube-nyckel]"
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
SCAN_INTERVAL = 2    # s mellan sök i fallback-läge
PING_INTERVAL = 2    # s mellan “lever kameran?” i kamera-läge
USE_BACKUP    = True # sänd även till yt-backup

# Snabbupptäckten via MAC (din kamera)
TARGET_MAC = "[Din MAC-adress]".lower()

# Generisk fallback-CIDR när vi inte kan läsa rätt interface
STATIC_CIDR = "[Din fallback CIDR]/24"

# mönster vi vet betyder "YT/RTMPS har glappat"
FFMPEG_OUT_ERROR_PATTERNS = (
    "Slave muxer #0 failed",
    "Slave muxer #1 failed",
    "All tee outputs failed",
    "Broken pipe",
    "IO error: End of file",
    "The specified session has been invalidated",
)

# ========== HJÄLPARE ==========
def log(msg):
    print(f"[webcam-2.0] {msg}", flush=True)

def run(cmd):
    return subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)

def popen(cmd, inherit=False):
    # vi vill kunna läsa ffmpeg-output → inherit=False
    if inherit:
        return subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)
    return subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        preexec_fn=os.setsid
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
    # Kort hård timeout via GNU timeout (ffprobe saknar -stimeout)
    cmd = (
        f'timeout -k 2 3 '
        f'ffprobe -v error -rtsp_transport tcp '
        f'-select_streams v -show_streams -of json {shlex.quote(rtsp_url)}'
    )
    r = run(cmd)
    output = (r.stdout or "") + (r.stderr or "")
    if '"codec_type":"video"' in output or '"codec_type": "video"' in output:
        return True
    try:
        data = json.loads(r.stdout or "{}")
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                return True
    except Exception:
        pass
    return False

def default_cidr():
    # 1) via default-route
    r = run("ip -j route show default")
    try:
        routes = json.loads(r.stdout)
        if routes and "dev" in routes[0]:
            dev = routes[0]["dev"]
            r2 = run(f"ip -j -4 addr show dev {shlex.quote(dev)}")
            js = json.loads(r2.stdout)
            for a in js[0].get("addr_info", []):
                if a.get("family") == "inet":
                    return f"{a['local']}/{a['prefixlen']}"
    except Exception:
        pass
    # 2) första icke-loopback med IPv4
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
    # 3) fallback
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
        rows = json.loads(r.stdout or "[]")
        for row in rows:
            ip = row.get("dst")
            mac = (row.get("lladdr") or "").lower()
            if ip and mac:
                out[ip] = mac
    except Exception:
        pass
    return out

def ping_sweep(net):
    # tyst ping-svep för att fylla ARP snabbt
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
    """Returnerar (True, rtsp_url) eller (False, None)"""
    cidr = default_cidr() or STATIC_CIDR
    net = normalize_net(cidr)
    log(f"söker kamera i {net.network_address}/{net.prefixlen} …")

    # 1) MAC-träff (snabbast)
    ip = find_ip_by_mac(target_mac, net) if target_mac else None
    if ip:
        log(f"MAC-träff: {ip} ({target_mac}) – provar RTSP")
        for url in make_rtsp_urls(ip):
            log(f"provar {url}")
            if ffprobe_has_video(url):
                log(f"hittade kamera (MAC match): {ip} via {url}")
                return True, url

    # 2) ARP-IP:er utan portfilter
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

    # 3) Port 554-kandidater i nätet
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

def cmd_from_rtsp(rtsp):
    # 16:9 till YouTube, med färgrymd
    vf = (
        f'scale=1280:720:force_original_aspect_ratio=decrease:in_range=full:out_range=tv,'
        f'pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps={FPS},setsar=1,format=yuv420p'
    )

    return (
        'ffmpeg '
        '-hide_banner -loglevel error -strict -1 '
        # stabilare timestamps
        '-fflags nobuffer -fflags +genpts '
        '-use_wallclock_as_timestamps 1 '
        # RTSP över TCP, så vi slipper UDP-trassel på LTE
        '-rtsp_transport tcp -rtsp_flags prefer_tcp '
        # större queue och längre analys så den inte ger upp direkt
        '-thread_queue_size 1024 -probesize 512k -analyzeduration 10M '
        # större inputbuffer för att klara jitter
        '-rtbufsize 256M '
        # själva kameran
        f'-i "{rtsp}" '
        # fejkljud så YT alltid får audio
        '-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 '
        # video-pipeline
        f'-filter:v "{vf}" '
        f'-fps_mode cfr -r {FPS} '
        '-c:v libx264 -preset veryfast -profile:v high -tune zerolatency '
        f'-g {GOP} -keyint_min {GOP} -sc_threshold 0 '
        f'-b:v {VBPS} -maxrate {MAXRATE} -bufsize {BUFSIZE} '
        # audio
        '-c:a aac -b:a 128k -ar 44100 -ac 2 '
        # färginfo till YT
        '-colorspace bt709 -color_primaries bt709 -color_trc bt709 '
        # mappa video från kameran + ljud från anullsrc
        '-map 0:v:0 -map 1:a:0 '
        # lite snäll muxning
        '-flush_packets 1 -muxpreload 0 -muxdelay 0 '
        # ut till YT (prim+backup)
        + out_mux()
    )

def cmd_from_fallback():
    vf = (
        f'scale=1280:720:force_original_aspect_ratio=increase:in_range=full:out_range=tv,'
        f'crop=1280:720,fps={FPS},setsar=1,format=yuv420p'
    )
    return (
        'ffmpeg '
        '-hide_banner -loglevel error -strict -1 '
        f'-stream_loop -1 -re -i "{FALLBACK_MP4}" '
        '-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 '
        f'-filter:v "{vf}" '
        f'-fps_mode cfr -r {FPS} '
        f'-c:v libx264 -preset veryfast -profile:v high -tune zerolatency '
        f'-g {GOP} -keyint_min {GOP} -sc_threshold 0 '
        f'-b:v {VBPS} -maxrate {MAXRATE} -bufsize {BUFSIZE} '
        '-c:a aac -b:a 128k -ar 44100 -ac 2 '
        '-colorspace bt709 -color_primaries bt709 -color_trc bt709 '
        '-map 0:v:0 -map 1:a:0 '
        + out_mux()
    )

def start_camera_stream(rtsp_url):
    log("startar ffmpeg (kamera)")
    # capture output så vi kan reagera på RTMPS-fel
    return popen(cmd_from_rtsp(rtsp_url), inherit=False)

def start_fallback_stream():
    log("startar ffmpeg (fallback)")
    # capture output så vi kan reagera även här
    return popen(cmd_from_fallback(), inherit=False)

def ffmpeg_output_has_error(proc):
    """Kollar om ffmpeg har skrivit något av de kända RTMP/tee-felen."""
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
            # skriv ut ändå så man ser det i journalctl
            log(line)
            for pat in FFMPEG_OUT_ERROR_PATTERNS:
                if pat in line:
                    return True
    return False

# ========== HUVUDLOOP ==========
def main():
    if not os.path.exists(FALLBACK_MP4):
        log(f"FEL: fallback saknas: {FALLBACK_MP4}")
        return 1

    mode = "fallback"   # "fallback" | "camera"
    ff   = start_fallback_stream()
    current_rtsp = None

    while True:
        try:
            # gemensamt: om ffmpeg börjar spotta RTMP-fel -> direkt fallback
            if ffmpeg_output_has_error(ff):
                log("ffmpeg rapporterade RTMP/tee-fel -> OMEDELBAR FALLBACK")
                kill_tree(ff)
                ff = start_fallback_stream()
                mode = "fallback"
                time.sleep(SCAN_INTERVAL)
                continue

            if mode == "camera":
                # 1) dog processen? -> omedelbar fallback
                if ff.poll() is not None:
                    log("kameraprocess dog -> OMEDELBAR FALLBACK")
                    kill_tree(ff)
                    ff = start_fallback_stream()
                    mode = "fallback"
                    time.sleep(SCAN_INTERVAL)
                    continue

                # 2) lever RTSP-källan?
                if not ffprobe_has_video(current_rtsp):
                    log("kamera-probe misslyckades -> OMEDELBAR FALLBACK")
                    kill_tree(ff)
                    ff = start_fallback_stream()
                    mode = "fallback"
                    time.sleep(SCAN_INTERVAL)
                    continue

                time.sleep(PING_INTERVAL)

            else:
                # fallback-läge: leta kamera
                found, url = find_camera_by_mac(TARGET_MAC)
                if found and url:
                    log("kamera uppe -> byter till RTSP")
                    kill_tree(ff)
                    current_rtsp = url
                    ff = start_camera_stream(url)
                    mode = "camera"
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
