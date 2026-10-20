import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CheckCircle2, Circle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { SettingsResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/input";
import { Alert } from "@/components/ui/misc";
import { ProviderKeyForm } from "./settings/ProviderKeyForm";
import { YouTubeConnection } from "./settings/YouTubeConnection";

export function SetupWizard({ data }: { data: SettingsResponse }) {
  const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const [language, setLanguage] = useState(data.settings.default_language);
  const [format, setFormat] = useState(data.settings.default_format);
  const finish = useMutation({
    mutationFn: () => api("/settings", { method: "PUT", body: { setup_completed: true, default_language: language, default_format: format } }),
    onSuccess: () => { toast.success("Setup complete"); qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const steps = ["AI models", "YouTube", "Defaults"];
  const anyAI = data.providers.some((p) => p.configured);
  return (
    <Card className="mb-6 border-primary/30">
      <CardHeader>
        <CardTitle>Welcome! Let's set up your studio</CardTitle>
        <CardDescription>Three quick steps. You can change everything later in Settings.</CardDescription>
        <ol className="mt-3 flex flex-wrap gap-4 text-sm">
          {steps.map((s, i) => (
            <li key={s}><button className="inline-flex items-center gap-1.5" onClick={() => setStep(i)} aria-current={i === step}>
              {i < step ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <Circle className={i === step ? "h-4 w-4 text-primary" : "h-4 w-4 text-muted-foreground"} />}
              <span className={i === step ? "font-medium" : "text-muted-foreground"}>{s}</span></button></li>
          ))}
        </ol>
      </CardHeader>
      <CardContent className="grid gap-4">
        {step === 0 && (
          <>
            <p className="text-sm text-muted-foreground">Add at least one model. Grok is the primary creative model; ChatGPT and Gemini act as fallbacks and independent reviewers. Keys are encrypted on the server and never sent back to the browser.</p>
            <div className="grid gap-4 lg:grid-cols-3">{data.providers.map((p) => <ProviderKeyForm key={p.provider} provider={p} />)}</div>
            {!anyAI && <Alert variant="warning">Without an AI model, the studio uses clearly-labelled local fallback templates.</Alert>}
          </>
        )}
        {step === 1 && <YouTubeConnection />}
        {step === 2 && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Default language" htmlFor="wl"><Select id="wl" value={language} onChange={(e) => setLanguage(e.target.value as typeof language)}>
              <option value="hi">Hindi</option><option value="en">English</option><option value="bilingual">Bilingual</option></Select></Field>
            <Field label="Default format" htmlFor="wf"><Select id="wf" value={format} onChange={(e) => setFormat(e.target.value as typeof format)}>
              <option value="short">YouTube Short (9:16)</option><option value="long">Long-form (16:9)</option></Select></Field>
            <Alert className="sm:col-span-2">Dry-run mode is ON by default: nothing is uploaded until you turn it off and complete a private test upload.</Alert>
          </div>
        )}
        <div className="flex justify-between">
          <Button variant="ghost" disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
          {step < 2 ? <Button onClick={() => setStep(step + 1)}>Next</Button> : <Button loading={finish.isPending} onClick={() => finish.mutate()}>Finish setup</Button>}
        </div>
      </CardContent>
    </Card>
  );
}
