"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { TABS } from "@/app/tab-config";

export default function TabShell() {
  const pathname = usePathname();

  return (
    <header className="flex shrink-0 flex-wrap items-center gap-4 border-b border-white/10 bg-[#0c0c12] px-4 py-3">
      <Link href="/overview" className="flex items-baseline gap-2">
        <span className="text-sm font-bold tracking-[0.2em] text-white">STADIUM SENTINEL</span>
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Venue A</span>
      </Link>
      <nav className="flex flex-wrap gap-2" aria-label="Workspace tabs">
        {TABS.map((tab) => {
          const active =
            pathname === tab.path || pathname.startsWith(`${tab.path}/`);
          return (
            <Link
              key={tab.path}
              href={tab.path}
              className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                active
                  ? "bg-white/10 text-white"
                  : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
      <span className="ml-auto text-[10px] uppercase tracking-wider text-slate-500">
        Synthetic scenarios · prioritizes footage for human review · not an emergency detector
      </span>
    </header>
  );
}
