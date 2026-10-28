import { ErrorBoundary } from '@components/common/ErrorBoundary';
import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { RiFileList2Line, RiMusic2Line, RiPlayFill, RiPlayList2Line, RiSearchLine } from 'react-icons/ri';
import { useMusicPlayer } from '@/hooks/useMusicPlayer';
import { type Playlist, playlistSongs, recommendedPlaylists, type Song, searchSongs } from '@/lib/netease';
import Lyrics from './Lyrics';
import NowPlaying from './NowPlaying';
import SongList, { CoverArt } from './SongList';

type Tab = 'songs' | 'lyrics' | 'queue';
const tabs = [
  { id: 'songs', label: '歌曲', icon: RiMusic2Line },
  { id: 'lyrics', label: '歌词', icon: RiFileList2Line },
  { id: 'queue', label: '播放队列', icon: RiPlayList2Line },
] as const;

function Player() {
  const player = useMusicPlayer();
  const [query, setQuery] = useState('');
  const [songs, setSongs] = useState<Song[]>([]);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [tab, setTab] = useState<Tab>('songs');
  const [heading, setHeading] = useState('发现音乐');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [playlistError, setPlaylistError] = useState('');
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [activeQuery, setActiveQuery] = useState('初音未来');
  const request = useRef<AbortController | null>(null);
  const retry = useRef<() => void>(() => {});

  const search = useCallback(async (term: string, nextPage = 0, discovery = false) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError('');
    setTab('songs');
    setActiveQuery(term);
    setHeading(discovery ? '发现音乐' : `“${term}” 的搜索结果`);
    if (!nextPage) setSongs([]);
    retry.current = () => {
      void search(term, nextPage, discovery);
    };
    try {
      const result = await searchSongs(term, nextPage, controller.signal);
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

  const openPlaylist = async (playlist: Playlist) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError('');
    setTab('songs');
    setActiveQuery('');
    setTotal(0);
    setSongs([]);
    setHeading(playlist.name);
    retry.current = () => {
      void openPlaylist(playlist);
    };
    document.getElementById('music-library')?.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
      block: 'center',
    });
    try {
      const result = await playlistSongs(playlist.id, controller.signal);
      if (!controller.signal.aborted) setSongs(result);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '歌单加载失败，请重试。');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  const loadRecommendations = useCallback(async (signal: AbortSignal) => {
    setPlaylistError('');
    try {
      const result = await recommendedPlaylists(signal);
      if (!signal.aborted) setPlaylists(result);
    } catch {
      if (!signal.aborted) setPlaylistError('推荐歌单暂时加载失败');
    }
  }, []);

  useEffect(() => {
    const term = new URLSearchParams(location.search).get('q')?.trim().slice(0, 100);
    if (term) setQuery(term);
    void search(term || '初音未来', 0, !term);
    const controller = new AbortController();
    void loadRecommendations(controller.signal);
    return () => {
      request.current?.abort();
      controller.abort();
    };
  }, [search, loadRecommendations]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const term = query.trim().slice(0, 100);
    if (!term) return;
    const url = new URL(location.href);
    url.searchParams.set('q', term);
    history.replaceState(null, '', url);
    void search(term);
  }

  return (
    <div className="music-app">
      <header className="music-heading">
        <div>
          <h1>音乐</h1>
          <p>给日常，留一点旋律。</p>
        </div>
        <form onSubmit={submit} className="music-search" aria-label="搜索网易云音乐">
          <RiSearchLine aria-hidden="true" />
          <input
            aria-label="搜索歌曲、歌手"
            placeholder="搜索歌曲、歌手"
            value={query}
            maxLength={100}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button type="submit" disabled={!query.trim()}>
            搜索
          </button>
        </form>
      </header>
      <div className="music-surface">
        <NowPlaying player={player} songs={songs} />
        <section className="music-library" id="music-library" aria-label="音乐资料库">
          <nav className="music-tabs" aria-label="播放器视图">
            {tabs.map(({ id, label, icon: Icon }) => (
              <button key={id} type="button" aria-pressed={tab === id} onClick={() => setTab(id)}>
                <Icon aria-hidden="true" />
                {label}
                {id === 'queue' && player.queue.length > 0 && <span>{player.queue.length}</span>}
              </button>
            ))}
          </nav>
          {tab === 'lyrics' ? (
            <>
              <div className="music-library-heading">
                <h2>{player.current?.name || '歌词'}</h2>
              </div>
              <Lyrics lines={player.lyrics} time={player.time} state={player.lyricState} onSeek={player.seek} />
            </>
          ) : (
            <>
              <div className="music-library-heading">
                <h2>{tab === 'queue' ? '播放队列' : heading}</h2>
                {(tab === 'queue' ? player.queue : songs).length > 0 && (
                  <button
                    type="button"
                    className="music-text-button"
                    onClick={() => {
                      const list = tab === 'queue' ? player.queue : songs;
                      void player.play(list[0], list);
                    }}
                  >
                    <RiPlayFill />
                    播放全部
                  </button>
                )}
              </div>
              {tab === 'songs' && (
                <div className="music-quick-search">
                  {['初音未来', '轻音乐', '周杰伦'].map((term) => (
                    <button
                      key={term}
                      type="button"
                      onClick={() => {
                        setQuery(term);
                        void search(term);
                      }}
                    >
                      {term}
                    </button>
                  ))}
                </div>
              )}
              {tab === 'songs' && error && (
                <div className="music-empty music-error" role="alert">
                  <p>{error}</p>
                  <button type="button" className="music-text-button" onClick={() => retry.current()}>
                    重新加载
                  </button>
                </div>
              )}
              <div className="music-list-scroll" aria-busy={tab === 'songs' && loading}>
                <SongList
                  songs={tab === 'queue' ? player.queue : songs}
                  currentId={player.current?.id}
                  queue={player.queue}
                  isQueue={tab === 'queue'}
                  onPlay={(song) => {
                    void player.play(song, tab === 'songs' ? songs : undefined);
                  }}
                  onAdd={player.add}
                  onRemove={player.remove}
                />
                {tab === 'songs' && loading && <output className="music-empty">正在寻找好音乐…</output>}
                {!loading && !error && tab === 'songs' && !songs.length && (
                  <p className="music-empty">没有找到歌曲，换个关键词试试。</p>
                )}
                {tab === 'queue' && !player.queue.length && (
                  <p className="music-empty">队列还是空的。点击歌曲旁的 +，把喜欢的旋律放进来。</p>
                )}
                {tab === 'songs' && activeQuery && songs.length > 0 && songs.length < total && !error && (
                  <button
                    type="button"
                    className="music-load-more"
                    disabled={loading}
                    onClick={() => {
                      void search(activeQuery, page + 1, heading === '发现音乐');
                    }}
                  >
                    {loading ? '加载中…' : '加载更多'}
                  </button>
                )}
              </div>
              {tab === 'queue' && player.queue.length > 0 && (
                <p className="music-queue-hint">队列自动保存在此浏览器 · 最多 200 首</p>
              )}
            </>
          )}
        </section>
      </div>
      <section className="music-recommendations" aria-label="推荐歌单">
        <h2>推荐歌单</h2>
        {playlistError && (
          <p className="music-empty">
            {playlistError}
            <button
              type="button"
              className="music-text-button"
              onClick={() => {
                void loadRecommendations(AbortSignal.timeout(18000));
              }}
            >
              重试
            </button>
          </p>
        )}
        <div className="music-playlists">
          {playlists.map((playlist) => (
            <button
              type="button"
              key={playlist.id}
              onClick={() => {
                void openPlaylist(playlist);
              }}
              aria-label={`打开歌单 ${playlist.name}`}
            >
              <div className="music-playlist-art">
                <CoverArt src={playlist.cover} />
                <span>
                  <RiPlayFill />
                </span>
              </div>
              <h3>{playlist.name}</h3>
              <p>{playlist.count} 首歌曲</p>
            </button>
          ))}
        </div>
      </section>
      <p className="music-service-note">音乐与歌词来自网易云音乐 · 播放范围以可用音源为准</p>
    </div>
  );
}

export default function MusicPlayer() {
  return (
    <ErrorBoundary
      fallbackRender={({ resetErrorBoundary }) => (
        <div className="music-empty">
          <p>播放器遇到了问题</p>
          <button type="button" onClick={resetErrorBoundary}>
            重新打开
          </button>
        </div>
      )}
    >
      <Player />
    </ErrorBoundary>
  );
}
