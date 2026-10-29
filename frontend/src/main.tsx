import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "./index.css";
import { ThemeProvider } from "./ThemeProvider";
import { I18nProvider } from "./i18n/I18nProvider";
import { readLocale, setCurrentLocale } from "./i18n/locale";
import Layout from "./Layout";
import RequireAuth from "./RequireAuth";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import OutletsPage from "./pages/OutletsPage";
import OutletDetailPage from "./pages/OutletDetailPage";
import JournalistsPage from "./pages/JournalistsPage";
import JournalistDetailPage from "./pages/JournalistDetailPage";
import ClientsPage from "./pages/ClientsPage";
import ClientDetailPage from "./pages/ClientDetailPage";
import ArticlesPage from "./pages/ArticlesPage";
import ArticleDetailPage from "./pages/ArticleDetailPage";
import SettingsPage from "./pages/SettingsPage";
import CartographyPage from "./pages/CartographyPage";
import TopicsPage from "./pages/TopicsPage";
import MethodPage from "./pages/MethodPage";
import AssistantPage from "./pages/AssistantPage";
import ReportsPage from "./pages/ReportsPage";
import ReportEditorPage from "./pages/ReportEditorPage";

setCurrentLocale(readLocale());

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <I18nProvider>
      <BrowserRouter>
        <Routes>
          <Route path="login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="outlets" element={<OutletsPage />} />
            <Route path="outlets/:id" element={<OutletDetailPage />} />
            <Route path="journalists" element={<JournalistsPage />} />
            <Route path="journalists/:id" element={<JournalistDetailPage />} />
            <Route path="clients" element={<ClientsPage />} />
            <Route path="clients/:id" element={<ClientDetailPage />} />
            <Route path="articles" element={<ArticlesPage />} />
            <Route path="articles/:id" element={<ArticleDetailPage />} />
            <Route path="cartography" element={<CartographyPage />} />
            <Route path="topics" element={<TopicsPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="method" element={<MethodPage />} />
            <Route path="assistant/:id?" element={<AssistantPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="reports/:id" element={<ReportEditorPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
          </Route>
        </Routes>
      </BrowserRouter>
      </I18nProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
