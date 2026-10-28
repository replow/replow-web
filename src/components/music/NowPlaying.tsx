import {
  RiLoader4Line,
  RiPauseFill,
  RiPlayFill,
  RiRepeat2Line,
  RiRepeatOneLine,
  RiShuffleLine,
  RiSkipBackFill,
  RiSkipForwardFill,
  RiVolumeMuteLine,
  RiVolumeUpLine,
} from 'react-icons/ri';
import type { useMusicPlayer } from '@/hooks/useMusicPlayer';
import { formatTime, type Song } from '@/lib/netease';
import { CoverArt } from './SongList';

type Player = ReturnType<typeof useMusicPlayer>;

export default function NowPlaying({ player: p, songs }: { player: Player; songs: Song[] }) {
  const song = p.current;
  const modeText = p.mode === 'list' ? '列表循环' : p.mode === 'single' ? '单曲循环' : '随机播放';
  return (
    <section className="music-now" aria-label="正在播放">
      <div className={`music-cover-wrap ${p.playing ? 'is-playing' : ''}`}>
        <CoverArt src={song?.cover || songs[0]?.cover} className="music-main-cover" />
      </div>
      <h2 title={song?.name}>{song?.name ?? '从这里开始聆听'}</h2>
      <p className="music-artist">{song?.artist ?? '选择一首歌，让音乐响起'}</p>
      <div className="music-transport">
        <button type="button" className="music-icon-button" onClick={p.cycleMode} title={modeText} aria-label={modeText}>
          {p.mode === 'list' ? <RiRepeat2Line /> : p.mode === 'single' ? <RiRepeatOneLine /> : <RiShuffleLine />}
        </button>
        <button
          type="button"
          className="music-icon-button"
          onClick={() => p.next(-1)}
          disabled={!p.queue.length}
          aria-label="上一首"
        >
          <RiSkipBackFill />
        </button>
        <button
          type="button"
          className="music-play"
          onClick={() => {
            void p.toggle(songs);
          }}
          disabled={p.loading || (!song && !p.queue.length && !songs.length)}
          aria-label={p.loading ? '正在加载音源' : p.playing ? '暂停' : '播放'}
        >
          {p.loading ? <RiLoader4Line className="music-spin" /> : p.playing ? <RiPauseFill /> : <RiPlayFill />}
        </button>
        <button
          type="button"
          className="music-icon-button"
          onClick={() => p.next()}
          disabled={!p.queue.length}
          aria-label="下一首"
        >
          <RiSkipForwardFill />
        </button>
        <button
          type="button"
          className="music-icon-button"
          onClick={() => p.setVolume(p.volume > 0 ? 0 : 0.7)}
          aria-label={p.volume > 0 ? '静音' : '取消静音'}
        >
          {p.volume > 0 ? <RiVolumeUpLine /> : <RiVolumeMuteLine />}
        </button>
      </div>
      <div className="music-progress">
        <input
          type="range"
          min="0"
          max={p.duration || 1}
          step="0.1"
          value={Math.min(p.time, p.duration || 1)}
          disabled={!p.duration}
          onChange={(event) => p.seek(Number(event.target.value))}
          aria-label="播放进度"
          aria-valuetext={`${formatTime(p.time)} / ${formatTime(p.duration)}`}
        />
        <div>
          <time>{formatTime(p.time)}</time>
          <time>{formatTime(p.duration)}</time>
        </div>
      </div>
      <label className="music-volume">
        <span>音量</span>
        <input
          type="range"
          min="0"
          max="1"
          step="0.01"
          value={p.volume}
          onChange={(event) => p.setVolume(Number(event.target.value))}
        />
        <span>{Math.round(p.volume * 100)}%</span>
      </label>
      {p.notice && <output className="music-notice">{p.notice}</output>}
      {p.error && (
        <p className="music-error" role="alert">
          {p.error}
        </p>
      )}
      <audio ref={p.audioRef} preload="none" {...p.audioEvents} />
    </section>
  );
}
