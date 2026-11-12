import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  listPendingWriteActions,
  type BatchActionResult,
  type PendingWriteAction,
} from "./userApi";

export type WriteBatchContextValue = {
  conversationId: string;
  pending: PendingWriteAction[];
  results: Record<string, BatchActionResult>;
  revision: number;
  refresh: () => Promise<void>;
  applyResults: (results: BatchActionResult[]) => void;
};

export const WriteBatchContext = createContext<WriteBatchContextValue | null>(
  null,
);

export function WriteBatchProvider({
  conversationId,
  children,
}: {
  conversationId: string;
  children: ReactNode;
}) {
  const [pending, setPending] = useState<PendingWriteAction[]>([]);
  const [results, setResults] = useState<Record<string, BatchActionResult>>({});
  const [revision, setRevision] = useState(0);

  const refresh = useCallback(async () => {
    try {
      setPending(await listPendingWriteActions(conversationId));
    } catch {
      setPending([]);
    }
  }, [conversationId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const applyResults = useCallback((items: BatchActionResult[]) => {
    setResults((current) => {
      const next = { ...current };
      for (const item of items) next[item.action_id] = item;
      return next;
    });
    setRevision((value) => value + 1);
  }, []);

  const value = useMemo(
    () => ({
      conversationId,
      pending,
      results,
      revision,
      refresh,
      applyResults,
    }),
    [conversationId, pending, results, revision, refresh, applyResults],
  );

  return (
    <WriteBatchContext.Provider value={value}>
      {children}
    </WriteBatchContext.Provider>
  );
}
