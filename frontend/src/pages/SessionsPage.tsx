import { useEffect, useState } from 'react';
import {
  Activity,
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Loader2,
  RefreshCw,
  Target,
  Trash2,
  Zap,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface Session {
  id: string;
  target_id: string;
  target_name: string;
  target_url: string;
  started_at: string;
  completed_at: string | null;
  status: 'running' | 'completed' | 'error';
  prompt_used: string;
  domain_focus: string[];
  target_goal: string;
  jobs_found: number;
  new_jobs: number;
  error: string | null;
  triggered_by: 'manual' | 'cron';
}

interface Stats {
  total: number;
  completed: number;
  errors: number;
  cron_runs: number;
  manual_runs: number;
  total_new_jobs: number;
  success_rate: number;
}

function StatusChip({ status }: { status: Session['status'] }) {
  const map = {
    running: { label: 'Running', icon: Loader2, cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
    completed: { label: 'Completed', icon: CheckCircle2, cls: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
    error: { label: 'Error', icon: AlertCircle, cls: 'bg-destructive/10 text-destructive' },
  } as const;
  const { label, icon: Icon, cls } = map[status] ?? map.running;
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', cls)}>
      <Icon className={cn('h-3 w-3', status === 'running' && 'animate-spin')} />
      {label}
    </span>
  );
}

function TriggerChip({ by }: { by: string }) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
      by === 'cron'
        ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
        : 'bg-muted text-muted-foreground'
    )}>
      {by === 'cron' ? <Clock className="h-3 w-3" /> : <Zap className="h-3 w-3" />}
      {by === 'cron' ? 'Scheduled' : 'Manual'}
    </span>
  );
}

function duration(start: string, end: string | null): string {
  if (!end) return '…';
  const ms = new Date(end).getTime() - new Date(start).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function SessionRow({ session, onDelete }: { session: Session; onDelete: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Card className={cn('transition-shadow', session.status === 'error' && 'border-destructive/30')}>
      <CardContent className="p-0">
        {/* Summary row */}
        <button
          className="w-full text-left p-4 flex items-start gap-3 hover:bg-muted/40 transition-colors rounded-xl"
          onClick={() => setExpanded((v) => !v)}
        >
          <div className={cn(
            'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
            session.status === 'error' ? 'bg-destructive/10' : 'bg-primary/10'
          )}>
            <Bot className={cn('h-4 w-4', session.status === 'error' ? 'text-destructive' : 'text-primary')} />
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-sm">{session.target_name || 'Unknown target'}</span>
              <StatusChip status={session.status} />
              <TriggerChip by={session.triggered_by} />
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1.5">
              <span className="text-xs text-muted-foreground">{timeAgo(session.started_at)}</span>
              <span className="text-xs text-muted-foreground">
                Duration: {duration(session.started_at, session.completed_at)}
              </span>
              {session.status === 'completed' && (
                <>
                  <span className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{session.jobs_found}</span> jobs found
                  </span>
                  <span className="text-xs text-green-600 dark:text-green-400 font-medium">
                    +{session.new_jobs} new
                  </span>
                </>
              )}
              {session.status === 'error' && session.error && (
                <span className="text-xs text-destructive truncate max-w-xs">{session.error}</span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0 ml-2">
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(session.id); }}
              className="text-muted-foreground hover:text-destructive transition-colors p-1 rounded"
              title="Delete session"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
            {expanded
              ? <ChevronDown className="h-4 w-4 text-muted-foreground" />
              : <ChevronRight className="h-4 w-4 text-muted-foreground" />
            }
          </div>
        </button>

        {/* Expanded detail — prompt used */}
        {expanded && (
          <div className="border-t border-border/60 px-4 pb-4 pt-3 space-y-3 animate-fade-in">
            {session.domain_focus?.length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1.5">Domain focus</p>
                <div className="flex flex-wrap gap-1.5">
                  {session.domain_focus.map((d) => (
                    <Badge key={d} variant="secondary" className="text-xs">{d}</Badge>
                  ))}
                </div>
              </div>
            )}
            {session.target_goal && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1">Target goal</p>
                <p className="text-xs text-foreground bg-muted rounded-md px-3 py-2">{session.target_goal}</p>
              </div>
            )}
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1.5">System prompt used</p>
              <pre className="text-xs bg-muted text-muted-foreground rounded-md p-3 whitespace-pre-wrap font-mono leading-relaxed max-h-48 overflow-y-auto">
                {session.prompt_used}
              </pre>
            </div>
            {session.error && (
              <div>
                <p className="text-xs font-medium text-destructive mb-1">Error</p>
                <p className="text-xs bg-destructive/10 text-destructive rounded-md px-3 py-2 font-mono">
                  {session.error}
                </p>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const fetchAll = async (showLoader = false) => {
    if (showLoader) setLoading(true);
    try {
      const [sessRes, statsRes] = await Promise.all([
        fetch('/api/sessions?limit=50'),
        fetch('/api/sessions/stats'),
      ]);
      if (sessRes.ok) {
        const d = await sessRes.json();
        setSessions(d.sessions);
        setTotal(d.total);
      }
      if (statsRes.ok) setStats(await statsRes.json());
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchAll(true);
    // Auto-refresh while any session is running
    const id = setInterval(() => fetchAll(), 4000);
    return () => clearInterval(id);
  }, []);

  const handleDelete = async (id: string) => {
    await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
    setSessions((prev) => prev.filter((s) => s.id !== id));
    setTotal((t) => t - 1);
  };

  const handleClearAll = async () => {
    if (!confirm('Delete all session logs? This cannot be undone.')) return;
    await fetch('/api/sessions', { method: 'DELETE' });
    setSessions([]);
    setTotal(0);
    fetchAll();
  };

  const handleRefresh = () => { setRefreshing(true); fetchAll(); };

  const statCards = stats
    ? [
        { label: 'Total runs', value: stats.total, icon: Activity },
        { label: 'Success rate', value: `${stats.success_rate}%`, icon: CheckCircle2 },
        { label: 'New jobs found', value: stats.total_new_jobs, icon: Target },
        { label: 'Scheduled runs', value: stats.cron_runs, icon: Clock },
      ]
    : [];

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Session Monitor</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Live log of every agent scrape run — prompts used, results, and errors.
          </p>
        </div>
        <div className="flex gap-2">
          {sessions.length > 0 && (
            <Button variant="outline" size="sm" onClick={handleClearAll} className="text-destructive hover:bg-destructive/10">
              <Trash2 className="h-3.5 w-3.5 mr-1.5" />
              Clear all
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
            <RefreshCw className={cn('h-3.5 w-3.5 mr-1.5', refreshing && 'animate-spin')} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Stats strip */}
      {stats && stats.total > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {statCards.map(({ label, value, icon: Icon }) => (
            <Card key={label}>
              <CardContent className="p-3 flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 shrink-0">
                  <Icon className="h-3.5 w-3.5 text-primary" />
                </div>
                <div>
                  <p className="text-lg font-semibold leading-none">{value}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Session list */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : sessions.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16 gap-3">
            <Bot className="h-10 w-10 text-muted-foreground/40" />
            <p className="font-medium text-sm">No sessions yet</p>
            <p className="text-xs text-muted-foreground text-center max-w-xs">
              Trigger a scan from the URL Manager or enable a cron schedule. Each run will appear here.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            Showing {sessions.length} of {total} session{total !== 1 ? 's' : ''} — click a row to see the prompt used
          </p>
          <div className="space-y-2">
            {sessions.map((s) => (
              <SessionRow key={s.id} session={s} onDelete={handleDelete} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
