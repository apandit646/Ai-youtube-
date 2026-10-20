import { NavLink, Outlet } from "react-router-dom";
import { BarChart3, CalendarDays, Clapperboard, LayoutDashboard, LogOut, Menu, Music4, Search, Settings, Sparkles } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/research", label: "Research Studio", icon: Search },
  { to: "/content", label: "Content Studio", icon: Sparkles },
  { to: "/videos", label: "Video Library", icon: Clapperboard },
  { to: "/calendar", label: "Publishing Calendar", icon: CalendarDays },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Layout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded focus:bg-card focus:p-2">Skip to content</a>
      <aside className={cn("fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-sidebar text-sidebar-foreground transition-transform md:static md:translate-x-0", open ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex items-center gap-2 px-5 py-5">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-primary"><Music4 className="h-5 w-5 text-white" aria-hidden /></div>
          <div>
            <p className="font-semibold leading-tight text-white">RhymePilot AI</p>
            <p className="text-xs text-sidebar-foreground/60">Kids rhyme studio</p>
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-3" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}
              className={({ isActive }) => cn("flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors", isActive ? "bg-white/10 font-medium text-white" : "text-sidebar-foreground/75 hover:bg-white/5 hover:text-white")}>
              <Icon className="h-4 w-4" aria-hidden />{label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-white/10 p-4 text-sm">
          <p className="truncate text-sidebar-foreground/80">{user?.email}</p>
          <button onClick={logout} className="mt-2 inline-flex items-center gap-2 text-sidebar-foreground/70 hover:text-white"><LogOut className="h-4 w-4" />Sign out</button>
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setOpen(false)} aria-hidden />}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b bg-card px-4 py-3 md:hidden">
          <button onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
          <span className="font-semibold">RhymePilot AI</span>
        </header>
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-8"><Outlet /></main>
      </div>
    </div>
  );
}
