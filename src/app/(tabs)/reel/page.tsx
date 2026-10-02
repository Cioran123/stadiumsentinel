import ReelView from "@/app/components/ReelView";
import { listReels } from "@/app/lib/reel";
import { listIncidents } from "@/app/lib/venue";

export const dynamic = "force-dynamic";

export default async function ReelPage() {
  const [reels, incidents] = await Promise.all([listReels(), listIncidents()]);
  return (
    <ReelView
      initialReels={reels}
      keptCount={incidents.filter((i) => i.verificationStatus === "kept").length}
    />
  );
}
