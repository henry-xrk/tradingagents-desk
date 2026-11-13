import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell.tsx";
import { HistoryPage } from "./pages/HistoryPage.tsx";
import { OverviewPage } from "./pages/OverviewPage.tsx";
import { ResearchPage } from "./pages/ResearchPage.tsx";
import { SettingsPage } from "./pages/SettingsPage.tsx";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppShell>
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/research" element={<ResearchPage />} />
            <Route path="/research/:analysisId" element={<ResearchPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </AppShell>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
