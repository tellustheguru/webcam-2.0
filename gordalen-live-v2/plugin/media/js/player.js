(() => {
  const config = window.Joomla.getOptions('gordalenLive');
  const frames = () => document.querySelectorAll('iframe[src*="gordalenlive=1"]');
  if (!config || !frames().length) return;
  const endpoint = config.statusUrl;
  const players = new Map();
  let busy = false;
  const apiReady = new Promise(resolve => {
    if (window.YT && window.YT.Player) return resolve();
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      if (typeof previous === 'function') previous();
      resolve();
    };
    if (!document.querySelector('script[src="https://www.youtube.com/iframe_api"]')) {
      const script = document.createElement('script');
      script.src = 'https://www.youtube.com/iframe_api';
      document.head.appendChild(script);
    }
  });
  function liveEdge(player) {
    try {
      const duration = player.getDuration();
      const current = player.getCurrentTime();
      if (Number.isFinite(duration) && duration > 0 && duration - current > config.maxLagSeconds) {
        player.seekTo(Math.max(0, duration - 3), true);
      }
    } catch (_) { /* Retry after metadata becomes available. */ }
  }
  async function attach() {
    await apiReady;
    frames().forEach(frame => {
      if (players.has(frame)) return;
      const url = new URL(frame.src, location.href);
      if (url.hostname !== 'www.youtube.com') return;
      url.searchParams.set('enablejsapi', '1');
      url.searchParams.set('origin', location.origin);
      frame.src = url.toString();
      const player = new window.YT.Player(frame, {
        events: {
          onReady: event => { event.target.mute(); liveEdge(event.target); event.target.playVideo(); },
          onStateChange: event => {
            if (event.data === window.YT.PlayerState.PLAYING) liveEdge(event.target);
          }
        }
      });
      players.set(frame, player);
    });
  }
  async function refresh() {
    if (busy) return;
    busy = true;
    try {
      const response = await fetch(endpoint + '&t=' + Date.now(), {cache: 'no-store', credentials: 'same-origin'});
      if (!response.ok) return;
      const result = await response.json();
      if (!result.success || !Array.isArray(result.data) || !result.data[0]) return;
      const id = result.data[0].video_id;
      if (typeof id !== 'string' || !/^[A-Za-z0-9_-]{11}$/.test(id)) return;
      for (const frame of frames()) {
        const player = players.get(frame);
        if (player && typeof player.getVideoData === 'function' && player.getVideoData().video_id) {
          if (player.getVideoData().video_id !== id) {
            player.mute();
            player.loadVideoById(id);
          } else {
            liveEdge(player);
          }
        } else if (new URL(frame.src, location.href).pathname !== '/embed/' + id) {
          frame.src = 'https://www.youtube.com/embed/' + id + '?autoplay=1&mute=1&controls=0&playsinline=1&rel=0&enablejsapi=1&gordalenlive=1&origin=' + encodeURIComponent(location.origin);
        }
      }
      attach();
    } catch (_) {
      // Preserve playback during temporary network or API failures.
    } finally { busy = false; }
  }
  attach();
  refresh();
  setInterval(refresh, config.pollSeconds * 1000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) { players.forEach(liveEdge); refresh(); }
  });
})();
