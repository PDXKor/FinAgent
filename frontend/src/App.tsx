import { useHealth } from "./api/queries";
import Ingestion from "./pages/Ingestion";

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-baseline gap-6">
            <span className="font-semibold tracking-tight">FinAgent</span>
            <nav className="text-sm text-zinc-500">
              <span className="text-zinc-900 dark:text-zinc-100">Ingestion</span>
            </nav>
          </div>
          <HealthBadge />
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Ingestion />
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
