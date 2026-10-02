"use client";

import { useEffect, useRef, useState } from "react";
import type { Camera, TrackBox, TrackFrame } from "@/app/lib/types";
import TrackOverlay from "./TrackOverlay";

const LIVE_URL = process.env.NEXT_PUBLIC_LIVE_URL ?? "http://localhost:8765";
// Frames are downscaled before upload; the server runs at imgsz 640 anyway.
const SEND_WIDTH = 960;
const JPEG_QUALITY = 0.7;
// Posture must hold this long before the tile flags it, so a quick bend does not.
const DOWN_HOLD_MS = 2000;

type Posture = "upright" | "tilted" | "down";
type LiveBox = TrackBox & { posture?: Posture };
type LiveFrame = { t: number; boxes: LiveBox[]; ms: number };
type Status = "idle" | "starting" | "live" | "no-server" | "no-camera";

const WEBCAM: Camera = {
  id: "WEBCAM",
  zone: "Local webcam",
  zoneId: "webcam",
  videoFile: "",
  durationSec: 0,
  sourceType: "team_recorded",
  scenario: "Live webcam test feed",
  groundTruth: { eventType: "person_down_or_inactivity", startSec: 0, endSec: 0 },
};

interface Props {
  showOverlay: boolean;
}

/** Browser webcam, labeled live by pipeline/live_server.py (YOLO-pose + ByteTrack). */
export default function WebcamTile({ showOverlay }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const runningRef = useRef(false);
  const downSince = useRef(new Map<number, number>());
  const [status, setStatus] = useState<Status>("idle");
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const [aspect, setAspect] = useState(16 / 9);
  const [fps, setFps] = useState(0);
  const [down, setDown] = useState<number[]>([]);
  const [mirrored, setMirrored] = useState(true);

  const stop = () => {
    runningRef.current = false;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    downSince.current.clear();
    setFrame(null);
    setDown([]);
    setFps(0);
    setStatus("idle");
  };

  useEffect(() => () => stop(), []);

  const loop = async () => {
    const video = videoRef.current;
    if (!video) return;
    const canvas = (canvasRef.current ??= document.createElement("canvas"));
    const scale = Math.min(1, SEND_WIDTH / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let reset = true;
    let last = performance.now();
    while (runningRef.current) {
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", JPEG_QUALITY));
      if (!blob) continue;
      try {
        const res = await fetch(`${LIVE_URL}/frame${reset ? "?reset=1" : ""}`, { method: "POST", body: blob });
        if (!res.ok) throw new Error(String(res.status));
        const data = (await res.json()) as LiveFrame;
        if (!runningRef.current) break;
        reset = false;
        const now = performance.now();
        setFps((f) => f * 0.8 + (1000 / Math.max(1, now - last)) * 0.2);
        last = now;
        setFrame(data);
        const ids = new Set(data.boxes.map((b) => b.id));
        for (const b of data.boxes) {
          if (b.posture === "down") {
            if (!downSince.current.has(b.id)) downSince.current.set(b.id, now);
          } else downSince.current.delete(b.id);
        }
        for (const id of downSince.current.keys()) if (!ids.has(id)) downSince.current.delete(id);
        setDown([...downSince.current].filter(([, since]) => now - since >= DOWN_HOLD_MS).map(([id]) => id));
        setStatus("live");
      } catch {
        if (!runningRef.current) break;
        setStatus("no-server");
        setFrame(null);
        await new Promise((r) => setTimeout(r, 1500));
        reset = true;
      }
    }
  };

  const start = async () => {
    setStatus("starting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      const video = videoRef.current!;
      video.srcObject = stream;
      await video.play();
      setAspect(video.videoWidth / video.videoHeight || 16 / 9);
      runningRef.current = true;
      void loop();
    } catch {
      setStatus("no-camera");
    }
  };

  const active = status === "live" || status === "no-server" || status === "starting";
  const people = frame?.boxes.length ?? 0;
  // The server labels the unmirrored frame; flip coordinates instead of the SVG so ID text stays readable.
  const overlayFrame: TrackFrame | null = frame
    ? {
        t: frame.t,
        boxes: mirrored
          ? frame.boxes.map((b) => ({
              ...b,
              box: [1 - b.box[2], b.box[1], 1 - b.box[0], b.box[3]],
              kp: b.kp?.map(([x, y, c]) => [1 - x, y, c] as [number, number, number]),
            }))
          : frame.boxes,
      }
    : null;

  return (
    <div className={`flex flex-col overflow-hidden rounded-xl border bg-[#0c0c12] ${down.length ? "tile-alert" : "border-white/10"}`}
      style={down.length ? ({ "--pulse": "#ef4444" } as React.CSSProperties) : undefined}>
      <div className="relative bg-black" style={{ aspectRatio: String(aspect) }}>
        <video ref={videoRef} className={`h-full w-full object-fill ${active ? "" : "hidden"}`}
          style={mirrored ? { transform: "scaleX(-1)" } : undefined} muted playsInline />
        {!active && (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center text-xs text-slate-500">
            <span className="text-sm text-slate-300">Webcam (live)</span>
            <span>{status === "no-camera" ? "Camera permission denied or no camera found." : "Labels your webcam live with YOLO-pose + ByteTrack."}</span>
            <button type="button" onClick={start}
              className="mt-1 rounded-lg border border-white/20 px-3 py-1.5 text-[12px] text-slate-200 hover:border-white/40">
              Start webcam
            </button>
          </div>
        )}
        {showOverlay && overlayFrame && (
          <div className="pointer-events-none absolute inset-0">
            <TrackOverlay camera={WEBCAM} frame={overlayFrame} highlight={new Set(down)} showIds />
          </div>
        )}
        {active && (
          <div className="absolute bottom-2 left-2 rounded bg-black/70 px-2 py-0.5 font-mono text-[11px] text-white">
            WEBCAM · LIVE · {people} {people === 1 ? "person" : "people"}
            {status === "live" ? ` · ${fps.toFixed(1)} fps · ${frame?.ms ?? 0} ms` : ""}
          </div>
        )}
        {active && (
          <div className="absolute right-2 top-2 flex items-center gap-1.5 rounded bg-red-600/80 px-2 py-0.5 text-[11px] font-semibold text-white">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" /> LIVE
          </div>
        )}
        {down.length > 0 && (
          <div className="absolute left-2 top-2 rounded bg-[#ef4444cc] px-2 py-0.5 text-[11px] font-semibold text-white">
            ● Possible person down · {down.map((id) => `#${id}`).join(", ")}
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3 text-[11px]">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5"
            style={{ color: status === "live" ? "#22c55e" : status === "no-server" ? "#f59e0b" : "#94a3b8" }}>
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: "currentColor" }} />
            {status === "live" ? "Labeling live" : status === "no-server" ? "Live server not reachable" : status === "starting" ? "Starting…" : "Not started"}
          </span>
          <span className="flex items-center gap-3">
            <button type="button" onClick={() => setMirrored((m) => !m)} className="text-slate-400 hover:text-slate-200">
              {mirrored ? "Mirrored" : "Unmirrored"}
            </button>
            {active && (
              <button type="button" onClick={stop} className="text-slate-400 hover:text-slate-200">Stop</button>
            )}
          </span>
        </div>
        <p className="text-slate-600">
          {status === "no-server"
            ? <>Start it with <code className="text-slate-400">npm run live</code> ({LIVE_URL}).</>
            : "Posture cue only (torso tilt from pose); not verified and not saved to the incident ledger."}
        </p>
      </div>
    </div>
  );
}
