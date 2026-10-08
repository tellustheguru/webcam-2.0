#!/usr/bin/env python3
from datetime import datetime, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


BASE_DIR = Path(__file__).resolve().parent
TOKEN_FILE = BASE_DIR / "youtube-oauth-token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube"]


def _credentials():
    credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
        TOKEN_FILE.chmod(0o600)
    return credentials


def _youtube():
    return build(
        "youtube",
        "v3",
        credentials=_credentials(),
        cache_discovery=False,
    )


def _broadcasts(youtube):
    items = []
    page_token = None
    while True:
        params = dict(part="id,snippet,status,contentDetails", mine=True,
                      broadcastType="all", maxResults=50)
        if page_token:
            params["pageToken"] = page_token
        response = youtube.liveBroadcasts().list(**params).execute()
        items.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return items


def _streams(youtube):
    return youtube.liveStreams().list(
        part="id,snippet,status",
        mine=True,
        maxResults=50,
    ).execute().get("items", [])


def ensure_youtube_broadcast(
    channel_id,
    stream_title="Webcam 2.0",
    broadcast_title="Gördalens webbkamera LIVE",
    logger=print,
):
    """Ensure that a public, bound broadcast exists for the reusable stream."""
    youtube = _youtube()

    channels = youtube.channels().list(part="id", mine=True).execute().get("items", [])
    if not channels or channels[0]["id"] != channel_id:
        raise RuntimeError("OAuth-token hör inte till den konfigurerade YouTube-kanalen")

    streams = _streams(youtube)
    stream = next(
        (item for item in streams if item.get("snippet", {}).get("title") == stream_title),
        None,
    )
    if stream is None:
        raise RuntimeError(f"YouTube-streamen {stream_title!r} hittades inte")

    broadcasts = _broadcasts(youtube)
    unfinished = [item for item in broadcasts
                  if item.get("status", {}).get("lifeCycleStatus") != "complete"]
    # Delete only completed archives created for this exact webcam broadcast
    # and bound to this exact reusable stream. Never touch other videos.
    for item in broadcasts:
        if (
            item.get("status", {}).get("lifeCycleStatus") == "complete"
            and item.get("snippet", {}).get("title") == broadcast_title
            and item.get("contentDetails", {}).get("boundStreamId") == stream["id"]
        ):
            broadcast_id = item["id"]
            youtube.liveBroadcasts().delete(id=broadcast_id).execute()
            logger(f"YouTube API: raderade avslutat webbkameraarkiv {broadcast_id}")

    live_states = {"live", "liveStarting", "testing", "testStarting"}
    for item in unfinished:
        if (item.get("contentDetails", {}).get("boundStreamId") == stream["id"]
                and item.get("status", {}).get("lifeCycleStatus") in live_states):
            logger(f"YouTube API: webbkamera-broadcast {item['id']} är live")
            return item["id"], False

    for item in unfinished:
        state = item.get("status", {}).get("lifeCycleStatus")
        bound = item.get("contentDetails", {}).get("boundStreamId")
        if bound == stream["id"] and state in {"created", "ready"}:
            logger(f"YouTube API: väntande broadcast {item['id']} är redan bunden")
            return item["id"], False

    body = {
        "snippet": {
            "title": broadcast_title,
            "description": "Direktsänd webbkamera från Gördalen.",
            "scheduledStartTime": datetime.now(timezone.utc).isoformat(),
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
        "contentDetails": {
            "enableAutoStart": True,
            "enableAutoStop": False,
            "enableEmbed": True,
            "enableDvr": False,
            "recordFromStart": False,
            "monitorStream": {"enableMonitorStream": False},
        },
    }
    try:
        broadcast = youtube.liveBroadcasts().insert(
            part="snippet,status,contentDetails", body=body
        ).execute()
    except HttpError as exc:
        error_text = str(exc)
        if exc.resp.status != 403 or not any(
            marker in error_text for marker in ("disableRecordingNotAllowed", "recordFromStart", "modificationNotAllowed")
        ):
            raise
        logger("YouTube tillåter inte avstängd inspelning; arkivet raderas efter avslut")
        body["contentDetails"]["recordFromStart"] = True
        broadcast = youtube.liveBroadcasts().insert(
            part="snippet,status,contentDetails", body=body
        ).execute()
    youtube.liveBroadcasts().bind(
        part="id,contentDetails",
        id=broadcast["id"],
        streamId=stream["id"],
    ).execute()
    logger(
        f"YouTube API: skapade och band publik broadcast {broadcast['id']} "
        f"till {stream_title}"
    )
    return broadcast["id"], True
