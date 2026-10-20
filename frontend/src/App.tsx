import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { Layout } from "@/components/Layout";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";

const Research = lazy(() => import("@/pages/Research"));
const Content = lazy(() => import("@/pages/Content"));
const ScriptEditor = lazy(() => import("@/pages/ScriptEditor"));
const Videos = lazy(() => import("@/pages/Videos"));
const CalendarPage = lazy(() => import("@/pages/Calendar"));
const Analytics = lazy(() => import("@/pages/Analytics"));
const Settings = lazy(() => import("@/pages/Settings"));

const Spinner = () => <div className="grid min-h-[50vh] place-items-center"><Loader2 className="h-6 w-6 animate-spin text-primary" aria-label="Loading" /></div>;

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!user) return <Login />;
  return (
    <Suspense fallback={<Spinner />}>
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="research" element={<Research />} />
        <Route path="content" element={<Content />} />
        <Route path="content/:id" element={<ScriptEditor />} />
        <Route path="videos" element={<Videos />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
    </Suspense>
  );
}
