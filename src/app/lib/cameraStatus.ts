import path from "node:path";
import { PIPELINE_DIR } from "@/app/lib/storage";
import type { Camera, Incident } from "@/app/lib/types";
import { cameraVideoPath, fileExists, listIncidents, loadVenue } from "@/app/lib/venue";

export type IndexStatus = "missing_video" | "not_indexed" | "tracked" | "indexed";

export interface CameraStatus {
  camera: Camera;
  indexStatus: IndexStatus;
  incidentCount: number;
  keptCount: number;
  latest?: Incident;
}

const PRIORITY_RANK = { high: 2, medium: 1, low: 0 } as const;

export async function getCameraStatuses(): Promise<CameraStatus[]> {
  const [venue, incidents] = await Promise.all([loadVenue(), listIncidents()]);
  return Promise.all(
    venue.cameras.map(async (camera) => {
      const own = incidents.filter((i) => i.cameraId === camera.id);
      const hasVideo = await fileExists(cameraVideoPath(camera));
      const hasTracks = await fileExists(path.join(PIPELINE_DIR, `${camera.id}.tracks.json`));
      const indexStatus: IndexStatus = !hasVideo
        ? "missing_video"
        : own.length > 0
          ? "indexed"
          : hasTracks
            ? "tracked"
            : "not_indexed";
      const visible = own.filter((i) => i.verificationStatus !== "rejected");
      const latest = [...visible].sort(
        (a, b) => PRIORITY_RANK[b.priority] - PRIORITY_RANK[a.priority] || b.startSec - a.startSec,
      )[0];
      return {
        camera,
        indexStatus,
        incidentCount: own.length,
        keptCount: own.filter((i) => i.verificationStatus === "kept").length,
        latest,
      };
    }),
  );
}
