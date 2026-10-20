import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, setUnauthorizedHandler, tokenStore } from "./api";

interface User { id: number; email: string; display_name: string }
interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const qc = useQueryClient();

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
    qc.clear();
  }, [qc]);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    api<User>("/auth/me").then(setUser).catch(() => tokenStore.clear()).finally(() => setLoading(false));
  }, [logout]);

  const finish = async (token: string) => {
    tokenStore.set(token);
    setUser(await api<User>("/auth/me"));
  };

  const login = async (email: string, password: string) => {
    const r = await api<{ access_token: string }>("/auth/login", { method: "POST", body: { email, password } });
    await finish(r.access_token);
  };
  const register = async (email: string, password: string, display_name: string) => {
    const r = await api<{ access_token: string }>("/auth/register", { method: "POST", body: { email, password, display_name } });
    await finish(r.access_token);
  };

  return <AuthContext.Provider value={{ user, loading, login, register, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
