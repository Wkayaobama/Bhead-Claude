import { useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Globe,
  Loader2,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Target,
  Trash2,
  Wand2,
  X,
  Zap,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

interface ScrapeTarget {
  id: string;
  url: string;
  name: string;
  description: string;
  active: boolean;
  goal: string;
  cron_enabled: boolean;
  cron_interval_minutes: number;
  cron_next_run: string | null;
  status: 'idle' | 'running' | 'completed' | 'error';
  scrape_count: number;
  job_count: number;
  last_scraped_at: string | null;
  last_error: string | null;
  created_at: string;
}

interface CronInterval { minutes: number; label: string; }

interface FormState {
  url: string;
  name: string;
  description: string;
  goal: string;
  active: boolean;
  cron_enabled: boolean;
  cron_interval_minutes: number;
}

const defaultForm: FormState = {
  url: '', name: '', description: '', goal: '',
  active: true, cron_enabled: false, cron_interval_minutes: 1440,
};

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0',
        checked ? 'bg-primary' : 'bg-muted'
      )}
    >
      <span className={cn(
        'inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform',
        checked ? 'translate-x-4' : 'translate-x-1'
      )} />
    </button>
  );
}

function isJobupUrl(url: string): boolean {
  return url.toLowerCase().includes('jobup.ch');
}

function ApifyBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
      <Zap className="h-3 w-3" />
      Apify leaf-pages
    </span>
  );
}

function StatusBadge({ status }: { status: ScrapeTarget['status'] }) {
  const map = {
    idle: { label: 'Idle', icon: Clock, cls: 'bg-muted text-muted-foreground' },
    running: { label: 'Scanning…', icon: Loader2, cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
    completed: { label: 'Done', icon: CheckCircle2, cls: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
    error: { label: 'Error', icon: AlertCircle, cls: 'bg-destructive/10 text-destructive' },
  } as const;
  const { label, icon: Icon, cls } = map[status] ?? map.idle;
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium', cls)}>
      <Icon className={cn('h-3 w-3', status === 'running' && 'animate-spin')} />
      {label}
    </span>
  );
}

function countdownLabel(isoNext: string | null): string {
  if (!isoNext) return '';
  const diff = new Date(isoNext).getTime() - Date.now();
  if (diff <= 0) return 'due now';
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return `in ${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `in ${hrs}h ${mins % 60}m`;
  return `in ${Math.floor(hrs / 24)}d`;
}

export default function TargetsPage() {
  const [targets, setTargets] = useState<ScrapeTarget[]>([]);
  const [intervals, setIntervals] = useState<CronInterval[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(defaultForm);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [scrapingIds, setScrapingIds] = useState<Set<string>>(new Set());

  const fetchTargets = async () => {
    try {
      const res = await fetch('/api/targets');
      if (res.ok) setTargets(await res.json());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTargets();
    fetch('/api/targets/cron-intervals')
      .then((r) => r.ok ? r.json() : [])
      .then(setIntervals);
    const id = setInterval(fetchTargets, 3000);
    return () => clearInterval(id);
  }, []);

  const openAdd = () => { setEditId(null); setForm(defaultForm); setFormError(null); setShowForm(true); };
  const openEdit = (t: ScrapeTarget) => {
    setEditId(t.id);
    setForm({ url: t.url, name: t.name, description: t.description, goal: t.goal || '',
      active: t.active, cron_enabled: t.cron_enabled || false,
      cron_interval_minutes: t.cron_interval_minutes || 1440 });
    setFormError(null); setShowForm(true);
  };
  const closeForm = () => { setShowForm(false); setEditId(null); setForm(defaultForm); setFormError(null); };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.url.trim() || !form.name.trim()) { setFormError('URL and Name are required.'); return; }
    setSubmitting(true); setFormError(null);
    try {
      const method = editId ? 'PUT' : 'POST';
      const url = editId ? `/api/targets/${editId}` : '/api/targets';
      const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Request failed'); }
      closeForm(); fetchTargets();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : 'An error occurred.');
    } finally { setSubmitting(false); }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this target and all its job postings?')) return;
    await fetch(`/api/targets/${id}`, { method: 'DELETE' }); fetchTargets();
  };

  const handleScrape = async (id: string) => {
    setScrapingIds((s) => new Set(s).add(id));
    try {
      const res = await fetch(`/api/scraper/run/${id}`, { method: 'POST' });
      if (!res.ok) { const err = await res.json(); alert(err.detail || 'Scrape failed to start.'); }
      else fetchTargets();
    } finally {
      setScrapingIds((s) => { const n = new Set(s); n.delete(id); return n; });
    }
  };

  const handleScrapeAll = async () => { await fetch('/api/scraper/run-all', { method: 'POST' }); fetchTargets(); };

  const fmt = (iso: string | null) => iso
    ? new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '—';

  const intervalLabel = (mins: number) =>
    intervals.find((i) => i.minutes === mins)?.label ?? `Every ${mins}m`;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">URL Manager</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Add job board URLs, set per-target goals, and configure automated scan schedules.
          </p>
        </div>
        <div className="flex gap-2">
          {targets.some((t) => t.active) && (
            <Button variant="outline" size="sm" onClick={handleScrapeAll}>
              <RefreshCw className="h-4 w-4 mr-1.5" />Scan All
            </Button>
          )}
          <Button size="sm" onClick={openAdd}>
            <Plus className="h-4 w-4 mr-1.5" />Add URL
          </Button>
        </div>
      </div>

      {/* Form */}
      {showForm && (
        <Card className="border-primary/40 shadow-md">
          <CardContent className="pt-5 pb-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-sm">{editId ? 'Edit Target' : 'Add New Target'}</h3>
              <button onClick={closeForm} className="text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="f-name">Label *</Label>
                  <Input id="f-name" placeholder="e.g. LinkedIn Engineering" value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="f-url">URL *</Label>
                  <Input id="f-url" placeholder="https://jobs.example.com" value={form.url}
                    onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))} />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="f-desc">Description</Label>
                <Input id="f-desc" placeholder="Optional notes" value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
              </div>

              {/* Apify info banner — shown when URL is a jobup.ch URL */}
              {isJobupUrl(form.url) && (
                <div className="flex items-start gap-2.5 rounded-lg border border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/30 px-4 py-3">
                  <Zap className="h-4 w-4 text-emerald-600 dark:text-emerald-400 mt-0.5 shrink-0" />
                  <div className="text-xs text-emerald-800 dark:text-emerald-300">
                    <span className="font-semibold">Apify scraper detected.</span>{' '}
                    This source will be scraped via the Apify jobup.ch actor — each
                    individual job posting (leaf page) is fetched by ID for rich,
                    structured data. Make sure{' '}
                    <span className="font-mono font-medium">APIFY_API_KEY</span> is
                    configured in your app settings.
                  </div>
                </div>
              )}
              {/* Goal field — step 8 */}
              <div className="space-y-1.5">
                <Label htmlFor="f-goal" className="flex items-center gap-1.5">
                  <Target className="h-3.5 w-3.5 text-primary" />
                  Target Goal
                </Label>
                <Input id="f-goal"
                  placeholder="e.g. Senior backend engineers in fintech with 5+ yrs experience"
                  value={form.goal}
                  onChange={(e) => setForm((f) => ({ ...f, goal: e.target.value }))} />
                <p className="text-xs text-muted-foreground">
                  Injected into the AI prompt to focus extraction for this source.
                </p>
              </div>

              {/* Cron settings — step 5 */}
              <div className="rounded-lg border border-border/60 p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <Toggle checked={form.cron_enabled} onChange={(v) => setForm((f) => ({ ...f, cron_enabled: v }))} />
                  <div>
                    <span className="text-sm font-medium">Automated scanning</span>
                    <p className="text-xs text-muted-foreground">
                      {form.cron_enabled ? 'Cron is ON — this URL will be scanned automatically.' : 'Enable to scan this URL on a schedule.'}
                    </p>
                  </div>
                </div>
                {form.cron_enabled && (
                  <div className="space-y-1.5 pt-1">
                    <Label htmlFor="f-interval">Scan frequency</Label>
                    <div className="flex flex-wrap gap-2">
                      {intervals.map((opt) => (
                        <button
                          key={opt.minutes}
                          type="button"
                          onClick={() => setForm((f) => ({ ...f, cron_interval_minutes: opt.minutes }))}
                          className={cn(
                            'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                            form.cron_interval_minutes === opt.minutes
                              ? 'bg-primary text-primary-foreground border-primary'
                              : 'border-border text-muted-foreground hover:border-primary/50 hover:text-foreground'
                          )}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2">
                <Toggle checked={form.active} onChange={(v) => setForm((f) => ({ ...f, active: v }))} />
                <span className="text-sm text-muted-foreground">
                  {form.active ? 'Active — included in scan-all' : 'Inactive — skipped in scan-all'}
                </span>
              </div>

              {formError && (
                <p className="text-sm text-destructive flex items-center gap-1.5">
                  <AlertCircle className="h-3.5 w-3.5" />{formError}
                </p>
              )}
              <div className="flex gap-2 justify-end">
                <Button type="button" variant="ghost" size="sm" onClick={closeForm}>Cancel</Button>
                <Button type="submit" size="sm" disabled={submitting}>
                  {submitting && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
                  {editId ? 'Save Changes' : 'Add Target'}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Target list */}
      {loading ? (
        <div className="flex items-center justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
      ) : targets.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16 gap-3">
            <Globe className="h-10 w-10 text-muted-foreground/40" />
            <p className="text-muted-foreground text-sm">No targets yet.</p>
            <Button size="sm" variant="outline" onClick={openAdd}><Plus className="h-4 w-4 mr-1.5" />Add your first URL</Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {targets.map((t) => (
            <Card key={t.id} className={cn('transition-shadow hover:shadow-md', !t.active && 'opacity-60')}>
              <CardContent className="p-4">
                <div className="flex items-start gap-4">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                    <Globe className="h-4 w-4 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm">{t.name}</span>
                      <StatusBadge status={t.status ?? 'idle'} />
                      {isJobupUrl(t.url) && <ApifyBadge />}
                      {t.cron_enabled && (
                        <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                          <Clock className="h-3 w-3" />
                          {intervalLabel(t.cron_interval_minutes)}
                          {t.cron_next_run && (
                            <span className="opacity-75 ml-0.5">· {countdownLabel(t.cron_next_run)}</span>
                          )}
                        </span>
                      )}
                      {!t.active && <Badge variant="secondary" className="text-xs">Inactive</Badge>}
                    </div>
                    <a href={t.url} target="_blank" rel="noopener noreferrer"
                      className="text-xs text-muted-foreground hover:text-primary truncate block mt-0.5">{t.url}</a>
                    {t.goal && (
                      <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                        <Target className="h-3 w-3 text-primary shrink-0" />
                        <span className="italic">{t.goal}</span>
                      </p>
                    )}
                    {t.last_error && (
                      <p className="text-xs text-destructive mt-1 flex items-center gap-1">
                        <AlertCircle className="h-3 w-3" />{t.last_error}
                      </p>
                    )}
                    <div className="flex items-center gap-4 mt-2">
                      <span className="text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">{t.job_count ?? 0}</span> jobs
                      </span>
                      <span className="text-xs text-muted-foreground">Last scan: {fmt(t.last_scraped_at)}</span>
                      {t.scrape_count > 0 && (
                        <span className="text-xs text-muted-foreground">{t.scrape_count} scans total</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Button variant="outline" size="icon" className="h-7 w-7" title="Scan now"
                      onClick={() => handleScrape(t.id)}
                      disabled={t.status === 'running' || scrapingIds.has(t.id)}>
                      {t.status === 'running' || scrapingIds.has(t.id)
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        : <Play className="h-3.5 w-3.5" />}
                    </Button>
                    <Button variant="outline" size="icon" className="h-7 w-7" title="Edit" onClick={() => openEdit(t)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button variant="outline" size="icon" className="h-7 w-7 text-destructive hover:bg-destructive/10"
                      title="Delete" onClick={() => handleDelete(t.id)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
