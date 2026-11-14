import assert from "node:assert/strict";
import test from "node:test";

import { popHistoryCursor, pushHistoryCursor } from "./historyQuery.ts";
import {
  beginPreview,
  commitPreview,
  discardSession,
  editDraft,
  editManual,
  hydrateSession,
  readSession,
  sessionDirty,
  shouldApplyPreview,
} from "./planSession.ts";
import { formForRoute, researchMode, routeIdentity } from "./researchForm.ts";

const options = {
  today: "2026-11-13",
  default_provider: "openai",
  providers: [
    {
      id: "openai",
      default_url: null,
      requires_url: false,
      models: { quick: [{ id: "quick" }], deep: [{ id: "deep" }] },
    },
  ],
};

const copied = {
  ticker: "MSFT",
  analysis_date: "2020-01-02",
  analysts: ["market"],
  research_depth: 5 as const,
  output_language: "Chinese" as const,
  llm_provider: "openai",
  quick_think_llm: "old-quick",
  deep_think_llm: "old-deep",
  backend_url: "",
};

test("a ticker parameter initializes a new form once and does not keep owning the field", () => {
  const arrived = routeIdentity("new", undefined, "", "MSFT");
  assert.equal(arrived, routeIdentity("new", undefined, "", "MSFT"));
  assert.notEqual(arrived, routeIdentity("new", undefined, "", "AAPL"));
  const form = formForRoute({ mode: "new", options, ticker: "MSFT", saved: copied });
  assert.equal(form.ticker, "MSFT");
  assert.equal(form.research_depth, 1);
  assert.equal(form.analysis_date, "2026-11-13");
  assert.equal(form.quick_think_llm, "quick");
});

test("new research and copy-from-history stay distinct", () => {
  assert.equal(researchMode(undefined, ""), "new");
  assert.equal(researchMode(undefined, "run-1"), "copy");
  assert.equal(researchMode("run-1", ""), "open");
  const fresh = formForRoute({ mode: "new", options, ticker: "AAPL", saved: copied });
  const historical = formForRoute({ mode: "copy", options, ticker: "AAPL", saved: copied });
  assert.equal(fresh.research_depth, 1);
  assert.equal(historical.research_depth, 5);
  assert.equal(historical.ticker, "MSFT");
  assert.equal(historical.output_language, "Chinese");
  assert.notEqual(routeIdentity("copy", undefined, "run-1", ""), routeIdentity("new", undefined, "", ""));
});

test("drafts stay with one research and a late preview cannot be restored", () => {
  discardSession("nvda");
  discardSession("aapl");
  hydrateSession("nvda", {
    available_capital: "100",
    available_cash: "",
    max_risk_amount: "",
    max_risk_percent: "",
    max_position_percent: "",
    cost_bps: "0",
    scale_in_prices: "",
    take_profit_prices: "",
  });
  editManual("nvda", { entry: "123.45", stop: "", target: "", action: "Buy" });
  assert.equal(readSession("nvda")?.manual.entry, "123.45");
  assert.equal(readSession("aapl"), null);
  hydrateSession("aapl", {
    available_capital: "",
    available_cash: "",
    max_risk_amount: "",
    max_risk_percent: "",
    max_position_percent: "",
    cost_bps: "0",
    scale_in_prices: "",
    take_profit_prices: "",
  });
  assert.equal(readSession("aapl")?.manual.entry, "");
  assert.equal(readSession("nvda")?.manual.entry, "123.45");
  assert.equal(sessionDirty(readSession("nvda")), true);

  const token = beginPreview("nvda");
  editDraft("nvda", { ...readSession("nvda")!.draft, available_cash: "50" });
  assert.equal(shouldApplyPreview("nvda", token), false);
  assert.equal(commitPreview("nvda", token, { sizing: { shares: 1 } }), false);
  assert.equal(readSession("nvda")?.preview, null);

  const next = beginPreview("nvda");
  assert.equal(commitPreview("nvda", next, { sizing: { shares: 4 } }), true);
  const preview = readSession("nvda")?.preview as { sizing: { shares: number } };
  assert.equal(preview.sizing.shares, 4);
  discardSession("nvda");
  discardSession("aapl");
});

test("previous history pages can be restored", () => {
  const older = pushHistoryCursor("", "", "page-2");
  const oldest = pushHistoryCursor(older.stack, older.cursor, "page-3");
  assert.deepEqual(popHistoryCursor(oldest.stack), { cursor: "page-2", stack: "-" });
  assert.deepEqual(popHistoryCursor("-"), { cursor: "", stack: "" });
});
