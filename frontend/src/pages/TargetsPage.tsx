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
  Trash2,
  X,
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

interface ScrapeTarget {
  id: string;
  url: string;
  name: string;
  description: string;
  active: boolean;
  status: 'idle' | 'running' | 'completed' | 'error';
  scrape_count: number;
  job_count: number;
  last_scraped_at: string | null;
  last_error: string | null;
  created_at: string;
}

interface FormState {
  url: string;
  name: string;
  description: string;
  active: boolean;
}

const defaultForm: FormState = { url: '', name: '', description: '', active: true };

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

export default function TargetsPage() {
  const [targets, setTargets] = useState<ScrapeTarget[]>([]);
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
      if (!res.ok) throw new Error(await res.text());
      const data: ScrapeTarget[] = await res.json();
      setTargets(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTargets();
    // Poll every 3s while any target is running
    const interval = setInterval(() => {
      fetchTargets();
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const openAdd = () => {
    setEditId(null);
    setForm(defaultForm);
    setFormError(null);
    setShowForm(true);
  };

  const openEdit = (t: ScrapeTarget) => {
    setEditId(t.id);
    setForm({ url: t.url, name: t.name, description: t.description, active: t.active });
    setFormError(null);
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditId(null);
    setForm(defaultForm);
    setFormError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.url.trim() || !form.name.trim()) {
      setFormError('URL and Name are required.');
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const method = editId ? 'PUT' : 'POST';
      const url = editId ? `/api/targets/${editId}` : '/api/targets';
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Request failed');
      }
      closeForm();
      fetchTargets();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : 'An error occurred.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this target and all its job postings?')) return;
    await fetch(`/api/targets/${id}`, { method: 'DELETE' });
    fetchTargets();
  };

  const handleScrape = async (id: string) => {
    setScrapingIds((s) => new Set(s).add(id));
    try {
      const res = await fetch(`/api/scraper/run/${id}`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || 'Scrape failed to start.');
      } else {
        fetchTargets();
      }
    } finally {
      setScrapingIds((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
    }
  };

  const handleScrapeAll = async () => {
    await fetch('/api/scraper/run-all', { method: 'POST' });
    fetchTargets();
  };

  const formatDate = (iso: string | null) => {
    if (!iso) return '—';
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">URL Manager</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Add and manage job board URLs for automated scanning.
          </p>
        </div>
        <div className="flex gap-2">
          {targets.some((t) => t.active) && (
            <Button variant="outline" size="sm" onClick={handleScrapeAll}>
              <RefreshCw className="h-4 w-4 mr-1.5" />
              Scan All
            </Button>
          )}
          <Button size="sm" onClick={openAdd}>
            <Plus className="h-4 w-4 mr-1.5" />
            Add URL
          </Button>
        </div>
      </div>

      {/* Inline form */}
      {showForm && (
        <Card className="border-primary/40 shadow-md">
          <CardHeader className="pb-2 flex flex-row items-center justify-between">
            <CardTitle className="text-base">
              {editId ? 'Edit Target' : 'Add New Target'}
            </CardTitle>
            <button onClick={closeForm} className="text-muted-foreground hover:text-foreground">
              <X className="h-4 w-4" />
            </button>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="f-name">Label *</Label>
                  <Input
                    id="f-name"
                    placeholder="e.g. LinkedIn Engineering Jobs"
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="f-url">URL *</Label>
                  <Input
                    id="f-url"
                    placeholder="https://jobs.example.com/listings"
                    value={form.url}
                    onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="f-desc">Description</Label>
                <Input
                  id="f-desc"
                  placeholder="Optional notes about this source"
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  role="switch"
                  aria-checked={form.active}
                  onClick={() => setForm((f) => ({ ...f, active: !f.active }))}
                  className={cn(
                    'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                    form.active ? 'bg-primary' : 'bg-muted'
                  )}
                >
                  <span
                    className={cn(
                      'inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform',
                      form.active ? 'translate-x-4' : 'translate-x-1'
                    )}
                  />
                </button>
                <span className="text-sm text-muted-foreground">
                  {form.active ? 'Active — will be included in scheduled scans' : 'Inactive — skipped in scheduled scans'}
                </span>
              </div>
              {formError && (
                <p className="text-sm text-destructive flex items-center gap-1.5">
                  <AlertCircle className="h-3.5 w-3.5" />
                  {formError}
                </p>
              )}
              <div className="flex gap-2 justify-end">
                <Button type="button" variant="ghost" size="sm" onClick={closeForm}>
                  Cancel
                </Button>
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
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : targets.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16 gap-3">
            <Globe className="h-10 w-10 text-muted-foreground/40" />
            <p className="text-muted-foreground text-sm">No targets yet.</p>
            <Button size="sm" variant="outline" onClick={openAdd}>
              <Plus className="h-4 w-4 mr-1.5" />
              Add your first URL
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {targets.map((t) => (
            <Card
              key={t.id}
              className={cn(
                'transition-shadow hover:shadow-md',
                !t.active && 'opacity-60'
              )}
            >
              <CardContent className="p-4">
                <div className="flex items-start gap-4">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                    <Globe className="h-4 w-4 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm truncate">{t.name}</span>
                      <StatusBadge status={t.status ?? 'idle'} />
                      {!t.active && (
                        <Badge variant="secondary" className="text-xs">Inactive</Badge>
                      )}
                    </div>
                    <a
                      href={t.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-muted-foreground hover:text-primary truncate block mt-0.5"
                    >
                      {t.url}
                    </a>
                    {t.description && (
                      <p className="text-xs text-muted-foreground mt-1">{t.description}</p>
                    )}
                    {t.last_error && (
                      <p className="text-xs text-destructive mt-1 flex items-center gap-1">
                        <AlertCircle className="h-3 w-3" />
                        {t.last_error}
                      </p>
                    )}
                    <div className="flex items-center gap-4 mt-2">
                      <span className="text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">{t.job_count ?? 0}</span> jobs found
                      </span>
                      <span className="text-xs text-muted-foreground">
                        Last scan: {formatDate(t.last_scraped_at)}
                      </span>
                      {t.scrape_count > 0 && (
                        <span className="text-xs text-muted-foreground">
                          {t.scrape_count} scans total
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Button
                      variant="outline"
                      size="icon"
                      className="h-7 w-7"
                      title="Scan now"
                      onClick={() => handleScrape(t.id)}
                      disabled={t.status === 'running' || scrapingIds.has(t.id)}
                    >
                      {t.status === 'running' || scrapingIds.has(t.id) ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Play className="h-3.5 w-3.5" />
                      )}
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      className="h-7 w-7"
                      title="Edit"
                      onClick={() => openEdit(t)}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      className="h-7 w-7 text-destructive hover:bg-destructive/10"
                      title="Delete"
                      onClick={() => handleDelete(t.id)}
                    >
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
