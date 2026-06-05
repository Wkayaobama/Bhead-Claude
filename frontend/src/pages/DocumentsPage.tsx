import { useEffect, useRef, useState } from 'react';
import {
  Bot,
  Download,
  FileText,
  Loader2,
  Paperclip,
  Send,
  Trash2,
  Upload,
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

interface Doc {
  id: string;
  job_id: string;
  job_title: string;
  job_company: string;
  filename: string;
  content_type: string;
  size: number;
  notes: string;
  uploaded_at: string;
}

interface Job { id: string; title: string; company: string; }
interface ChatMsg { role: 'user' | 'assistant'; content: string; }

interface Props {
  initialJobId?: string | null;
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function fileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase();
  const color =
    ext === 'pdf' ? 'text-red-500' :
    ext === 'doc' || ext === 'docx' ? 'text-blue-500' :
    'text-muted-foreground';
  return <FileText className={cn('h-4 w-4 shrink-0', color)} />;
}

export default function DocumentsPage({ initialJobId }: Props) {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<{ total: number; total_size: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [jobFilter, setJobFilter] = useState<string>(initialJobId ?? 'all');
  const [uploading, setUploading] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);

  // Interview prep chat
  const [prepDoc, setPrepDoc] = useState<Doc | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [inputMsg, setInputMsg] = useState('');
  const [streaming, setStreaming] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const fetchDocs = async () => {
    const params = jobFilter !== 'all' ? `?job_id=${jobFilter}` : '';
    const [docsRes, statsRes] = await Promise.all([
      fetch(`/api/documents${params}`),
      fetch('/api/documents/stats'),
    ]);
    if (docsRes.ok) setDocs(await docsRes.json());
    if (statsRes.ok) setStats(await statsRes.json());
    setLoading(false);
  };

  const fetchJobs = async () => {
    const res = await fetch('/api/jobs?limit=200');
    if (res.ok) {
      const d = await res.json();
      const unique = new Map<string, Job>();
      for (const j of d.jobs) unique.set(j.id, { id: j.id, title: j.title, company: j.company });
      setJobs(Array.from(unique.values()));
    }
  };

  useEffect(() => { fetchJobs(); }, []);
  useEffect(() => { fetchDocs(); }, [jobFilter]);

  // Sync initialJobId when it changes (e.g. navigated from feed)
  useEffect(() => {
    if (initialJobId) setJobFilter(initialJobId);
  }, [initialJobId]);

  // Scroll chat to bottom on new messages
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>, jobId?: string) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const targetJobId = jobId ?? (jobFilter !== 'all' ? jobFilter : null);
    if (!targetJobId) { alert('Please filter by a specific job before uploading.'); return; }
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch(`/api/documents/upload/${targetJobId}`, { method: 'POST', body: form });
      if (!res.ok) { const err = await res.json(); alert(err.detail || 'Upload failed.'); }
      else await fetchDocs();
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this document?')) return;
    await fetch(`/api/documents/${id}`, { method: 'DELETE' });
    if (prepDoc?.id === id) { setPrepDoc(null); setMessages([]); }
    fetchDocs();
  };

  const handleStartPrep = (doc: Doc) => {
    setPrepDoc(doc);
    setMessages([{
      role: 'assistant',
      content: `Hi! I've loaded **${doc.filename}** and the job posting **${doc.job_title}** at **${doc.job_company}**. Ask me anything — interview questions, how to tailor your pitch, skill gaps, or salary advice.`,
    }]);
    setInputMsg('');
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  };

  const handleSend = async () => {
    if (!inputMsg.trim() || !prepDoc || streaming) return;
    const userMsg = inputMsg.trim();
    setInputMsg('');
    const newHistory = [...messages, { role: 'user' as const, content: userMsg }];
    setMessages(newHistory);
    setStreaming(true);

    // Build history for API (exclude the initial greeting)
    const apiHistory = newHistory
      .slice(1)
      .slice(0, -1)
      .map((m) => ({ role: m.role, content: m.content }));

    try {
      const res = await fetch('/api/documents/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          doc_id: prepDoc.id,
          job_id: prepDoc.job_id,
          message: userMsg,
          history: apiHistory,
        }),
      });
      if (!res.ok) throw new Error('Chat request failed');

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let assistantText = '';
      setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const raw = decoder.decode(value, { stream: true });
        for (const line of raw.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.text) {
              assistantText += data.text;
              setMessages((prev) => {
                const next = [...prev];
                next[next.length - 1] = { role: 'assistant', content: assistantText };
                return next;
              });
            }
            if (data.error) {
              assistantText += `\n\n⚠️ Error: ${data.error}`;
              setMessages((prev) => {
                const next = [...prev];
                next[next.length - 1] = { role: 'assistant', content: assistantText };
                return next;
              });
            }
          } catch { /* skip malformed */ }
        }
      }
    } catch (e) {
      setMessages((prev) => [...prev, { role: 'assistant', content: `⚠️ ${e instanceof Error ? e.message : 'Request failed'}` }]);
    } finally {
      setStreaming(false);
    }
  };

  const filteredJobForUpload = jobFilter !== 'all'
    ? jobs.find((j) => j.id === jobFilter)
    : null;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Stats + controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-4">
          {stats && (
            <>
              <span className="text-sm font-medium">{stats.total} document{stats.total !== 1 ? 's' : ''}</span>
              <span className="text-xs text-muted-foreground">{fmtSize(stats.total_size)} total</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Job filter */}
          <select
            className="h-8 rounded-md border border-border bg-background px-2.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            value={jobFilter}
            onChange={(e) => setJobFilter(e.target.value)}
          >
            <option value="all">All jobs</option>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.title}{j.company ? ` — ${j.company}` : ''}
              </option>
            ))}
          </select>
          {/* Upload button — only active when a specific job is selected */}
          <input
            ref={uploadRef}
            type="file"
            accept=".pdf,.txt,.md,.doc,.docx,.csv"
            className="hidden"
            onChange={(e) => handleUpload(e)}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={jobFilter === 'all' || uploading}
            onClick={() => uploadRef.current?.click()}
            title={jobFilter === 'all' ? 'Select a specific job first' : 'Upload document for this job'}
          >
            {uploading
              ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              : <Upload className="h-3.5 w-3.5 mr-1.5" />}
            Upload
          </Button>
        </div>
      </div>

      {jobFilter !== 'all' && filteredJobForUpload && (
        <div className="rounded-lg bg-primary/5 border border-primary/20 px-4 py-2.5 text-xs text-primary flex items-center gap-2">
          <Paperclip className="h-3.5 w-3.5 shrink-0" />
          Showing documents for: <strong>{filteredJobForUpload.title}</strong>
          {filteredJobForUpload.company && <span className="text-muted-foreground">@ {filteredJobForUpload.company}</span>}
          <button onClick={() => setJobFilter('all')} className="ml-auto hover:text-foreground"><X className="h-3 w-3" /></button>
        </div>
      )}

      {/* Document library */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : docs.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-14 gap-3">
            <Paperclip className="h-10 w-10 text-muted-foreground/40" />
            <p className="font-medium text-sm">No documents yet</p>
            <p className="text-xs text-muted-foreground text-center max-w-xs">
              {jobFilter === 'all'
                ? 'Go to the Job Feed, click the upload icon on any job card, and attach a CV or prep document.'
                : 'Select a file above to upload your first document for this job.'}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {docs.map((doc) => (
            <Card
              key={doc.id}
              className={cn(
                'transition-shadow hover:shadow-md',
                prepDoc?.id === doc.id && 'border-primary/50 shadow-md'
              )}
            >
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                    {fileIcon(doc.filename)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm truncate">{doc.filename}</span>
                      <Badge variant="secondary" className="text-xs shrink-0">{fmtSize(doc.size)}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      For: <span className="text-foreground font-medium">{doc.job_title}</span>
                      {doc.job_company && <span> @ {doc.job_company}</span>}
                    </p>
                    {doc.notes && <p className="text-xs text-muted-foreground mt-1 italic">{doc.notes}</p>}
                    <p className="text-[11px] text-muted-foreground mt-1">{timeAgo(doc.uploaded_at)}</p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Button
                      variant={prepDoc?.id === doc.id ? 'default' : 'outline'}
                      size="sm"
                      className="h-7 text-xs px-2.5"
                      onClick={() => prepDoc?.id === doc.id ? setPrepDoc(null) : handleStartPrep(doc)}
                    >
                      <Bot className="h-3 w-3 mr-1" />
                      {prepDoc?.id === doc.id ? 'Close' : 'Interview Prep'}
                    </Button>
                    <a href={`/api/documents/${doc.id}/download`} download={doc.filename}>
                      <Button variant="outline" size="icon" className="h-7 w-7" title="Download">
                        <Download className="h-3.5 w-3.5" />
                      </Button>
                    </a>
                    <Button
                      variant="outline" size="icon"
                      className="h-7 w-7 text-destructive hover:bg-destructive/10"
                      title="Delete" onClick={() => handleDelete(doc.id)}
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

      {/* Interview Prep Chat panel */}
      {prepDoc && (
        <Card className="border-primary/30 shadow-lg animate-fade-in">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base flex items-center gap-2">
                  <Bot className="h-4 w-4 text-primary" />
                  Interview Prep Coach
                </CardTitle>
                <CardDescription className="mt-0.5">
                  Context: <strong>{prepDoc.filename}</strong> · <strong>{prepDoc.job_title}</strong>
                </CardDescription>
              </div>
              <button
                onClick={() => { setPrepDoc(null); setMessages([]); }}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Messages */}
            <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
              {messages.map((msg, i) => (
                <div
                  key={i}
                  className={cn(
                    'flex gap-2.5',
                    msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'
                  )}
                >
                  {msg.role === 'assistant' && (
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 mt-0.5">
                      <Bot className="h-3.5 w-3.5 text-primary" />
                    </div>
                  )}
                  <div
                    className={cn(
                      'rounded-xl px-3 py-2 text-sm max-w-[85%] leading-relaxed whitespace-pre-wrap',
                      msg.role === 'user'
                        ? 'bg-primary text-primary-foreground ml-auto'
                        : 'bg-muted text-foreground'
                    )}
                  >
                    {msg.content || (streaming && i === messages.length - 1
                      ? <span className="flex gap-1 items-center"><Loader2 className="h-3 w-3 animate-spin" /><span className="text-xs text-muted-foreground">Thinking…</span></span>
                      : '')}
                  </div>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* Quick prompts */}
            {messages.length <= 1 && (
              <div className="flex flex-wrap gap-1.5">
                {[
                  'What are the top 5 interview questions for this role?',
                  'How should I tailor my pitch for this company?',
                  'What skill gaps should I address?',
                  'Help me with salary negotiation',
                ].map((q) => (
                  <button
                    key={q}
                    onClick={() => { setInputMsg(q); }}
                    className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}

            {/* Input */}
            <div className="flex gap-2">
              <Input
                placeholder="Ask anything about this interview…"
                value={inputMsg}
                onChange={(e) => setInputMsg(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
                disabled={streaming}
                className="flex-1"
              />
              <Button
                size="icon"
                onClick={handleSend}
                disabled={!inputMsg.trim() || streaming}
                title="Send"
              >
                {streaming
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <Send className="h-4 w-4" />}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
