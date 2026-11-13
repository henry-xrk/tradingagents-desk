import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

export function useAnalysisStream(analysisId: string | undefined, polling: boolean) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!analysisId || !polling) return;
    const source = new EventSource(`/api/analyses/${analysisId}/events`);
    let timer = 0;
    const refresh = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ["analysis", analysisId] });
        void queryClient.invalidateQueries({ queryKey: ["analyses"] });
      }, 400);
    };
    source.addEventListener("status", refresh);
    const finish = () => {
      source.close();
      refresh();
    };
    source.addEventListener("completed", finish);
    source.addEventListener("failed", finish);
    source.addEventListener("timed_out", finish);
    source.addEventListener("stopped", finish);
    source.addEventListener("interrupted", finish);
    return () => {
      window.clearTimeout(timer);
      source.close();
    };
  }, [analysisId, polling, queryClient]);

  useEffect(() => {
    if (!analysisId || !polling) return;
    const timer = window.setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: ["analysis", analysisId] });
    }, 4000);
    return () => window.clearInterval(timer);
  }, [analysisId, polling, queryClient]);
}
