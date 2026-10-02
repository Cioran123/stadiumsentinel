import { promises as fs } from "node:fs";
import path from "node:path";
import { notFound } from "next/navigation";
import IncidentViewer from "@/app/components/IncidentViewer";
import { PIPELINE_DIR } from "@/app/lib/storage";
import { getIncident, listIncidents, loadTracks, loadVenue } from "@/app/lib/venue";

export const dynamic = "force-dynamic";

async function tracksAreSynthetic(cameraId: string): Promise<boolean> {
  try {
    const head = (await fs.readFile(path.join(PIPELINE_DIR, `${cameraId}.tracks.json`), "utf8")).slice(-200);
    return head.includes('"synthetic": true');
  } catch {
    return false;
  }
}

export default async function IncidentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const incident = await getIncident(id);
  if (!incident) notFound();
  const venue = await loadVenue();
  const camera = venue.cameras.find((c) => c.id === incident.cameraId);
  if (!camera) notFound();

  const [all, tracks, synthetic] = await Promise.all([
    listIncidents(),
    loadTracks(camera.id, Math.max(0, incident.startSec - 15), incident.endSec + 15),
    tracksAreSynthetic(camera.id),
  ]);

  return (
    <IncidentViewer
      incident={incident}
      camera={camera}
      venueName={venue.venueName}
      cameraIncidents={all.filter((i) => i.cameraId === camera.id)}
      tracks={tracks}
      syntheticTracks={synthetic}
    />
  );
}
