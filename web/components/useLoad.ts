"use client";

import { useCallback, useEffect, useState } from "react";

/** Load data on mount, optionally re-polling. Keeps the last good data on refresh errors. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[], pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(load, deps);

  const refresh = useCallback(async () => {
    try {
      setData(await run());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    }
  }, [run]);

  useEffect(() => {
    refresh();
    if (!pollMs) return;
    const t = setInterval(refresh, pollMs);
    return () => clearInterval(t);
  }, [refresh, pollMs]);

  return { data, error, refresh, setData };
}
