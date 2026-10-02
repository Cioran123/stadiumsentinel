/** Central list for the workspace tab bar — add entries here when introducing new tabs. */
export const TABS = [
  { path: "/overview", label: "Overview" },
  { path: "/search", label: "Incident Search" },
  { path: "/venue", label: "Venue" },
  { path: "/reel", label: "Review Reel" },
] as const;

export type TabConfig = (typeof TABS)[number];
