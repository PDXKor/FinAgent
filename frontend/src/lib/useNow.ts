import { useEffect, useState } from "react";

/** Current time, re-rendered every `ms` while `enabled`. */
export function useNow(enabled: boolean, ms = 1_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [enabled, ms]);
  return now;
}
