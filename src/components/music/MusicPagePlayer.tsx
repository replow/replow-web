import { ErrorBoundary } from '@components/common/ErrorBoundary';
import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import {
  type DiscoveryPlaylist,
  type DiscoverySong,
  playlistMusic,
  recommendedMusic,
  searchMusic,
} from '@/lib/music-discovery';
import { playBgmTracks } from '@/store/bgm';
import './discovery.css';

function MusicDiscovery() {
  const [query, setQuery] = useState('');
  const [songs, setSongs] = useState<DiscoverySong[]>([]);
  const [playlists, setPlaylists] = useState<DiscoveryPlaylist[]>([]);
  const [heading, setHeading] = useState('搜索音乐');
  const [loading, setLoading] = useState(false);
  const [recommendLoading, setRecommendLoading] = useState(true);
  const [error, setError] = useState('');
  const [recommendError, setRecommendError] = useState('');
  const [activeQuery, setActiveQuery] = useState('');
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const request = useRef<AbortController | null>(null);
  const recommendations = useRef<AbortController | null>(null);
  const retry = useRef<() => void>(() => {});

  const search = useCallback(async (term: string, nextPage = 0) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError('');
    setHeading(`“${term}” 的搜索结果`);
    setActiveQuery(term);
    if (!nextPage) setSongs([]);
    retry.current = () => {
      void search(term, nextPage);
    };
    try {
      const result = await searchMusic(term, nextPage, controller.signal);
      if (controller.signal.aborted) return;
      setSongs((previous) =>
        nextPage
          ? [...previous, ...result.songs.filter((song) => !previous.some((item) => item.id === song.id))]
          : result.songs,
      );
      setPage(nextPage);
      setTotal(result.total);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '搜索失败，请重试。');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  async function openPlaylist(playlist: DiscoveryPlaylist) {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError('');
    setHeading(playlist.name);
    setActiveQuery('');
    setSongs([]);
    setTotal(0);
    retry.current = () => {
      void openPlaylist(playlist);
    };
    try {
      const result = await playlistMusic(playlist.id, controller.signal);
      if (!controller.signal.aborted) setSongs(result);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '歌单加载失败，请重试。');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  const loadRecommendations = useCallback(async () => {
    recommendations.current?.abort();
    const controller = new AbortController();
    recommendations.current = controller;
    setRecommendLoading(true);
    setRecommendError('');
    try {
      const result = await recommendedMusic(controller.signal);
      if (!controller.signal.aborted) setPlaylists(result);
    } catch {
      if (!controller.signal.aborted) setRecommendError('推荐歌单暂时加载失败，请重试。');
    } finally {
      if (!controller.signal.aborted) setRecommendLoading(false);
    }
  }, []);

  useEffect(() => {
    const term = new URLSearchParams(location.search).get('q')?.trim().slice(0, 100);
    if (term) {
      setQuery(term);
      void search(term);
    }
    void loadRecommendations();
    return () => {
      request.current?.abort();
      recommendations.current?.abort();
    };
  }, [search, loadRecommendations]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const term = query.trim().slice(0, 100);
    if (!term) return;
    const url = new URL(location.href);
    url.searchParams.set('q', term);
    history.replaceState(history.state, '', url);
    void search(term);
  }

  return (
    <div className="music-discovery">
      <form className="music-discovery-search" onSubmit={submit} aria-label="音乐搜索">
        <input
          aria-label="搜索歌曲、歌手"
          placeholder="搜索歌曲、歌手，发现喜欢的旋律"
          value={query}
          maxLength={100}
          onChange={(event) => setQuery(event.target.value)}
        />
        <button type="submit" disabled={!query.trim()}>
          搜索
        </button>
      </form>
      <section className="music-discovery-results" aria-label="歌曲列表" aria-busy={loading}>
        <div className="music-discovery-section-heading">
          <h2>{heading}</h2>
          {songs.length > 0 && (
            <button type="button" onClick={() => playBgmTracks(songs, 0)}>
              播放全部
            </button>
          )}
        </div>
        {error && (
          <div role="alert">
            <p>{error}</p>
            <button type="button" onClick={() => retry.current()}>
              重新加载
            </button>
          </div>
        )}
        {loading && <output>正在加载歌曲…</output>}
        {!loading && !error && !songs.length && (
          <p>{heading === '搜索音乐' ? '输入歌曲、歌手，或选择下方推荐歌单。' : '没有找到歌曲，换个关键词试试。'}</p>
        )}
        <ol className="music-discovery-songs">
          {songs.map((song, index) => (
            <li key={song.id}>
              <button
                type="button"
                onClick={() => playBgmTracks(songs, index)}
                aria-label={`播放 ${song.name} - ${song.artist}`}
              >
                <span className="music-discovery-number">{index + 1}</span>
                {song.pic && <img src={song.pic} alt="" loading="lazy" referrerPolicy="no-referrer" />}
                <span className="music-discovery-song-copy">
                  <strong>{song.name}</strong>
                  <span>{song.artist}</span>
                </span>
                <span className="music-discovery-play">播放</span>
              </button>
            </li>
          ))}
        </ol>
        {activeQuery && songs.length > 0 && songs.length < total && !error && (
          <button
            className="music-discovery-more"
            type="button"
            disabled={loading}
            onClick={() => {
              void search(activeQuery, page + 1);
            }}
          >
            加载更多
          </button>
        )}
      </section>
      <section aria-label="推荐歌单" aria-busy={recommendLoading}>
        <div className="music-discovery-section-heading">
          <h2>推荐歌单</h2>
          <button
            type="button"
            onClick={() => {
              void loadRecommendations();
            }}
            disabled={recommendLoading}
          >
            刷新歌单
          </button>
        </div>
        {recommendLoading && <output>正在发现好歌单…</output>}
        {recommendError && <p role="alert">{recommendError}</p>}
        {!recommendLoading && !recommendError && !playlists.length && <p>暂时没有推荐歌单，试试搜索喜欢的歌曲。</p>}
        <div className="music-discovery-playlists">
          {playlists.map((playlist) => (
            <button
              type="button"
              key={playlist.id}
              onClick={() => {
                void openPlaylist(playlist);
              }}
              aria-label={`查看歌单 ${playlist.name}`}
            >
              {playlist.cover && <img src={playlist.cover} alt="" loading="lazy" referrerPolicy="no-referrer" />}
              <strong>{playlist.name}</strong>
              <span>{playlist.count > 0 ? `${playlist.count} 首歌曲` : '查看歌单'}</span>
            </button>
          ))}
        </div>
      </section>
      <p className="music-discovery-hint">选择歌曲后，使用右下角的小播放器控制播放。切换页面也能继续听。</p>
    </div>
  );
}

export default function MusicPagePlayer() {
  return (
    <ErrorBoundary>
      <MusicDiscovery />
    </ErrorBoundary>
  );
}
