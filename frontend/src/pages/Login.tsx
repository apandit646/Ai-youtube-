import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Music4 } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Alert } from "@/components/ui/misc";

export default function Login() {
  const { login, register } = useAuth();
  const status = useQuery({ queryKey: ["setup-status"], queryFn: () => api<{ needs_owner: boolean }>("/auth/setup-status") });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const creating = status.data?.needs_owner;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (creating && password.length < 10) return setError("Use at least 10 characters for the password.");
    setBusy(true);
    try {
      if (creating) await register(email, password, name);
      else await login(email, password);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center bg-gradient-to-br from-violet-100 via-background to-amber-50 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="items-center text-center">
          <div className="mb-2 grid h-12 w-12 place-items-center rounded-xl bg-primary"><Music4 className="h-6 w-6 text-white" /></div>
          <CardTitle className="text-xl">{creating ? "Create the owner account" : "Sign in to RhymePilot AI"}</CardTitle>
          <CardDescription>{creating ? "This first account controls the channel. Registration closes afterwards." : "Original Hindi & English rhyme videos, end to end."}</CardDescription>
        </CardHeader>
        <CardContent>
          {status.isError && <Alert variant="error" className="mb-4">Cannot reach the API. Check that the backend container is running.</Alert>}
          <form onSubmit={submit} className="grid gap-4">
            {creating && (
              <Field label="Display name" htmlFor="name"><Input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></Field>
            )}
            <Field label="Email" htmlFor="email"><Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></Field>
            <Field label="Password" htmlFor="password" hint={creating ? "Minimum 10 characters." : undefined}>
              <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={creating ? "new-password" : "current-password"} />
            </Field>
            {error && <Alert variant="error">{error}</Alert>}
            <Button type="submit" loading={busy} disabled={status.isLoading}>{creating ? "Create account" : "Sign in"}</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
