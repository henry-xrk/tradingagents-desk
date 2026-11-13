import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Panel } from "../components/AgentWorkflow.tsx";
import { Badge } from "../components/ui/badge.tsx";
import { Button } from "../components/ui/button.tsx";
import { formatWhen } from "../lib/utils.ts";
import { api } from "../services/api.ts";
import type { SystemStatus } from "../types/api.ts";

export function SettingsPage() {
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
        <h1 className="text-xl font-medium">Settings</h1>
        <p className="mt-1 max-w-3xl text-sm text-[#4d5d6d]">
          The API key stays in the server environment. This page never displays it.
        </p>
      </div>
      {system.isLoading && <p className="text-sm text-[#4d5d6d]">Loading service status.</p>}
      {system.error && <p className="text-sm text-[#b42334]">{system.error.message}</p>}
      {system.data && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="OpenAI API">
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span>Key configured</span>
                <Badge>{system.data.openai_api_key_configured ? "Yes" : "No"}</Badge>
              </div>
              <p className="text-xs leading-5 text-[#4d5d6d]">{system.data.configured_means}</p>
              <div className="text-xs text-[#4d5d6d]">
                Last check: {system.data.validation.checked_at ? formatWhen(system.data.validation.checked_at) : "Not run"}
                {" · "}
                {system.data.validation.code}
              </div>
              <p className="text-sm">{system.data.validation.message}</p>
              {!warned ? (
                <Button type="button" variant="outline" onClick={() => setWarned(true)}>
                  Check provider connection
                </Button>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-[#8a5a00]">
                    This check calls the provider. It can incur a charge or count against a rate limit. It still does not show the account balance.
                  </p>
                  <Button type="button" disabled={validate.isPending} onClick={() => validate.mutate()}>
                    {validate.isPending ? "Checking" : "Run connection check"}
                  </Button>
                </div>
              )}
              {validate.isError && <p className="text-xs text-[#b42334]">{validate.error.message}</p>}
            </div>
          </Panel>
          <Panel title="Service">
            <div className="space-y-2 text-sm">
              <Row label="Version" value={system.data.version} />
              <Row label="Build commit" value={system.data.commit} />
              <Row label="Health" value={system.isSuccess ? "API responded" : "Unknown"} />
              <p className="text-xs leading-5 text-[#4d5d6d]">
                Docker publishes the page on this machine only. The API is reached through the same address.
              </p>
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
