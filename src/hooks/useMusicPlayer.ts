import { useEffect, useRef, useState } from 'react';
import { type LyricLine, restoreQueue, type Song, songLyrics, songSource } from '@/lib/netease';

type Mode = 'list' | 'single' | 'shuffle';
const STORAGE = 'silune.music.queue.v1';

export function useMusicPlayer() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const requestRef = useRef<AbortController | null>(null);
  const [queue, setQueue] = useState<Song[]>([]);
  const [ready, setReady] = useState(false);
  const [current, setCurrent] = useState<Song | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(0.7);
  const [mode, setMode] = useState<Mode>('list');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [lyrics, setLyrics] = useState<LyricLine[]>([]);
  const [lyricState, setLyricState] = useState('选择歌曲后显示歌词');

  useEffect(() => {
    try {
      setQueue(restoreQueue(localStorage.getItem(STORAGE)));
    } catch {
      /* Private browsing can disable storage. */
    }
    setReady(true);
    const audio = audioRef.current;
    return () => {
      requestRef.current?.abort();
      audio?.pause();
      if (audio) {
        audio.removeAttribute('src');
        audio.load();
      }
      if ('mediaSession' in navigator) navigator.mediaSession.metadata = null;
    };
  }, []);

  useEffect(() => {
    if (!ready) return;
    try {
      localStorage.setItem(STORAGE, JSON.stringify({ version: 1, songs: queue }));
    } catch {
      /* Playback works without persistence. */
    }
  }, [queue, ready]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = volume;
  }, [volume]);

  async function play(song: Song, source?: Song[]) {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const audio = audioRef.current;
    if (!audio) return;
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    setCurrent(song);
    setPlaying(false);
    setTime(0);
    setDuration(0);
    setLoading(true);
    setError('');
    setNotice('');
    setLyrics([]);
    setLyricState('正在加载歌词…');
    setQueue((previous) => {
      if (source) return source.slice(0, 200);
      return previous.some((item) => item.id === song.id) ? previous : [...previous.slice(-199), song];
    });
    void songLyrics(song.id, controller.signal)
      .then((lines) => {
        if (controller.signal.aborted) return;
        setLyrics(lines);
        setLyricState(lines.length ? '' : '这首歌暂无歌词，静静聆听吧。');
      })
      .catch(() => {
        if (!controller.signal.aborted) setLyricState('歌词暂时加载失败，播放不受影响。');
      });
    try {
      const result = await songSource(song.id, controller.signal);
      if (controller.signal.aborted) return;
      audio.src = result.url;
      if (result.trial) setNotice('当前音源为网易云提供的试听片段。');
      await audio.play();
      if (!controller.signal.aborted && 'mediaSession' in navigator) {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: song.name,
          artist: song.artist,
          album: song.album,
          artwork: song.cover ? [{ src: song.cover }] : [],
        });
      }
    } catch (failure) {
      if (controller.signal.aborted) return;
      setError(
        failure instanceof Error && failure.name === 'NotAllowedError'
          ? '浏览器暂停了自动播放，请再点一次播放。'
          : failure instanceof Error
            ? failure.message
            : '播放失败，请重试。',
      );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  async function toggle(fallback?: Song[]) {
    const audio = audioRef.current;
    if (!audio || loading) return;
    if (playing) {
      audio.pause();
      return;
    }
    if (current && audio.getAttribute('src') && !audio.error) {
      setError('');
      try {
        await audio.play();
      } catch {
        setError('浏览器未能开始播放，请重试。');
      }
    } else if (current || queue[0] || fallback?.[0]) {
      const song = current ?? queue[0] ?? fallback?.[0];
      if (song) await play(song, queue.length ? undefined : fallback);
    }
  }

  function next(direction = 1, ended = false) {
    if (!queue.length) return;
    if (ended && mode === 'single' && current) {
      void play(current);
      return;
    }
    const index = queue.findIndex((song) => song.id === current?.id);
    const shuffle = mode === 'shuffle' && queue.length > 1;
    const step = shuffle ? 1 + Math.floor(Math.random() * (queue.length - 1)) : direction;
    void play(queue[(Math.max(0, index) + step + queue.length) % queue.length]);
  }

  function seek(value: number) {
    const audio = audioRef.current;
    if (!audio?.getAttribute('src') || !Number.isFinite(audio.duration)) return;
    audio.currentTime = Math.max(0, Math.min(value, audio.duration));
    setTime(audio.currentTime);
  }

  function add(song: Song) {
    setQueue((previous) => (previous.some((item) => item.id === song.id) ? previous : [...previous.slice(-199), song]));
  }

  function remove(id: number) {
    setQueue((previous) => previous.filter((song) => song.id !== id));
  }

  useEffect(() => {
    if (!('mediaSession' in navigator)) return;
    const handlers: Partial<Record<MediaSessionAction, MediaSessionActionHandler>> = {
      play: () => {
        void toggle();
      },
      pause: () => audioRef.current?.pause(),
      previoustrack: () => next(-1),
      nexttrack: () => next(),
      seekto: (details) => {
        if (details.seekTime !== undefined) seek(details.seekTime);
      },
    };
    for (const [action, handler] of Object.entries(handlers)) {
      try {
        navigator.mediaSession.setActionHandler(action as MediaSessionAction, handler);
      } catch {
        /* Unsupported action. */
      }
    }
    navigator.mediaSession.playbackState = playing ? 'playing' : 'paused';
    return () => {
      for (const action of Object.keys(handlers)) {
        try {
          navigator.mediaSession.setActionHandler(action as MediaSessionAction, null);
        } catch {
          /* Unsupported action. */
        }
      }
    };
  });

  return {
    audioRef,
    queue,
    current,
    playing,
    loading,
    time,
    duration,
    volume,
    mode,
    error,
    notice,
    lyrics,
    lyricState,
    play,
    toggle,
    next,
    seek,
    add,
    remove,
    setVolume,
    cycleMode: () => setMode((value) => (value === 'list' ? 'single' : value === 'single' ? 'shuffle' : 'list')),
    audioEvents: {
      onPlay: () => setPlaying(true),
      onPause: () => setPlaying(false),
      onEnded: () => next(1, true),
      onTimeUpdate: () => setTime(audioRef.current?.currentTime ?? 0),
      onDurationChange: () => {
        const value = audioRef.current?.duration ?? 0;
        setDuration(Number.isFinite(value) ? value : 0);
      },
      onError: () => {
        if (audioRef.current?.getAttribute('src')) {
          setLoading(false);
          setPlaying(false);
          setError('音源加载失败，可能已过期或当前网络无法访问。请重新播放或切换歌曲。');
        }
      },
    },
  };
}
