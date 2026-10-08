#!/usr/bin/env python3
"""Ensure the webcam broadcast, remove completed archives, and publish via Joomla com_ajax."""
import http.client
import json
import socket
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, '/opt/webcam-2.0')
from youtube_live_manager import _youtube, ensure_youtube_broadcast

CONFIG = Path(__file__).with_name('publisher.json')

def find_broadcast(youtube, channel_id, stream_title):
    channels = youtube.channels().list(part='id', mine=True).execute().get('items', [])
    if not any(c['id'] == channel_id for c in channels):
        raise RuntimeError('Wrong YouTube channel; preserving published status')
    streams = youtube.liveStreams().list(part='id,snippet', mine=True, maxResults=50).execute().get('items', [])
    stream_ids = {s['id'] for s in streams if s['snippet']['title'] == stream_title}
    if not stream_ids:
        raise RuntimeError('Webcam stream missing; preserving published status')
    broadcasts = youtube.liveBroadcasts().list(part='id,status,contentDetails', broadcastStatus='active', maxResults=50).execute().get('items', [])
    live = [b for b in broadcasts if b['contentDetails'].get('boundStreamId') in stream_ids
            and b['status'].get('lifeCycleStatus') == 'live' and b['status'].get('privacyStatus') == 'public']
    if len(live) > 1:
        raise RuntimeError('Multiple webcam broadcasts; preserving published status')
    return live[0]['id'] if live else None

def publish(config, payload):
    url = urlsplit(config['endpoint'])
    if url.scheme != 'https':
        raise ValueError('Publisher endpoint must use HTTPS')
    conn = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=15, context=ssl.create_default_context())
    # Optional private routing retains certificate validation and the public SNI.
    if config.get('connect_ip'):
        def connect(address, timeout, source_address=None):
            return socket.create_connection((config['connect_ip'], address[1]), timeout, source_address)
        conn._create_connection = connect
    try:
        conn.request('POST', url.path + ('?' + url.query if url.query else ''), body=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'X-Gordalen-Key': config['publish_key'],
            'User-Agent': 'GordalenLivePublisher/2.0'})
        response = conn.getresponse()
        body = response.read(16384)
        if response.status != 200:
            raise RuntimeError(f'Joomla publication failed: HTTP {response.status}')
        result = json.loads(body)
        if not result.get('success') or not isinstance(result.get('data'), list) or not result['data']:
            raise RuntimeError('Joomla rejected status publication')
        if result['data'][0].get('video_id') != payload['video_id']:
            raise RuntimeError('Joomla did not acknowledge the published broadcast')
    finally:
        conn.close()

def main():
    config = json.loads(CONFIG.read_text())
    broadcast_id, _ = ensure_youtube_broadcast(
        channel_id=config['channel_id'], stream_title=config['stream_title'])
    result = _youtube().liveBroadcasts().list(part='id,status', id=broadcast_id).execute().get('items', [])
    video_id = next((b['id'] for b in result if b['status'].get('lifeCycleStatus') == 'live'
                     and b['status'].get('privacyStatus') == 'public'), None)
    payload = {'channel_id': config['channel_id'], 'video_id': video_id, 'checked_at': datetime.now(timezone.utc).isoformat()}
    publish(config, payload)
    print('Published webcam broadcast:', video_id or 'not live')

if __name__ == '__main__':
    main()
