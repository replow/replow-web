/**
 * Dedicated music page. It shares the configured NetEase playlists and
 * media-player mutex with the persistent floating BGM player.
 */

import { PlayerPlaylist, type PlaylistGroup } from '@components/markdown/audio-player/PlayerPlaylist';
import { PlayerPreview } from '@components/markdown/audio-player/PlayerPreview';
import { MediaControls } from '@components/markdown/shared/MediaControls';
import { useAudioPlayer } from '@hooks/useAudioPlayer';
import { useTranslation } from '@hooks/useTranslation';
import type { BgmAudioGroup } from '@lib/config/types';
import type { MetingSong } from '@lib/meting';
import { resolvePlaylist } from '@lib/meting';
import { useEffect, useState } from 'react';

interface MusicPagePlayerProps {
  audioGroups: BgmAudioGroup[];
  metingApi?: string;
}

export default function MusicPagePlayer({ audioGroups, metingApi }: MusicPagePlayerProps) {
  const { t } = useTranslation();
  const [tracks, setTracks] = useState<MetingSong[]>([]);
  const [groups, setGroups] = useState<PlaylistGroup[]>([]);
  const [activeTab, setActiveTab] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  // biome-ignore lint/correctness/useExhaustiveDependencies: retryKey intentionally reloads the playlists on retry.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    async function load() {
      const results = await Promise.allSettled(audioGroups.map((group) => resolvePlaylist(group.list, metingApi)));
      if (cancelled) return;

      const allTracks: MetingSong[] = [];
      const resolvedGroups: PlaylistGroup[] = [];
      for (let index = 0; index < results.length; index++) {
        const result = results[index];
        const songs = result.status === 'fulfilled' ? result.value : [];
        resolvedGroups.push({ title: audioGroups[index].title, startIndex: allTracks.length, count: songs.length });
        allTracks.push(...songs);
      }

      const failure = results.find((result) => result.status === 'rejected');
      if (allTracks.length === 0 && failure?.status === 'rejected') {
        setError(failure.reason instanceof Error ? failure.reason.message : 'Failed to load playlist');
      }
      setTracks(allTracks);
      setGroups(resolvedGroups);
      const firstAvailableGroup = resolvedGroups.findIndex((group) => group.count > 0);
      setActiveTab(firstAvailableGroup < 0 ? 0 : firstAvailableGroup);
      setLoading(false);
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [audioGroups, metingApi, retryKey]);

  // Always mount the hook, even while loading, so playback can begin after data resolves.
  const player = useAudioPlayer(tracks);
  const currentTrack = tracks[player.state.currentIndex] ?? null;

  if (loading) {
    return (
      <output className="music-page-player audio-player audio-player-loading">
        <span className="audio-player-spinner" />
        <span>{t('audio.loading')}</span>
      </output>
    );
  }

  if (error || tracks.length === 0) {
    return (
      <output className="music-page-player audio-player audio-player-empty">
        <span>{error ? t('audio.loadError', { error }) : t('audio.empty')}</span>
        {error && (
          <button type="button" className="audio-player-btn" onClick={() => setRetryKey((key) => key + 1)}>
            {t('audio.retry')}
          </button>
        )}
      </output>
    );
  }

  return (
    <div className="music-page-player audio-player not-prose">
      <PlayerPreview track={currentTrack} playing={player.state.playing} timeStore={player.timeStore} reserveLyrics />
      <MediaControls
        playing={player.state.playing}
        loading={player.state.loading}
        mode={player.state.mode}
        volume={player.state.volume}
        muted={player.state.muted}
        timeStore={player.timeStore}
        onTogglePlay={player.togglePlay}
        onPrev={player.prevTrack}
        onNext={player.nextTrack}
        onSeek={player.seek}
        onSetMode={player.setMode}
        onSetVolume={player.setVolume}
        onToggleMute={player.toggleMute}
      />
      {player.state.error && (
        <div className="audio-player-error" role="alert">
          {t('audio.loadError', { error: player.state.error })}
        </div>
      )}
      <PlayerPlaylist
        tracks={tracks}
        groups={groups}
        currentIndex={player.state.currentIndex}
        playing={player.state.playing}
        timeStore={player.timeStore}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        onTrackSelect={player.play}
        onSeek={player.seek}
      />
    </div>
  );
}
