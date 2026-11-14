import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Panel } from "../components/AgentWorkflow.tsx";
import { Badge } from "../components/ui/badge.tsx";
import { Button } from "../components/ui/button.tsx";
import { useLocale } from "../i18n.tsx";
import { formatWhen } from "../lib/utils.ts";
import { api } from "../services/api.ts";
import type { SystemStatus } from "../types/api.ts";

export function SettingsPage() {
  const { t } = useLocale();
  const queryClient = useQueryClient();
  const system = useQuery({
    queryKey: ["system"],
    queryFn: () => api<SystemStatus>("/api/system"),
  });
  const [warned, setWarned] = useState(false);
  const validate = useMutation({
    mutationFn: () =>
      api<SystemStatus["validation"]>("/api/system/validate", {
        method: "POST",
        body: JSON.stringify({ confirm_charge: true }),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["system"] });
    },
  });

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-medium">{t("settings.title")}</h1>
        <p className="copy mt-1 text-sm text-muted">{t("settings.lead")} {t("language.note")}</p>
      </div>
      {system.isLoading && <p className="text-sm text-muted">{t("settings.loading")}</p>}
      {system.error && (
        <div role="alert" className="space-y-2">
          <p className="text-sm text-danger">{system.error.message}</p>
          <Button type="button" variant="outline" onClick={() => system.refetch()}>{t("common.retry")}</Button>
        </div>
      )}
      {system.data && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title={t("settings.api")}>
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span>{t("settings.key")}</span>
                <Badge>{system.data.openai_api_key_configured ? t("settings.yes") : t("settings.no")}</Badge>
              </div>
              <p className="text-xs leading-5 text-muted">{system.data.configured_means}</p>
              <div className="text-xs text-muted">{t("settings.endpoint")}: {system.data.validation.endpoint ?? t("common.unknown")}</div>
              <div className="text-xs text-muted">
                {t("settings.lastCheck")}: {system.data.validation.matches_current && system.data.validation.checked_at ? formatWhen(system.data.validation.checked_at) : t("settings.notCurrent")}
                {" · "}
                {system.data.validation.code}
              </div>
              <p className="text-sm">{system.data.validation.message}</p>
              {!warned ? (
                <Button type="button" variant="outline" onClick={() => setWarned(true)}>{t("settings.check")}</Button>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-warn">{t("settings.checkWarn")}</p>
                  <Button type="button" disabled={validate.isPending} onClick={() => validate.mutate()}>
                    {validate.isPending ? t("settings.checking") : t("settings.runCheck")}
                  </Button>
                </div>
              )}
              {validate.isError && <p className="text-xs text-danger">{validate.error.message}</p>}
            </div>
          </Panel>
          <Panel title={t("settings.service")}>
            <div className="space-y-2 text-sm">
              <Row label={t("settings.version")} value={system.data.version} />
              <Row label={t("settings.commit")} value={system.data.commit} />
              <Row label={t("settings.health")} value={system.isSuccess ? t("settings.healthOk") : t("common.unknown")} />
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[#4d5d6d]">{label}</span>
      <span className="font-mono text-xs">{value}</span>
    </div>
  );
}
