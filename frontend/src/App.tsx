import { useState } from 'react';
import { Bot, Briefcase, Clock, FileText, Globe, Radar } from 'lucide-react';

import { cn } from '@/lib/utils';
import AgentConfigPage from '@/pages/AgentConfigPage';
import DocumentsPage from '@/pages/DocumentsPage';
import JobFeedPage from '@/pages/JobFeedPage';
import SessionsPage from '@/pages/SessionsPage';
import TargetsPage from '@/pages/TargetsPage';

type Tab = 'feed' | 'targets' | 'agent' | 'sessions' | 'docs';

const TABS: { id: Tab; label: string; icon: typeof Briefcase }[] = [
  { id: 'feed',     label: 'Job Feed',     icon: Briefcase  },
  { id: 'targets',  label: 'URL Manager',  icon: Globe      },
  { id: 'agent',    label: 'Agent Config', icon: Bot        },
  { id: 'sessions', label: 'Sessions',     icon: Clock      },
  { id: 'docs',     label: 'Documents',    icon: FileText   },
];

const HERO: Record<Tab, { title: string; sub: string }> = {
  feed:     { title: 'Job Intelligence Feed',   sub: 'AI-categorised job postings scraped from your configured sources.' },
  targets:  { title: 'URL Manager',             sub: 'Configure job board sources, per-target goals, and cron schedules.' },
  agent:    { title: 'Agent Configuration',     sub: 'Shape the AI system prompt, domain focus, and per-target objectives.' },
  sessions: { title: 'Agent Session Monitor',   sub: 'Live log of every scrape run — prompts used, results, and errors.' },
  docs:     { title: 'Document Library',        sub: 'Upload interview documents per job and prep with the AI coach.' },
};

export default function App() {
  const [tab, setTab] = useState<Tab>('feed');
  const [docsJobFilter, setDocsJobFilter] = useState<string | null>(null);

  const handleOpenDocs = (jobId: string) => {
    setDocsJobFilter(jobId);
    setTab('docs');
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-background">
      {/* Gradient atmosphere */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-64 bg-gradient-to-b from-primary/10 via-background to-background" />
      <div aria-hidden className="pointer-events-none absolute -top-24 left-1/2 -z-10 h-96 w-[700px] -translate-x-1/2 rounded-full bg-primary/15 blur-3xl" />

      {/* Nav */}
      <header className="sticky top-0 z-20 border-b border-border/60 bg-background/80 backdrop-blur-md">
        <div className="container mx-auto max-w-5xl px-6">
          <div className="flex h-14 items-center justify-between gap-4">
            <div className="flex items-center gap-2.5 shrink-0">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary">
                <Radar className="h-4 w-4 text-primary-foreground" />
              </div>
              <span className="font-semibold text-sm tracking-tight">HR Scout</span>
            </div>
            <nav className="flex items-center gap-0.5 overflow-x-auto">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap',
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
        <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-br from-foreground to-foreground/60 bg-clip-text text-transparent">
          {HERO[tab].title}
        </h1>
        <p className="mt-1.5 text-muted-foreground">{HERO[tab].sub}</p>
      </div>

      {/* Page content */}
      <main className="container mx-auto max-w-5xl px-6 pb-16">
        {tab === 'feed'     && <JobFeedPage onOpenDocs={handleOpenDocs} />}
        {tab === 'targets'  && <TargetsPage />}
        {tab === 'agent'    && <AgentConfigPage />}
        {tab === 'sessions' && <SessionsPage />}
        {tab === 'docs'     && <DocumentsPage initialJobId={docsJobFilter} />}
      </main>
    </div>
  );
}
