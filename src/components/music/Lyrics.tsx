import { useEffect, useRef } from 'react';
import type { LyricLine } from '@/lib/netease';

export default function Lyrics({
  lines,
  time,
  state,
  onSeek,
}: {
  lines: LyricLine[];
  time: number;
  state: string;
  onSeek: (time: number) => void;
}) {
  const active = lines.findLastIndex((line) => line.time <= time);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = ref.current;
    const line = root?.querySelectorAll<HTMLElement>('button')[active];
    if (root && line)
      root.scrollTo({
        top: line.offsetTop - root.offsetTop - root.clientHeight / 2 + line.clientHeight / 2,
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
      });
  }, [active]);
  return (
    <div className="music-lyrics" ref={ref}>
      {state ? (
        <p className="music-empty">{state}</p>
      ) : (
        lines.map((line, index) => (
          <button
            type="button"
            key={`${line.time}-${index}`}
            aria-current={active === index ? 'true' : undefined}
            onClick={() => onSeek(line.time)}
            title="点击跳转到这句歌词"
          >
            {line.text}
          </button>
        ))
      )}
    </div>
  );
}
