import { useState } from 'react';
import { Briefcase, Globe, Radar } from 'lucide-react';

import { cn } from '@/lib/utils';
import JobFeedPage from '@/pages/JobFeedPage';
import TargetsPage from '@/pages/TargetsPage';

type Tab = 'feed' | 'targets';

const TABS: { id: Tab; label: string; icon: typeof Briefcase }[] = [
  { id: 'feed', label: 'Job Feed', icon: Briefcase },
  { id: 'targets', label: 'URL Manager', icon: Globe },
];

export default function App() {
  const [tab, setTab] = useState<Tab>('feed');

  return (
    <div className="relative min-h-screen overflow-hidden bg-background">
      {/* Gradient atmosphere */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-64 bg-gradient-to-b from-primary/10 via-background to-background"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-24 left-1/2 -z-10 h-96 w-[700px] -translate-x-1/2 rounded-full bg-primary/15 blur-3xl"
      />

      {/* Nav */}
      <header className="sticky top-0 z-20 border-b border-border/60 bg-background/80 backdrop-blur-md">
        <div className="container mx-auto max-w-5xl px-6">
          <div className="flex h-14 items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary">
                <Radar className="h-4 w-4 text-primary-foreground" />
              </div>
              <span className="font-semibold text-sm tracking-tight">HR Scout</span>
            </div>

            {/* Tabs */}
            <nav className="flex items-center gap-1">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                    tab === id
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </button>
              ))}
            </nav>
          </div>
        </div>
      </header>

      {/* Hero */}
      <div className="container mx-auto max-w-5xl px-6 pt-12 pb-8">
        <div className="space-y-1.5">
          <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-br from-foreground to-foreground/60 bg-clip-text text-transparent">
            {tab === 'feed' ? 'Job Intelligence Feed' : 'Scrape Target Manager'}
          </h1>
          <p className="text-muted-foreground">
            {tab === 'feed'
              ? 'AI-categorised job postings scraped from your configured sources.'
              : 'Manage the job board URLs HR Scout monitors for new postings.'}
          </p>
        </div>
      </div>

      {/* Page content */}
      <main className="container mx-auto max-w-5xl px-6 pb-16">
        {tab === 'feed' ? <JobFeedPage /> : <TargetsPage />}
      </main>
    </div>
  );
}
