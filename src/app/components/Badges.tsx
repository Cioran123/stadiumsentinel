import {
  PRIORITY_COLOR,
  STATUS_COLOR,
  type Priority,
  type SourceType,
  type VerificationStatus,
} from "@/app/lib/types";

function Pill({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
      style={{ color, borderColor: `${color}55`, background: `${color}1a` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {children}
    </span>
  );
}

export function PriorityBadge({ priority }: { priority: Priority }) {
  return <Pill color={PRIORITY_COLOR[priority]}>{priority} priority</Pill>;
}

const STATUS_LABEL: Record<VerificationStatus, string> = {
  candidate: "Unverified candidate",
  kept: "Verified: kept",
  rejected: "Verified: rejected",
};

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  return <Pill color={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</Pill>;
}

export function SourceBadge({ sourceType }: { sourceType: SourceType }) {
  if (sourceType !== "synthetic_seedance") {
    return <Pill color="#60a5fa">{sourceType.replace("_", " ")}</Pill>;
  }
  return <Pill color="#c084fc">Synthetic scenario</Pill>;
}
