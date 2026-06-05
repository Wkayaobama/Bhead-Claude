import { useEffect, useState } from 'react';
import { ArrowRight, Sparkles } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

type Hello = { message: string; count: number };

export default function App() {
  const [data, setData] = useState<Hello | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/hello')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="relative min-h-screen overflow-hidden bg-background">
      {/* Soft top-edge gradient — gives the page atmosphere without
          fighting whatever the app actually does. Replace freely. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[480px] bg-gradient-to-b from-primary/10 via-background to-background"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-32 left-1/2 -z-10 h-[420px] w-[840px] -translate-x-1/2 rounded-full bg-primary/20 blur-3xl"
      />

      <main className="container mx-auto max-w-3xl px-6 py-24 animate-fade-in">
        <Badge variant="secondary" className="mb-6 gap-1.5">
          <Sparkles className="h-3 w-3" />
          Studio starter
        </Badge>

        <h1 className="bg-gradient-to-br from-foreground to-foreground/60 bg-clip-text text-transparent">
          Your app starts here.
        </h1>

        <p className="mt-5 max-w-xl text-lg text-muted-foreground">
          React + FastAPI + a database, pre-wired and ready. Tell Studio
          what to build and it'll replace this page with the real thing.
        </p>

        <div className="mt-10">
          <Card>
            <CardHeader>
              <CardTitle>Backend handshake</CardTitle>
              <CardDescription>
                The frontend pings <code className="rounded bg-muted px-1.5 py-0.5 text-xs">/api/hello</code> and the
                backend counts the visit in the database.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {error ? (
                <p className="text-sm font-medium text-destructive">Error: {error}</p>
              ) : data ? (
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-2xl font-semibold tracking-tight">
                      {data.message}
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Visited <span className="font-medium text-foreground">{data.count}</span>{' '}
                      {data.count === 1 ? 'time' : 'times'}
                    </p>
                  </div>
                  <Button variant="outline" size="sm" className="shrink-0">
                    Refresh <ArrowRight className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Loading…</p>
              )}
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}
