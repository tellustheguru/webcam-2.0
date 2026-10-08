# Gordalen Live Player 2.0.0

A Joomla system plugin using native Joomla extension installation, namespaced dependency injection, com_ajax, Web Asset Manager, configurable plugin parameters and YOOtheme module/Builder extension APIs. No Joomla or YOOtheme core files are changed. No rendered HTML is rewritten. The native YOOtheme Video element retains its normal layout settings.

## Install/update
Install `plg_system_gordalenlive-2.0.0.zip` through Joomla's extension installer or its `extension:install --path` CLI command. Uploading later versions with the same extension ID updates the plugin while preserving settings. The installer removes the obsolete v1 player.js only from this plugin's own directory. Automatic update-server hosting is not configured; updates use normal Joomla package installation.

Configure the channel ID and publisher key in System > Plugins > Gordalen Live Player. Keep the status path empty for the extension-owned media location. The publisher key must contain at least 32 characters. The website exposes only channel/video IDs and timestamps, never this key or Google's OAuth credentials.

Use the standard YOOtheme Video element with `https://www.youtube.com/embed/live_stream?channel=CHANNEL_ID`. Width, height, alignment and styling remain editable in YOOtheme. Only the configured channel's video element is resolved. Playback goes to the live edge and checks for replacement broadcasts automatically.

The status endpoint is `index.php?option=com_ajax&plugin=gordalenlive&group=system&format=json`. GET is public. POST requires `X-Gordalen-Key` and validates the channel, timestamp and video ID. Writes are atomic. Google API credentials remain on the camera server.

## Publisher
`publish_youtube_live.py` runs from the existing camera systemd timer every minute. Its root-readable `publisher.json` config sets endpoint, channel_id, stream_title, publish_key and optionally connect_ip for private network routing. HTTPS certificate validation remains enabled. API/network failures retain the last successfully published state; an explicit no-live result contains null. The plugin deliberately preserves playback while waiting for the replacement stream.

## Uninstall
Uninstall via Joomla > System > Manage Extensions. Joomla removes the plugin, managed assets and registration. The installer removes its managed status file. It does not modify article layouts or delete a custom externally configured status path. On the camera server separately disable `gordalen-live-publish.timer` and remove its service/config if abandoning the integration. OAuth credentials and the webcam supervisor are independent.

## Migration from v1
`configure-migration.php` uses Joomla's Extension table API to set configuration, without direct SQL. `install-standard.sh` uses the official Joomla CLI installer as www-data. Existing article content is preserved; the YOOtheme Video element already contains the permanent channel URL. The former SSH key and status files are retired only after successful end-to-end verification. Legacy installer scripts are then archived outside the running website.

## Validation
Test status validation, replay rejection and atomic writes; native builder rendering with different video IDs and preserved 960x540 geometry; player start at live edge, drift recovery, replacement broadcasts and network failures. Verify official installation/update lifecycle and live endpoint/HTML after deployment. Actual browser autoplay still depends on browser consent/settings.

## Deployment audit (2026-10-07)

Validated on Joomla 5.4.9 and the installed YOOtheme Pro version. Official CLI installation and a second installation as an update both succeeded. The native article Video element remains at 960x540. Existing user-approved article content/settings are retained; the new plugin does not update content rows. Changes are confined to the custom plugin and its installer-managed media directory, plus the camera publisher service. No Joomla or YOOtheme core source files were edited.

Production tests confirmed authenticated com_ajax publication, rejection of invalid keys/channels and old timestamps, matching delivered versioned JavaScript, and automatic publisher service success. Isolated tests covered new broadcast IDs, live-edge recovery, layout preservation, and uninstall ownership boundaries. Uninstall was tested in isolation. The subsequent DVR migration exercised a real broadcast replacement and automatic Joomla status publication.

The hosting server has `opcache.validate_timestamps=0`. Therefore CLI deployments require explicit invalidation of changed plugin PHP files in the FPM pool (or a graceful FPM reload). CLI OPcache is distinct from FPM OPcache. Joomla cache cleaning alone is insufficient. This is a hosting deployment requirement, not a Joomla/YOOtheme core modification. Plugin parameters are cached in Joomla's `com_plugins` cache group; clean this group when applying configuration through maintenance scripts. Normal Joomla administrator plugin saves perform their own lifecycle operations.

Build reproducibly using `python3 build.py`. Install the generated ZIP through Joomla. Do not use retired v1 installer scripts or raw database edits. The one-time SSH installation key is revoked after verification; runtime publication uses HTTPS and does not depend on SSH.

## DVR and archive policy (2026-10-07)

New webcam broadcasts are created with `enableDvr=false`. Google rejects `recordFromStart=false` for this channel with `disableRecordingNotAllowed`, so recording remains enabled on YouTube. Every publisher cycle (approximately one minute) runs the broadcast manager, which deletes completed broadcasts only when both the exact webcam title and bound stream ID match. Other videos are preserved. API failures are retried on later cycles; deletion cannot be guaranteed during an API outage. This prevents retained completed webcam archives, but does not prevent YouTube recording during the live broadcast.

The old DVR-enabled broadcast was completed and its deletion verified through the videos API. Its replacement was verified live with DVR disabled, and Joomla received the replacement ID automatically.

## Camera supervisor stability (2026-10-07)

The running supervisor is `../webcam_onvif_supervisor.py`. It reads `../webcam-supervisor.conf` by default; `WEBCAM_SUPERVISOR_CONF` can select a different file. The older `config.txt` is not the default configuration for this supervisor.

Scheduled proactive camera restarts are disabled (`proactive_camera_restart_every=0`, both in defaults and the deployed configuration). Camera and ffmpeg monitoring still handle actual failures. YouTube HLS lookup uses a 10-second socket timeout, one retry and a 25-second subprocess timeout. A failed lookup or unavailable HLS is treated as unknown viewer health: after the configured probe-failure threshold, the supervisor clears the stall counters and continues camera/ffmpeg monitoring without restarting the camera or switching to fallback solely because HLS is unavailable. Confirmed HLS stalls retain their existing recovery handling.

## Local configuration and GitHub

The project `.gitignore` excludes `config.txt`, `webcam-supervisor.conf`, `publisher.json`, `.env`, YouTube OAuth JSON files and their backup copies. Keep real credentials on the camera server. The Joomla ZIP builder packages only the `plugin/` directory, excluding these server configuration files.

Ignore rules apply to untracked files. If an existing Git checkout already tracks a configuration file, remove it from the index with `git rm --cached -- <path>` and commit that removal together with these ignore rules; the local file remains on disk. Check with `git ls-files -- <path>` and `git check-ignore -v -- <path>`. Previously committed credentials remain in Git history and require separate cleanup and replacement if they were exposed.

On 2026-10-08 this server directory was connected to `tellustheguru/webcam-2.0`, with `main` tracking `origin/main`. Configuration files are ignored and were not tracked on the remote main branch. Fetch uses HTTPS; push uses a dedicated SSH deploy key in `.git/`. The public deploy key is registered on GitHub with write access; push was verified. Git metadata is owned by `andersj`, and the root-owned project directory is explicitly trusted; Git operations work without `sudo`. The runtime supervisor remains `webcam_onvif_supervisor.py`; the older `webcam-supervisor.py` was archived outside the checkout on 2026-10-08.
