export interface ResearchFormState {
  ticker: string;
  analysis_date: string;
  analysts: string[];
  research_depth: 1 | 3 | 5;
  output_language: "English" | "Chinese";
  llm_provider: string;
  quick_think_llm: string;
  deep_think_llm: string;
  backend_url: string;
}

export interface ResearchFormOptions {
  today: string;
  default_provider: string;
  providers: {
    id: string;
    default_url: string | null;
    requires_url: boolean;
    models: { quick: { id: string }[]; deep: { id: string }[] };
  }[];
}

export interface SavedRunSettings {
  ticker?: string;
  analysis_date?: string;
  analysts?: string[];
  research_depth?: 1 | 3 | 5;
  output_language?: "English" | "Chinese";
  llm_provider?: string;
  quick_think_llm?: string;
  deep_think_llm?: string;
  backend_url?: string | null;
}

export type ResearchMode = "new" | "copy" | "open";

const ANALYSTS = ["market", "social", "news", "fundamentals"];

export function researchMode(analysisId?: string, fromId?: string): ResearchMode {
  if (analysisId) return "open";
  if (fromId) return "copy";
  return "new";
}

/** Changes only when the user arrives, goes back, or picks another ticker. Typing does not change it. */
export function routeIdentity(mode: ResearchMode, analysisId: string | undefined, fromId: string, tickerParam: string): string {
  if (mode === "open") return `open\n${analysisId ?? ""}`;
  if (mode === "copy") return `copy\n${fromId}`;
  return `new\n${tickerParam}`;
}

export function initialForm(options: ResearchFormOptions, ticker: string): ResearchFormState {
  const provider = options.providers.find((item) => item.id === options.default_provider) ?? options.providers[0];
  return {
    ticker: ticker || "",
    analysis_date: options.today,
    analysts: [...ANALYSTS],
    research_depth: 1,
    output_language: "English",
    llm_provider: provider?.id ?? "openai",
    quick_think_llm: provider?.models.quick[0]?.id ?? "",
    deep_think_llm: provider?.models.deep[0]?.id ?? "",
    backend_url: provider?.requires_url ? provider.default_url ?? "" : "",
  };
}

export function formFromSettings(settings: SavedRunSettings): ResearchFormState {
  return {
    ticker: settings.ticker ?? "",
    analysis_date: settings.analysis_date ?? "",
    analysts: settings.analysts ?? [],
    research_depth: settings.research_depth ?? 1,
    output_language: settings.output_language ?? "English",
    llm_provider: settings.llm_provider ?? "openai",
    quick_think_llm: settings.quick_think_llm ?? "",
    deep_think_llm: settings.deep_think_llm ?? "",
    backend_url: settings.backend_url ?? "",
  };
}

export function selectProvider(form: ResearchFormState, options: ResearchFormOptions | undefined, providerId: string): ResearchFormState {
  const provider = options?.providers.find((item) => item.id === providerId);
  return {
    ...form,
    llm_provider: providerId,
    quick_think_llm: provider?.models.quick[0]?.id ?? "",
    deep_think_llm: provider?.models.deep[0]?.id ?? "",
    backend_url: provider?.requires_url ? provider.default_url ?? "" : "",
  };
}

export function formForRoute(input: {
  mode: ResearchMode;
  options: ResearchFormOptions;
  ticker: string;
  saved?: SavedRunSettings | null;
}): ResearchFormState {
  if (input.mode === "new" || !input.saved) return initialForm(input.options, input.ticker);
  const saved = formFromSettings(input.saved);
  if (!input.options.providers.some((provider) => provider.id === saved.llm_provider)) {
    return selectProvider(saved, input.options, input.options.default_provider);
  }
  return saved;
}
