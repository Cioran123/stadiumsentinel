"use client";

import { useCallback, useEffect, useImperativeHandle, useRef, type ReactNode, type Ref } from "react";

export interface VideoPlayerHandle {
  seekTo: (seconds: number) => void;
  togglePlay: () => void;
  seekRelative: (deltaSeconds: number) => void;
  isPaused: () => boolean;
}

interface Props {
  ref?: Ref<VideoPlayerHandle>;
  src: string;
  onTimeChange: (currentTime: number) => void;
  onDurationChange?: (duration: number) => void;
  /** Seek here once metadata has loaded. */
  initialTime?: number;
  /** Rendered absolutely over the video (e.g. an SVG overlay in 0..1 coordinates). */
  overlay?: ReactNode;
}

export default function VideoPlayer({ ref, src, onTimeChange, onDurationChange, initialTime, overlay }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const appliedInitial = useRef(false);

  const handleMetadata = useCallback(
    (v: HTMLVideoElement) => {
      const d = v.duration;
      if (Number.isFinite(d) && d > 0) onDurationChange?.(d);
      if (initialTime !== undefined && !appliedInitial.current) {
        appliedInitial.current = true;
        v.currentTime = Math.max(0, initialTime);
      }
    },
    [initialTime, onDurationChange],
  );

  // Metadata can finish loading before hydration attaches onLoadedMetadata.
  useEffect(() => {
    const v = videoRef.current;
    if (v && v.readyState >= 1) handleMetadata(v);
  }, [handleMetadata]);

  useImperativeHandle(
    ref,
    () => ({
      seekTo(seconds: number) {
        const v = videoRef.current;
        if (!v) return;
        const max = Number.isFinite(v.duration) ? v.duration : seconds;
        v.currentTime = Math.max(0, Math.min(max, seconds));
      },
      togglePlay() {
        const v = videoRef.current;
        if (!v) return;
        if (v.paused) void v.play().catch(() => {});
        else v.pause();
      },
      seekRelative(delta: number) {
        const v = videoRef.current;
        if (!v) return;
        const max = Number.isFinite(v.duration) ? v.duration : v.currentTime + delta;
        v.currentTime = Math.max(0, Math.min(max, v.currentTime + delta));
      },
      isPaused() {
        return videoRef.current?.paused ?? true;
      },
    }),
    [],
  );

  return (
    <div className="relative overflow-hidden rounded-xl border border-white/10 bg-black">
      <video
        ref={videoRef}
        controls
        muted
        preload="metadata"
        className="aspect-video w-full"
        src={src}
        onTimeUpdate={(e) => onTimeChange(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => handleMetadata(e.currentTarget)}
      />
      {overlay && <div className="pointer-events-none absolute inset-0">{overlay}</div>}
    </div>
  );
}
