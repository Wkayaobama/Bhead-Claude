import { useEffect, useRef, useState } from 'react';
import {
  BookOpen,
  Bot,
  Briefcase,
  Building2,
  DollarSign,
  ExternalLink,
  Loader2,
  MapPin,
  Paperclip,
  RefreshCw,
  Search,
  Sparkles,
  Tag,
  Upload,
  X,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

interface Job {
  id: string;
  title: string;
  company: string;
  location: string;
  description: string;
  url: string;
  salary_range: string;
  posted_at: string;
  category: string;
  tags: string[];
  target_name: string;
  scraped_at: string;
}

interface Stats {
  total_jobs: number;
  total_targets: number;
  active_targets: number;
  categories: { category: string; count: number }[];
}

interface Props {
  onOpenDocs: (jobId: string) => void;
}

const CATEGORY_COLORS: Record<string, string> = {
  Engineering: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  Marketing: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  Sales: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
  HR: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  Finance: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  Design: 'bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400',
  Operations: 'bg-slate-100 text-slate-700 dark:bg-slate-800/60 dark:text-slate-400',
  Product: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400',
  Legal: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  Other: 'bg-muted text-muted-foreground',
};

function CategoryBadge({ category }: { category: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
      CATEGORY_COLORS[category] ?? CATEGORY_COLORS.Other)}>
      {category}
    </span>
  );
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function JobFeedPage({ onOpenDocs }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [activeCategory, setActiveCategory] = useState<string>('All');
  const [total, setTotal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [docCounts, setDocCounts] = useState<Record<string, number>>({});
  const [uploadingId, setUploadingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadTargetId = useRef<string | null>(null);

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/jobs/stats');
      if (res.ok) setStats(await res.json());
    } catch {/* noop */}
  };

  const fetchDocCounts = async () => {
    try {
      const res = await fetch('/api/documents/counts');
      if (res.ok) setDocCounts(await res.json());
    } catch {/* noop */}
  };

  const fetchJobs = async (opts?: { showLoader?: boolean }) => {
    if (opts?.showLoader) setLoading(true);
    const params = new URLSearchParams();
    if (activeCategory && activeCategory !== 'All') params.set('category', activeCategory);
    if (search) params.set('search', search);
    params.set('limit', '60');
    try {
      const res = await fetch(`/api/jobs?${params}`);
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      setJobs(data.jobs);
      setTotal(data.total);
    } catch {/* noop */}
    finally { setLoading(false); setRefreshing(false); }
  };

  useEffect(() => { fetchStats(); fetchDocCounts(); }, []);
  useEffect(() => { fetchJobs({ showLoader: true }); }, [activeCategory, search]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([fetchJobs(), fetchStats(), fetchDocCounts()]);
  };

  const handleSearchSubmit = (e: React.FormEvent) => { e.preventDefault(); setSearch(searchInput); };
  const clearSearch = () => { setSearchInput(''); setSearch(''); };

  const triggerUpload = (jobId: string) => {
    uploadTargetId.current = jobId;
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    const jobId = uploadTargetId.current;
    if (!file || !jobId) return;
    setUploadingId(jobId);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch(`/api/documents/upload/${jobId}`, { method: 'POST', body: form });
      if (!res.ok) { const err = await res.json(); alert(err.detail || 'Upload failed.'); }
      else fetchDocCounts();
    } finally {
      setUploadingId(null);
      e.target.value = '';
      uploadTargetId.current = null;
    }
  };

  const allCategories = ['All', ...Array.from(new Set(stats?.categories.map((c) => c.category) ?? []))];

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Hidden file input for uploads */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.txt,.md,.doc,.docx,.csv"
        className="hidden"
        onChange={handleFileChange}
      />

      {/* Stats strip */}
      {stats && (
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Total Jobs', value: stats.total_jobs, icon: Briefcase },
            { label: 'Active Sources', value: stats.active_targets, icon: BookOpen },
            { label: 'Categories', value: stats.categories.length, icon: Tag },
          ].map(({ label, value, icon: Icon }) => (
            <Card key={label}>
              <CardContent className="p-4 flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
                  <Icon className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <p className="text-xl font-semibold leading-none">{value}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Search + refresh */}
      <div className="flex gap-2">
        <form onSubmit={handleSearchSubmit} className="relative flex-1">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input placeholder="Search jobs, companies…" className="pl-8 pr-8" value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)} />
          {searchInput && (
            <button type="button" onClick={clearSearch}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </form>
        <Button variant="outline" size="icon" onClick={handleRefresh} disabled={refreshing}>
          <RefreshCw className={cn('h-4 w-4', refreshing && 'animate-spin')} />
        </Button>
      </div>

      {/* Category filters */}
      {allCategories.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {allCategories.map((cat) => {
            const count = cat === 'All' ? total : (stats?.categories.find((c) => c.category === cat)?.count ?? 0);
            return (
              <button key={cat} onClick={() => setActiveCategory(cat)}
                className={cn('inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors border',
                  activeCategory === cat
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-background hover:bg-muted border-border text-muted-foreground')}>
                {cat}
                <span className={cn('rounded-full px-1.5 py-0.5 text-[10px] font-semibold',
                  activeCategory === cat ? 'bg-primary-foreground/20 text-primary-foreground' : 'bg-muted-foreground/20')}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Job cards */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : jobs.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16 gap-3">
            <Sparkles className="h-10 w-10 text-muted-foreground/40" />
            <p className="font-medium text-sm">{search ? `No jobs matching "${search}"` : 'No jobs yet.'}</p>
            <p className="text-xs text-muted-foreground">
              {search ? 'Try a different search term.' : 'Head to URL Manager and add job board URLs, then click Scan.'}
            </p>
            {search && <Button size="sm" variant="outline" onClick={clearSearch}>Clear search</Button>}
          </CardContent>
        </Card>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">Showing {jobs.length} of {total} job{total !== 1 ? 's' : ''}</p>
          <div className="grid gap-3">
            {jobs.map((job) => {
              const docCount = docCounts[job.id] ?? 0;
              return (
                <Card key={job.id} className="hover:shadow-md transition-shadow">
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        {/* Title row */}
                        <div className="flex items-center gap-2 flex-wrap">
                          <h3 className="font-semibold text-sm leading-snug">{job.title}</h3>
                          <CategoryBadge category={job.category ?? 'Other'} />
                          {docCount > 0 && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 text-primary px-2 py-0.5 text-[11px] font-medium">
                              <Paperclip className="h-2.5 w-2.5" />
                              {docCount}
                            </span>
                          )}
                        </div>

                        {/* Meta row */}
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5">
                          {job.company && (
                            <span className="flex items-center gap-1 text-xs text-muted-foreground">
                              <Building2 className="h-3 w-3" />{job.company}
                            </span>
                          )}
                          {job.location && (
                            <span className="flex items-center gap-1 text-xs text-muted-foreground">
                              <MapPin className="h-3 w-3" />{job.location}
                            </span>
                          )}
                          {job.salary_range && (
                            <span className="flex items-center gap-1 text-xs text-muted-foreground">
                              <DollarSign className="h-3 w-3" />{job.salary_range}
                            </span>
                          )}
                        </div>

                        {/* Description */}
                        {job.description && (
                          <p className="text-xs text-muted-foreground mt-2 line-clamp-2">{job.description}</p>
                        )}

                        {/* Tags */}
                        {job.tags?.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 mt-2">
                            {job.tags.slice(0, 5).map((tag) => (
                              <span key={tag} className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">{tag}</span>
                            ))}
                          </div>
                        )}

                        {/* Footer */}
                        <div className="flex items-center gap-3 mt-2.5">
                          <span className="text-[11px] text-muted-foreground">via {job.target_name}</span>
                          {job.posted_at && <span className="text-[11px] text-muted-foreground">posted {job.posted_at}</span>}
                          <span className="text-[11px] text-muted-foreground ml-auto">scraped {timeAgo(job.scraped_at)}</span>
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex flex-col gap-1.5 shrink-0">
                        {/* Upload document */}
                        <Button
                          variant="outline" size="icon" className="h-7 w-7"
                          title="Upload interview document"
                          onClick={() => triggerUpload(job.id)}
                          disabled={uploadingId === job.id}
                        >
                          {uploadingId === job.id
                            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            : <Upload className="h-3.5 w-3.5" />}
                        </Button>
                        {/* Interview prep */}
                        <Button
                          variant="outline" size="icon" className="h-7 w-7"
                          title="Interview prep"
                          onClick={() => onOpenDocs(job.id)}
                        >
                          <Bot className="h-3.5 w-3.5" />
                        </Button>
                        {/* Open posting */}
                        {job.url && (
                          <a href={job.url} target="_blank" rel="noopener noreferrer">
                            <Button variant="outline" size="icon" className="h-7 w-7" title="Open posting">
                              <ExternalLink className="h-3.5 w-3.5" />
                            </Button>
                          </a>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
