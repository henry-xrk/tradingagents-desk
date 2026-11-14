import type { ReactNode } from "react";

import { useLocale } from "../i18n.tsx";
import { formForRoute, selectProvider, type ResearchFormState } from "../lib/researchForm.ts";
import type { AnalystId, ConfigOptions } from "../types/api.ts";
import { Button } from "./ui/button.tsx";
import { Input, Select } from "./ui/input.tsx";

export function ResearchSetup({
  form,
  setForm,
  options,
  advanced,
  setAdvanced,
  busy,
  onSubmit,
  onWatch,
  watchPending,
  showCopy,
  onCopy,
  showRestore,
}: {
  form: ResearchFormState;
  setForm: (form: ResearchFormState) => void;
  options: ConfigOptions;
  advanced: boolean;
  setAdvanced: (value: boolean | ((value: boolean) => boolean)) => void;
  busy: boolean;
  onSubmit: () => void;
  onWatch: () => void;
  watchPending: boolean;
  showCopy?: boolean;
  onCopy?: () => void;
  showRestore?: boolean;
}) {
  const { t, locale } = useLocale();
  const provider = options.providers.find((item) => item.id === form.llm_provider);
  const depthLabel = t(`depth.${form.research_depth}`);
  return (
    <form className="grid gap-4 lg:grid-cols-2" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
      <div className="space-y-3">
      <Label text={t("research.ticker")}>
        <Input className="font-mono uppercase" value={form.ticker} onChange={(event) => setForm({ ...form, ticker: event.target.value.toUpperCase() })} required />
      </Label>
      <Label text={t("research.date")}>
        <Input type="date" max={options.today} value={form.analysis_date} onChange={(event) => setForm({ ...form, analysis_date: event.target.value })} required />
      </Label>
      <p className="text-xs text-muted">{t("research.dateNote")}</p>
      <fieldset>
        <legend className="mb-1 text-xs text-muted">{t("research.analysts")}</legend>
        <div className="space-y-1">
          {options.analysts.map((analyst) => (
            <label key={analyst.id} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.analysts.includes(analyst.id)} onChange={() => setForm({ ...form, analysts: toggleAnalyst(form.analysts, analyst.id) })} />
              {analystName(t, analyst.id, analyst.label)}
            </label>
          ))}
        </div>
      </fieldset>
      <Label text={t("research.depth")}>
        <Select value={String(form.research_depth)} onChange={(event) => setForm({ ...form, research_depth: Number(event.target.value) as ResearchFormState["research_depth"] })}>
          {options.depths.map((depth) => (
            <option key={depth.id} value={depth.id}>{t(`depth.${depth.id}`)}</option>
          ))}
        </Select>
      </Label>
      <p className="text-xs leading-5 text-muted">
        {depthLabel}. {t("research.depthNote")}
      </p>
      <button type="button" className="text-xs text-accent lg:hidden" onClick={() => setAdvanced((value) => !value)}>
        {advanced ? t("research.hideModels") : t("research.models")}
      </button>
      </div>
      <div className={advanced ? "space-y-3" : "hidden space-y-3 lg:block"}>
          <Label text={t("research.outputLanguage")}>
            <Select value={form.output_language} onChange={(event) => setForm({ ...form, output_language: event.target.value as ResearchFormState["output_language"] })}>
              {options.languages.map((language) => (
                <option key={language} value={language}>{language}</option>
              ))}
            </Select>
          </Label>
          <p className="text-xs text-muted">{t("research.interfaceLanguage")}: {locale === "zh" ? "中文" : "English"}. {t("language.note")}</p>
          <Label text={t("research.provider")}>
            <Select value={form.llm_provider} onChange={(event) => setForm(selectProvider(form, options, event.target.value))}>
              {options.providers.map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </Select>
          </Label>
          {provider?.auth_message && <p className="text-xs text-warn">{provider.auth_message}</p>}
          <ModelField label={t("research.quick")} value={form.quick_think_llm} choices={provider?.models.quick ?? []} onChange={(value) => setForm({ ...form, quick_think_llm: value })} />
          <ModelField label={t("research.deep")} value={form.deep_think_llm} choices={provider?.models.deep ?? []} onChange={(value) => setForm({ ...form, deep_think_llm: value })} />
          {provider?.requires_url && (
            <Label text={t("research.endpoint")}>
              <Input value={form.backend_url} onChange={(event) => setForm({ ...form, backend_url: event.target.value })} placeholder={provider.default_url ?? "https://"} />
            </Label>
          )}
      </div>
      <div className="flex flex-wrap gap-2 lg:col-span-2">
        <Button type="submit" disabled={busy || form.analysts.length === 0}>{busy ? t("research.running") : t("research.run")}</Button>
        <Button type="button" variant="outline" disabled={!form.ticker.trim() || watchPending} onClick={onWatch}>{t("research.watch")}</Button>
        {showRestore && (
          <Button type="button" variant="ghost" onClick={() => setForm(formForRoute({ mode: "new", options, ticker: form.ticker, saved: null }))}>
            {t("research.restore")}
          </Button>
        )}
      </div>
      {showCopy && onCopy && (
        <button type="button" className="text-xs text-accent" onClick={onCopy}>{t("research.copySettings")}</button>
      )}
    </form>
  );
}

function Label({ text, children }: { text: string; children: ReactNode }) {
  return (
    <label className="block text-xs text-muted">
      {text}
      <div className="mt-1">{children}</div>
    </label>
  );
}

function ModelField({ label, value, choices, onChange }: { label: string; value: string; choices: { id: string; label: string }[]; onChange: (value: string) => void }) {
  const { t } = useLocale();
  return (
    <Label text={label}>
      {choices.length > 0 && (
        <Select className="mb-1" value={choices.some((choice) => choice.id === value) ? value : ""} onChange={(event) => onChange(event.target.value)}>
          <option value="">{t("form.chooseOrType")}</option>
          {choices.map((choice) => (
            <option key={choice.id} value={choice.id}>{choice.label}</option>
          ))}
        </Select>
      )}
      <Input value={value} onChange={(event) => onChange(event.target.value)} placeholder="Model ID" required />
    </Label>
  );
}

function analystName(t: (key: string) => string, id: string, fallback: string) {
  const key = `analyst.${id}`;
  const value = t(key);
  return value === key ? fallback : value;
}

function toggleAnalyst(current: string[], analyst: AnalystId): string[] {
  return current.includes(analyst) ? current.filter((item) => item !== analyst) : [...current, analyst];
}
