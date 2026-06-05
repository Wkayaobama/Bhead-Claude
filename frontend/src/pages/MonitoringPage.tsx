import { useEffect, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  BarChart2,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Globe,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Target,
  TrendingUp,
  X,
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

// ─── Types ────────────────────────────────────────────────────────────────────

interface Overview {
  total_jobs: number;
  active_targets: number;
  total_sessions: number;
  success_rate: number;
  flagged_jobs: number;
  analysed_jobs: number;
  total_documents: number;
  total_new_jobs_discovered: number;
  last_scan: string | null;
  error_sessions: number;
  completed_sessions: number;
}

interface TimelineDay { date: string; label: string; count: number; }
interface CategoryRow { category: string; count: number; }
interface TargetPerf {
  target_id: string; target_name: string; target_url: string;
  total_sessions: number; completed: number; errored: number;
  jobs_found: number; new_jobs: number; success_rate: number; last_run: string | null;
}
interface FlaggedJob {
  id: string; title: string; company: string; category: string;
  confidence_score: number; quality_flags: string[]; target_name: string; scraped_at: string;
}
interface AuditEvent {
  id: string; timestamp: string; type: string; severity: 'info' | 'warning' | 'error';
  target: string; message: string; details: Record<string, unknown>;
}
interface AnalysisResult { analyzed: number; flagged: number; clean: number; flag_rate: number; }

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  if (!iso) return 'never';
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function ScoreBar({ score }: { score: number }) {
  const color = score >= 90 ? 'bg-green-500' : score >= 70 ? 'bg-yellow-400' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${score}%` }} />
      </div>
      <span className={cn('text-xs font-semibold tabular-nums w-7 shrink-0',
        score >= 90 ? 'text-green-600' : score >= 70 ? 'text-yellow-600' : 'text-red-600')}>
        {score}
      </span>
    </div>
  );
}

const SEVERITY_STYLE = {
  info:    { badge: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',    dot: 'bg-blue-500' },
  warning: { badge: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400', dot: 'bg-yellow-500' },
  error:   { badge: 'bg-destructive/10 text-destructive', dot: 'bg-destructive' },
};

const EVENT_ICONS: Record<string, typeof Activity> = {
  scrape_start:    Zap,
  scrape_complete: CheckCircle2,
  scrape_error:    AlertTriangle,
  hallucination:   ShieldAlert,
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, icon: Icon, accent = false }: {
  label: string; value: string | number; sub?: string;
  icon: typeof Activity; accent?: boolean;
}) {
  return (
    <Card className={cn(accent && 'border-destructive/40')}>
      <CardContent className="p-4 flex items-center gap-3">
        <div className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg',
          accent ? 'bg-destructive/10' : 'bg-primary/10')}>
          <Icon className={cn('h-4 w-4', accent ? 'text-destructive' : 'text-primary')} />
        </div>
        <div className="min-w-0">
          <p className="text-xl font-semibold leading-none truncate">{value}</p>
          <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
          {sub && <p className="text-[11px] text-muted-foreground/70 mt-0.5">{sub}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function AuditRow({ event }: { event: AuditEvent }) {
  const [open, setOpen] = useState(false);
  const Icon = EVENT_ICONS[event.type] ?? Activity;
  const sty = SEVERITY_STYLE[event.severity] ?? SEVERITY_STYLE.info;
  return (
    <div className="border-b border-border/40 last:border-0">
      <button
        className="w-full flex items-start gap-3 px-3 py-2.5 hover:bg-muted/40 transition-colors text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className={cn('mt-1.5 h-2 w-2 rounded-full shrink-0', sty.dot)} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            <span className="text-xs font-medium truncate">{event.message}</span>
            <span className={cn('inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium shrink-0', sty.badge)}>
              {event.type.replace('_', ' ')}
            </span>
          </div>
          <div className="flex items-center gap-3 mt-0.5">
            <span className="text-[11px] text-muted-foreground">{timeAgo(event.timestamp)}</span>
            {event.target && <span className="text-[11px] text-muted-foreground truncate">target: {event.target}</span>}
          </div>
        </div>
        {open ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-1" />
               : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-1" />}
      </button>
      {open && Object.keys(event.details).length > 0 && (
        <div className="px-8 pb-3">
          <pre className="text-[11px] text-muted-foreground bg-muted rounded-md p-2.5 overflow-x-auto font-mono leading-relaxed">
            {JSON.stringify(event.details, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function MonitoringPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [timeline, setTimeline] = useState<TimelineDay[]>([]);
  const [categories, setCategories] = useState<CategoryRow[]>([]);
  const [targetPerf, setTargetPerf] = useState<TargetPerf[]>([]);
  const [flagged, setFlagged] = useState<FlaggedJob[]>([]);
  const [flaggedTotal, setFlaggedTotal] = useState(0);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [auditFilter, setAuditFilter] = useState<string>('all');
  const [refreshing, setRefreshing] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [ov, tl, cats, tp, fl, au] = await Promise.all([
        fetch('/api/monitor/overview').then((r) => r.ok ? r.json() : null),
        fetch('/api/monitor/timeline').then((r) => r.ok ? r.json() : []),
        fetch('/api/monitor/categories').then((r) => r.ok ? r.json() : []),
        fetch('/api/monitor/target-perf').then((r) => r.ok ? r.json() : []),
        fetch('/api/monitor/hallucinations').then((r) => r.ok ? r.json() : { jobs: [], total: 0 }),
        fetch('/api/monitor/audit?limit=80').then((r) => r.ok ? r.json() : []),
      ]);
      if (ov) setOverview(ov);
      setTimeline(tl);
      setCategories(cats);
      setTargetPerf(tp);
      setFlagged(fl.jobs ?? []);
      setFlaggedTotal(fl.total ?? 0);
      setAudit(au);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchAll();
    pollRef.current = setInterval(() => fetchAll(true), 6000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const handleRunAnalysis = async () => {
    setAnalyzing(true);
    setAnalysisResult(null);
    try {
      const res = await fetch('/api/monitor/analyze', { method: 'POST' });
      if (res.ok) {
        const result = await res.json();
        setAnalysisResult(result);
        fetchAll(true);
      }
    } finally { setAnalyzing(false); }
  };

  const handleRefresh = () => { setRefreshing(true); fetchAll(true); };

  const maxTimeline = Math.max(...timeline.map((d) => d.count), 1);
  const maxCat = Math.max(...categories.map((c) => c.count), 1);
  const filteredAudit = auditFilter === 'all' ? audit : audit.filter((e) => e.severity === auditFilter);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">

      {/* ── Header controls ──────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">
            Last scan: <span className="font-medium text-foreground">{timeAgo(overview?.last_scan ?? null)}</span>
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
          <RefreshCw className={cn('h-3.5 w-3.5 mr-1.5', refreshing && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      {/* ══ STEP 12: PERFORMANCE DASHBOARD ════════════════════════════════ */}

      {/* KPI cards */}
      {overview && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard label="Total Jobs" value={overview.total_jobs} icon={Sparkles}
            sub={`+${overview.total_new_jobs_discovered} discovered`} />
          <KpiCard label="Success Rate" value={`${overview.success_rate}%`} icon={TrendingUp}
            sub={`${overview.completed_sessions}/${overview.total_sessions} sessions`} />
          <KpiCard label="Active Sources" value={overview.active_targets} icon={Globe} />
          <KpiCard label="Flagged" value={overview.flagged_jobs} icon={ShieldAlert}
            accent={overview.flagged_jobs > 0}
            sub={overview.analysed_jobs > 0 ? `${overview.analysed_jobs} analysed` : 'run analysis below'} />
        </div>
      )}

      {/* Activity timeline + category distribution side by side */}
      <div className="grid gap-4 sm:grid-cols-2">
        {/* Timeline */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <BarChart2 className="h-4 w-4 text-primary" />
              Jobs Scraped — Last 7 Days
            </CardTitle>
          </CardHeader>
          <CardContent>
            {timeline.length === 0 ? (
              <p className="text-xs text-muted-foreground py-4 text-center">No data yet</p>
            ) : (
              <div className="flex items-end gap-1.5 h-28">
                {timeline.map((day) => (
                  <div key={day.date} className="flex-1 flex flex-col items-center gap-1 group">
                    <span className="text-[10px] text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity">
                      {day.count}
                    </span>
                    <div className="w-full flex items-end" style={{ height: '72px' }}>
                      <div
                        className="w-full rounded-t bg-primary/60 hover:bg-primary transition-colors"
                        style={{
                          height: day.count > 0 ? `${Math.max(6, (day.count / maxTimeline) * 72)}px` : '3px',
                          opacity: day.count > 0 ? 1 : 0.3,
                        }}
                      />
                    </div>
                    <span className="text-[10px] text-muted-foreground">{day.label}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Category distribution */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Target className="h-4 w-4 text-primary" />
              Category Distribution
            </CardTitle>
          </CardHeader>
          <CardContent>
            {categories.length === 0 ? (
              <p className="text-xs text-muted-foreground py-4 text-center">No data yet</p>
            ) : (
              <div className="space-y-2">
                {categories.slice(0, 7).map((cat) => (
                  <div key={cat.category} className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-20 text-right shrink-0 truncate">
                      {cat.category}
                    </span>
                    <div className="flex-1 h-3 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full bg-primary/70 rounded-full transition-all"
                        style={{ width: `${(cat.count / maxCat) * 100}%` }}
                      />
                    </div>
                    <span className="text-xs font-medium w-7 shrink-0">{cat.count}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Target performance table */}
      {targetPerf.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Activity className="h-4 w-4 text-primary" />
              Source Performance
            </CardTitle>
            <CardDescription>Per-target scan history and yield</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border/60">
                    {['Source', 'Sessions', 'Jobs found', 'New jobs', 'Success', 'Last run'].map((h) => (
                      <th key={h} className="px-4 py-2.5 text-left font-medium text-muted-foreground">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {targetPerf.map((t) => (
                    <tr key={t.target_id} className="border-b border-border/40 last:border-0 hover:bg-muted/30 transition-colors">
                      <td className="px-4 py-2.5 font-medium max-w-[160px] truncate">{t.target_name}</td>
                      <td className="px-4 py-2.5 tabular-nums">{t.total_sessions}</td>
                      <td className="px-4 py-2.5 tabular-nums">{t.jobs_found}</td>
                      <td className="px-4 py-2.5 tabular-nums font-medium text-primary">+{t.new_jobs}</td>
                      <td className="px-4 py-2.5">
                        <span className={cn('font-medium', t.success_rate >= 80 ? 'text-green-600' : t.success_rate >= 50 ? 'text-yellow-600' : 'text-destructive')}>
                          {t.success_rate}%
                        </span>
                        {t.errored > 0 && <span className="text-destructive ml-1">({t.errored} err)</span>}
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground">{timeAgo(t.last_run)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ══ STEP 13: HALLUCINATION DETECTION ══════════════════════════════ */}

      <Card className={cn(flaggedTotal > 0 && 'border-yellow-400/40')}>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <CardTitle className="text-sm flex items-center gap-2">
                <ShieldAlert className="h-4 w-4 text-yellow-500" />
                Hallucination &amp; Quality Detection
              </CardTitle>
              <CardDescription className="mt-0.5">
                Deterministic heuristics flag low-confidence AI extractions (HTML artefacts, missing fields, garbage text).
              </CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={handleRunAnalysis} disabled={analyzing}>
              {analyzing
                ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Analysing…</>
                : <><Sparkles className="h-3.5 w-3.5 mr-1.5" />Run Analysis</>}
            </Button>
          </div>
          {analysisResult && (
            <div className="mt-2 rounded-lg bg-muted px-3 py-2 text-xs flex flex-wrap gap-4">
              <span><strong>{analysisResult.analyzed}</strong> jobs checked</span>
              <span className="text-green-600"><strong>{analysisResult.clean}</strong> clean</span>
              <span className={analysisResult.flagged > 0 ? 'text-yellow-600' : ''}>
                <strong>{analysisResult.flagged}</strong> flagged ({analysisResult.flag_rate}%)
              </span>
            </div>
          )}
        </CardHeader>
        <CardContent>
          {flagged.length === 0 ? (
            <div className="flex flex-col items-center py-8 gap-2 text-center">
              <CheckCircle2 className="h-8 w-8 text-green-500/50" />
              <p className="text-sm font-medium text-muted-foreground">
                {overview?.analysed_jobs === 0
                  ? 'No analysis run yet — click Run Analysis above.'
                  : 'No low-confidence jobs detected. Looking clean!'}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground mb-3">
                {flaggedTotal} job{flaggedTotal !== 1 ? 's' : ''} flagged — confidence score below 70
              </p>
              {flagged.map((job) => (
                <div key={job.id} className="rounded-lg border border-yellow-400/30 bg-yellow-50/30 dark:bg-yellow-900/5 p-3">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="h-4 w-4 text-yellow-500 shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium truncate">{job.title || '(no title)'}</span>
                        {job.company && <span className="text-xs text-muted-foreground">@ {job.company}</span>}
                        <Badge variant="secondary" className="text-xs shrink-0">{job.category}</Badge>
                      </div>
                      <div className="mt-1.5">
                        <ScoreBar score={job.confidence_score ?? 0} />
                      </div>
                      {job.quality_flags?.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {job.quality_flags.map((flag) => (
                            <span key={flag}
                              className="inline-flex items-center gap-1 rounded-full bg-yellow-100 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-400 px-2 py-0.5 text-[11px]">
                              <X className="h-2.5 w-2.5" />{flag}
                            </span>
                          ))}
                        </div>
                      )}
                      <p className="text-[11px] text-muted-foreground mt-1.5">via {job.target_name} · {timeAgo(job.scraped_at)}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ══ STEP 14: AUDIT LOG ════════════════════════════════════════════ */}

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <CardTitle className="text-sm flex items-center gap-2">
                <Clock className="h-4 w-4 text-primary" />
                Agent Audit Log
              </CardTitle>
              <CardDescription className="mt-0.5">
                Live stream of agent actions, scrape results, errors, and quality flags.
                Auto-refreshes every 6 s.
              </CardDescription>
            </div>
            {/* Severity filter */}
            <div className="flex items-center gap-1">
              {(['all', 'info', 'warning', 'error'] as const).map((sev) => (
                <button key={sev} onClick={() => setAuditFilter(sev)}
                  className={cn('rounded-full px-2.5 py-1 text-xs font-medium transition-colors border',
                    auditFilter === sev
                      ? 'bg-primary text-primary-foreground border-primary'
                      : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground')}>
                  {sev}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {filteredAudit.length === 0 ? (
            <div className="flex flex-col items-center py-12 gap-2">
              <Activity className="h-8 w-8 text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">
                {audit.length === 0 ? 'No events yet — trigger a scan to populate the log.' : 'No events match this filter.'}
              </p>
            </div>
          ) : (
            <div className="max-h-[480px] overflow-y-auto">
              {filteredAudit.map((event) => (
                <AuditRow key={event.id} event={event} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

    </div>
  );
}
