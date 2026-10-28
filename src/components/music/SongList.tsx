import { RiAddCircleLine, RiCheckLine, RiCloseLine, RiMusic2Line } from 'react-icons/ri';
import { formatTime, type Song } from '@/lib/netease';

export function CoverArt({ src, className = '' }: { src?: string; className?: string }) {
  return (
    <div className={`music-art ${className}`}>
      <RiMusic2Line aria-hidden="true" />
      {src && (
        <img
          key={src}
          src={`${src}${src.includes('?') ? '&' : '?'}param=480y480`}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={(event) => {
            event.currentTarget.style.display = 'none';
          }}
        />
      )}
    </div>
  );
}

interface Props {
  songs: Song[];
  currentId?: number;
  queue: Song[];
  isQueue?: boolean;
  onPlay: (song: Song) => void;
  onAdd: (song: Song) => void;
  onRemove: (id: number) => void;
}

export default function SongList({ songs, currentId, queue, isQueue, onPlay, onAdd, onRemove }: Props) {
  return (
    <ol className="music-song-list">
      {songs.map((song) => {
        const added = queue.some((item) => item.id === song.id);
        return (
          <li key={song.id} className={currentId === song.id ? 'is-current' : ''}>
            <button
              type="button"
              className="music-song-main"
              onClick={() => onPlay(song)}
              aria-label={`播放 ${song.name} - ${song.artist}`}
              aria-current={currentId === song.id ? 'true' : undefined}
            >
              <CoverArt src={song.cover} />
              <span className="music-song-copy">
                <strong>{song.name}</strong>
                <span>{song.artist}</span>
              </span>
              <time>{formatTime(song.duration / 1000)}</time>
            </button>
            <button
              type="button"
              className="music-icon-button"
              aria-label={isQueue ? `移除 ${song.name}` : added ? `${song.name} 已在队列` : `加入队列 ${song.name}`}
              disabled={!isQueue && added}
              onClick={() => (isQueue ? onRemove(song.id) : onAdd(song))}
            >
              {isQueue ? <RiCloseLine /> : added ? <RiCheckLine /> : <RiAddCircleLine />}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
