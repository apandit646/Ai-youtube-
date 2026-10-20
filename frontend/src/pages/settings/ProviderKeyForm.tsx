import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { ProviderStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";

const HINTS: Record<string, string> = {
  grok: "xAI console → API keys. Use a model id your account can access.",
  openai: "platform.openai.com → API keys. Use any chat model id that supports JSON mode.",
  gemini: "Google AI Studio → API key. Use a Gemini model id (generateContent).",
};

export function ProviderKeyForm({ provider }: { provider: ProviderStatus }) {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [model, setModel] = useState(provider.model ?? "");
  const [test, setTest] = useState<{ ok: boolean; error?: string } | null>(null);
  const save = useMutation({
    mutationFn: () => api("/settings/api-keys", { method: "PUT", body: { provider: provider.provider, api_key: key, model: model || undefined } }),
    onSuccess: () => { setKey(""); toast.success(`${provider.label} saved`); qc.invalidateQueries({ queryKey: ["settings"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const saveModel = useMutation({
    mutationFn: () => api("/settings", { method: "PUT", body: { llm_models: { [provider.provider]: model } } }),
    onSuccess: () => { toast.success("Model updated"); qc.invalidateQueries({ queryKey: ["settings"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api(`/settings/api-keys/${provider.provider}`, { method: "DELETE" }),
    onSuccess: () => { toast.success("Stored key removed"); qc.invalidateQueries({ queryKey: ["settings"] }); },
  });
  const runTest = useMutation({
    mutationFn: () => api<{ ok: boolean; error?: string }>(`/settings/test-provider/${provider.provider}`, { method: "POST" }),
    onSuccess: setTest,
    onError: (e: Error) => setTest({ ok: false, error: e.message }),
  });
  const id = `key-${provider.provider}`;
  return (
    <div className="grid gap-3 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <p className="font-medium">{provider.label}</p>
        {provider.configured ? <Badge variant="success">Configured</Badge> : <Badge variant="secondary">Not configured</Badge>}
      </div>
      {provider.key_hint && <p className="text-xs text-muted-foreground">Key {provider.key_hint} (from {provider.key_source})</p>}
      <Field label="API key" htmlFor={id} hint={HINTS[provider.provider]}>
        <Input id={id} type="password" autoComplete="off" placeholder={provider.key_hint ? "Enter a new key to replace" : "Paste API key"} value={key} onChange={(e) => setKey(e.target.value)} />
      </Field>
      <Field label="Model name" htmlFor={`${id}-model`}>
        <Input id={`${id}-model`} placeholder="Required — e.g. the model id from your provider console" value={model} onChange={(e) => setModel(e.target.value)} />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={key.length < 8} loading={save.isPending} onClick={() => save.mutate()}>Save key</Button>
        <Button size="sm" variant="outline" disabled={!model || model === provider.model} loading={saveModel.isPending} onClick={() => saveModel.mutate()}>Save model</Button>
        <Button size="sm" variant="outline" disabled={!provider.configured} loading={runTest.isPending} onClick={() => runTest.mutate()}>Test</Button>
        {provider.key_source === "settings" && <Button size="sm" variant="ghost" onClick={() => remove.mutate()}>Remove</Button>}
      </div>
      {test && <p className={test.ok ? "text-xs text-emerald-700" : "text-xs text-red-700"}>{test.ok ? "Connection OK — the model returned JSON." : test.error}</p>}
    </div>
  );
}
