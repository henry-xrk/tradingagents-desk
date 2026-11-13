export type AnalystId = "market" | "social" | "news" | "fundamentals";
export type RunStatus =
  | "queued"
  | "running"
  | "cancel_requested"
  | "cancelling"
  | "completed"
  | "failed"
  | "timed_out"
  | "stopped"
  | "interrupted";

export interface ModelChoice {
  id: string;
  label: string;
}

export interface ProviderOption {
  id: string;
  label: string;
  default_url: string | null;
  requires_url: boolean;
  api_key_env: string | null;
  auth_message: string | null;
  models: { quick: ModelChoice[]; deep: ModelChoice[] };
  models_note: string | null;
}

export interface ConfigOptions {
  today: string;
  default_provider: string;
  signed_in_email: string | null;
  analysts: { id: AnalystId; label: string }[];
  languages: string[];
  depths: { id: 1 | 3 | 5; label: string }[];
  environment_notes: string[];
  environment: Record<string, string | null>;
  providers: ProviderOption[];
  orders_sent: boolean;
}

export interface AuthStatus {
  provider: string;
  signed_in: boolean;
  email: string | null;
  message: string | null;
}

export interface CapitalPreferences {
  available_capital: number | null;
  available_cash: number | null;
  max_risk_amount: number | null;
  max_risk_percent: number | null;
  max_position_percent: number | null;
  cost_bps: number;
}

export interface RunSettings {
  ticker: string;
  analysis_date: string;
  analysts: AnalystId[];
  research_depth: 1 | 3 | 5;
  output_language: "English" | "Chinese";
  llm_provider: string;
  quick_think_llm: string;
  deep_think_llm: string;
  backend_url: string | null;
  asset_type: string;
  max_debate_rounds: number;
  max_risk_discuss_rounds: number;
  round_notes: string[];
}

export interface ActivityItem {
  at: string;
  message: string;
}

export interface FieldStatus {
  status: "available" | "unavailable" | "partial";
  reason?: string | null;
}

export interface PriceLevel {
  price: number;
  shares: number | null;
  source: string;
}

export interface TradePlan {
  ticker: string;
  analysis_date: string;
  disclaimer: string;
  orders_sent: boolean;
  limitations: string[];
  verified_market: {
    status: string;
    source: string;
    price: number | null;
    bar_date?: string | null;
    fetched_at?: string | null;
    error?: string | null;
  };
  hypotheses: {
    status: string;
    source: string;
    action: string | null;
    rating: string | null;
    entry_price: number | null;
    stop_loss: number | null;
    price_target: number | null;
    missing: string[];
  };
  entry_zone: { status: string; low: number | null; high: number | null; reason?: string | null; source?: string };
  limit_entries: PriceLevel[];
  exits: PriceLevel[];
  invalidation: { status: string; text: string | null; stop_loss: number | null; reason?: string | null };
  sizing: {
    status: string;
    reason: string | null;
    shares: number | null;
    risk_per_share: number | null;
    planned_loss: number | null;
    maximum_planned_loss: number | null;
    capital_used: number | null;
    remaining_cash: number | null;
    allocation_percent: number | null;
    risk_reward: number | null;
    binding_constraint: string[];
    shares_by_risk: number | null;
    shares_by_allocation: number | null;
    shares_by_cash: number | null;
    direction: string | null;
  };
  assumptions: string[];
  explanation: string;
  evidence: { label: string; source: string; status: string; detail?: string | null }[];
  calculated_at: string;
  plan_version?: number | null;
  input_snapshot?: {
    scale_in_prices?: number[];
    take_profit_prices?: number[];
    capital?: CapitalPreferences;
  } | null;
}

export interface AnalysisRecord {
  id: string;
  ticker: string;
  analysis_date: string;
  settings: RunSettings;
  status: RunStatus;
  phase: string;
  agent_status: Record<string, string>;
  reports?: Record<string, string>;
  rating: string | null;
  trade_plan?: TradePlan | null;
  error: string | null;
  error_code: string | null;
  data_sources: Record<string, unknown>;
  activity: ActivityItem[];
  html_report_path: string | null;
  markdown_report_path: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  reused?: boolean;
  has_report?: boolean;
  has_partial_report?: boolean;
  report_sections?: string[];
  has_trade_plan?: boolean;
  plan_version?: number | null;
}

export interface Candle {
  time: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  sma20: number | null;
  sma50: number | null;
  sma200: number | null;
  rsi: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
}

export interface MarketChart {
  ok: boolean;
  symbol: string;
  as_of: string;
  source: string;
  download_started_at?: string;
  fetched_at: string;
  response_at?: string;
  bar_date: string;
  bar_matches_as_of?: boolean;
  bar_complete?: boolean | null;
  session?: string;
  session_note?: string | null;
  timezone?: string | null;
  cache_age_seconds?: number | null;
  cache_status?: string;
  reference_price: number;
  previous_close: number | null;
  change: number | null;
  change_percent: number | null;
  currency: string | null;
  indicators_error: string | null;
  indicator_note: string;
  candles: Candle[];
}

export interface QuoteRow {
  ticker: string;
  ok: boolean;
  source: string;
  price?: number | null;
  previous_close?: number | null;
  change?: number | null;
  change_percent?: number | null;
  bar_date?: string | null;
  fetched_at?: string | null;
  error?: string | null;
  added_at?: string;
}

export interface WatchlistResponse {
  as_of: string;
  source: string;
  items: QuoteRow[];
}

export interface SystemStatus {
  service: string;
  version: string;
  commit: string;
  openai_api_key_configured: boolean;
  configured_means: string;
  validation: {
    checked_at: string | null;
    ok: boolean | null;
    code: string;
    message: string;
  };
}

export interface PositionSizeResult {
  disclaimer: string;
  orders_sent: boolean;
  limitations: string[];
  entry_zone: TradePlan["entry_zone"];
  limit_entries: PriceLevel[];
  exits: PriceLevel[];
  invalidation: TradePlan["invalidation"];
  assumptions: string[];
  sizing: TradePlan["sizing"];
  calculated_at: string;
}
