import { useEffect, useRef, useState } from 'react';

let apiPromise: Promise<typeof YT> | null = null;

function loadApi(): Promise<typeof YT> {
  apiPromise ??= new Promise((resolve, reject) => {
    if (window.YT?.Player) return resolve(window.YT);
    const w = window as unknown as { onYouTubeIframeAPIReady?: () => void };
    const prev = w.onYouTubeIframeAPIReady;
    w.onYouTubeIframeAPIReady = () => { prev?.(); resolve(window.YT); };
    const s = document.createElement('script');
    s.src = 'https://www.youtube.com/iframe_api';
    s.onerror = () => { apiPromise = null; reject(new Error('YouTube 를 불러오지 못했습니다 (오프라인?)')); };
    document.head.appendChild(s);
  });
  return apiPromise;
}

export interface PlayerApi {
  ready: boolean;
  error: string | null;
  playing: boolean;
  /** 현재 재생 위치 (250ms 간격 갱신) */
  time: number;
  currentTime: () => number | null;
  seek: (sec: number, play?: boolean) => void;
}

/** YouTube IFrame 플레이어. videoId 가 바뀌면 같은 플레이어에서 영상만 교체한다 */
export function useYouTube(container: React.RefObject<HTMLDivElement>, videoId: string | null): PlayerApi {
  const player = useRef<YT.Player | null>(null);
  const loadedId = useRef<string | null>(null);
  const pendingSeek = useRef<{ sec: number; play: boolean } | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);

  useEffect(() => {
    if (!videoId || !container.current) return;
    if (player.current) {
      if (loadedId.current !== videoId) {
        loadedId.current = videoId;
        player.current.cueVideoById(videoId);
      }
      return;
    }
    let cancelled = false;
    const host = document.createElement('div');
    container.current.appendChild(host);
    loadApi().then((Y) => {
      if (cancelled) return;
      loadedId.current = videoId;
      player.current = new Y.Player(host, {
        videoId,
        width: '100%',
        height: '100%',
        playerVars: { playsinline: 1, rel: 0, modestbranding: 1, origin: location.origin },
        events: {
          onReady: () => {
            setReady(true);
            const p = pendingSeek.current;
            if (p) { pendingSeek.current = null; player.current?.seekTo(p.sec, true); if (p.play) player.current?.playVideo(); }
          },
          onStateChange: (e) => setPlaying(e.data === Y.PlayerState.PLAYING),
          onError: (e) => setError(`영상을 재생할 수 없습니다 (코드 ${e.data})`),
        },
      });
    }).catch((e: Error) => setError(e.message));
    return () => { cancelled = true; };
  }, [videoId, container]);

  useEffect(() => () => { player.current?.destroy(); player.current = null; }, []);

  useEffect(() => {
    if (!ready) return;
    const id = window.setInterval(() => {
      const t = player.current?.getCurrentTime?.();
      if (typeof t === 'number') setTime(t);
    }, 250);
    return () => clearInterval(id);
  }, [ready]);

  return {
    ready,
    error,
    playing,
    time,
    currentTime: () => (ready ? player.current?.getCurrentTime?.() ?? null : null),
    seek: (sec, play = true) => {
      if (!player.current || !ready) { pendingSeek.current = { sec, play }; return; }
      player.current.seekTo(sec, true);
      if (play) player.current.playVideo();
      setTime(sec);
    },
  };
}
