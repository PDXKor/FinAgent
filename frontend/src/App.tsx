import { Link, Outlet } from "@tanstack/react-router";

import { useHealth } from "./api/queries";

const NAV = "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100";
const ACTIVE = "text-zinc-900 dark:text-zinc-100 font-medium";

export default function Layout() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-baseline gap-6">
            <span className="font-semibold tracking-tight">FinAgent</span>
            <nav className="flex gap-4 text-sm">
              <Link to="/" className={NAV} activeProps={{ className: ACTIVE }} activeOptions={{ exact: true }}>
                Ingestion
              </Link>
              <Link to="/data" className={NAV} activeProps={{ className: ACTIVE }}>
                Data viewer
              </Link>
            </nav>
          </div>
          <HealthBadge />
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}

function HealthBadge() {
  const health = useHealth();
  const [dot, label] = health.isSuccess
    ? ["bg-emerald-500", "Data API"]
    : health.isError
      ? ["bg-red-500", "Data API down"]
      : ["bg-zinc-400", "Data API…"];
  return (
    <span className="flex items-center gap-2 text-xs text-zinc-500" title={health.error?.message}>
      <span className={`size-2 rounded-full ${dot}`} />
      {label}
    </span>
  );
}
