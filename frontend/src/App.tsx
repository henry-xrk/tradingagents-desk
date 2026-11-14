import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell.tsx";
import { LocaleProvider } from "./i18n.tsx";
import { HistoryPage } from "./pages/HistoryPage.tsx";
import { OverviewPage } from "./pages/OverviewPage.tsx";
import { ResearchPage } from "./pages/ResearchPage.tsx";
import { SettingsPage } from "./pages/SettingsPage.tsx";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: "research", element: <ResearchPage /> },
      { path: "research/:analysisId", element: <ResearchPage /> },
      { path: "history", element: <HistoryPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);

export default function App() {
  return (
    <LocaleProvider>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </LocaleProvider>
  );
}
