import { useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ClipboardCopy,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Plus,
  Trash2,
  X,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

// ─── Types ────────────────────────────────────────────────────────────────────

interface Secret {
  variable_name: string;
  masked_value: string;
  created_at: string;
  updated_at: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ─── Secret row card ──────────────────────────────────────────────────────────

interface SecretRowProps {
  secret: Secret;
  onDelete: (name: string) => Promise<void>;
}

function SecretRow({ secret, onDelete }: SecretRowProps) {
  const [revealed, setRevealed]     = useState(false);
  const [liveValue, setLiveValue]   = useState<string | null>(null);
  const [fetching, setFetching]     = useState(false);
  const [fetchErr, setFetchErr]     = useState('');
  const [copied, setCopied]         = useState(false);
  const [deleting, setDeleting]     = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);

  // STEP 4 — fetch decrypted value from backend on reveal
  const handleToggle = async () => {
    if (revealed) { setRevealed(false); return; }
    if (liveValue !== null) { setRevealed(true); return; }  // already fetched

    setFetching(true);
    setFetchErr('');
    try {
      const res = await fetch(`/api/secrets/${secret.variable_name}/value`);
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail ?? 'Failed'); }
      const data = await res.json();
      setLiveValue(data.value);
      setRevealed(true);
    } catch (e) {
      setFetchErr(e instanceof Error ? e.message : 'Error fetching value');
    } finally {
      setFetching(false);
    }
  };

  const handleCopy = async () => {
    if (!liveValue) return;
    await navigator.clipboard.writeText(liveValue);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const handleDelete = async () => {
    setDeleting(true);
    await onDelete(secret.variable_name);
    setDeleting(false);
    setConfirmDel(false);
  };

  return (
    <Card className="transition-shadow hover:shadow-sm">
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          {/* Icon */}
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
            <KeyRound className="h-4 w-4 text-primary" />
          </div>

          {/* Body */}
          <div className="flex-1 min-w-0 space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <code className="text-xs font-mono font-semibold bg-muted px-1.5 py-0.5 rounded">
                {secret.variable_name}
              </code>
              <span className="text-[11px] text-muted-foreground">updated {timeAgo(secret.updated_at)}</span>
            </div>

            {/* Value display */}
            <div className="flex items-center gap-2">
              <span className={cn(
                'text-sm font-mono flex-1 truncate',
                revealed ? 'text-foreground select-all' : 'text-muted-foreground tracking-widest'
              )}>
                {revealed && liveValue !== null ? liveValue : '••••••••••••'}
              </span>
              {fetchErr && (
                <span className="text-xs text-destructive flex items-center gap-1">
                  <AlertCircle className="h-3 w-3" />{fetchErr}
                </span>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1.5 shrink-0">
            {/* Show / hide — STEP 3 eye toggle */}
            <Button
              variant="outline" size="icon" className="h-7 w-7"
              title={revealed ? 'Hide value' : 'Reveal value'}
              onClick={handleToggle}
              disabled={fetching}
            >
              {fetching
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : revealed
                  ? <EyeOff className="h-3.5 w-3.5" />
                  : <Eye className="h-3.5 w-3.5" />
              }
            </Button>

            {/* Copy (only available once revealed) */}
            <Button
              variant="outline" size="icon" className="h-7 w-7"
              title="Copy to clipboard"
              onClick={handleCopy}
              disabled={!revealed || !liveValue}
            >
              {copied
                ? <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                : <ClipboardCopy className="h-3.5 w-3.5" />
              }
            </Button>

            {/* Delete */}
            {confirmDel ? (
              <>
                <Button
                  variant="destructive" size="sm" className="h-7 text-xs px-2"
                  onClick={handleDelete} disabled={deleting}
                >
                  {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Delete'}
                </Button>
                <Button
                  variant="ghost" size="sm" className="h-7 text-xs px-2"
                  onClick={() => setConfirmDel(false)} disabled={deleting}
                >
                  Cancel
                </Button>
              </>
            ) : (
              <Button
                variant="outline" size="icon"
                className="h-7 w-7 text-destructive hover:bg-destructive/10"
                title="Delete secret"
                onClick={() => setConfirmDel(true)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function SecretsPage() {
  const [secrets, setSecrets]   = useState<Secret[]>([]);
  const [loading, setLoading]   = useState(true);
  const [showForm, setShowForm] = useState(false);

  // Form state
  const [name, setName]         = useState('');
  const [value, setValue]       = useState('');
  const [showVal, setShowVal]   = useState(false);
  const [saving, setSaving]     = useState(false);
  const [formErr, setFormErr]   = useState('');
  const [formOk, setFormOk]     = useState('');

  const nameRef = useRef<HTMLInputElement>(null);

  const fetchSecrets = async () => {
    try {
      const res = await fetch('/api/secrets');
      if (res.ok) setSecrets(await res.json());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchSecrets(); }, []);

  useEffect(() => {
    if (showForm) setTimeout(() => nameRef.current?.focus(), 50);
  }, [showForm]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const n = name.trim().toUpperCase().replace(/\s+/g, '_');
    const v = value.trim();
    if (!n) { setFormErr('Variable name is required.'); return; }
    if (!v) { setFormErr('Value is required.'); return; }

    setSaving(true); setFormErr(''); setFormOk('');
    try {
      const res = await fetch('/api/secrets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ variable_name: n, value: v }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail ?? 'Request failed'); }
      setFormOk(`"${n}" saved successfully.`);
      setName(''); setValue(''); setShowVal(false);
      await fetchSecrets();
      setTimeout(() => { setShowForm(false); setFormOk(''); }, 1200);
    } catch (e) {
      setFormErr(e instanceof Error ? e.message : 'An error occurred.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (varName: string) => {
    await fetch(`/api/secrets/${varName}`, { method: 'DELETE' });
    await fetchSecrets();
  };

  return (
    <div className="space-y-6 animate-fade-in">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground mt-0.5">
            Keys are encrypted at rest. The frontend resolves values by variable name at runtime — no raw tokens in code.
          </p>
        </div>
        <Button size="sm" onClick={() => { setShowForm((v) => !v); setFormErr(''); setFormOk(''); }}>
          {showForm ? <X className="h-4 w-4 mr-1.5" /> : <Plus className="h-4 w-4 mr-1.5" />}
          {showForm ? 'Cancel' : 'Add Secret'}
        </Button>
      </div>

      {/* ── STEP 3 — Add secret form ────────────────────────────────────────── */}
      {showForm && (
        <Card className="border-primary/40 shadow-md animate-fade-in">
          <CardHeader className="pb-3 pt-4 px-4">
            <CardTitle className="text-sm flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-primary" />
              Store a new secret
            </CardTitle>
            <CardDescription className="text-xs">
              The value is encrypted before storage. Use the variable name in code to fetch it at runtime.
            </CardDescription>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <form onSubmit={handleSave} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="s-name">Variable name</Label>
                  <Input
                    ref={nameRef}
                    id="s-name"
                    placeholder="e.g. APIFY_API_KEY"
                    value={name}
                    onChange={(e) => setName(e.target.value.toUpperCase().replace(/\s+/g, '_'))}
                    className="font-mono text-sm"
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <p className="text-[11px] text-muted-foreground">Auto-uppercased, spaces → underscores.</p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="s-value">Secret value</Label>
                  <div className="relative">
                    <Input
                      id="s-value"
                      type={showVal ? 'text' : 'password'}
                      placeholder="Paste your API key…"
                      value={value}
                      onChange={(e) => setValue(e.target.value)}
                      className="pr-9 font-mono text-sm"
                      autoComplete="new-password"
                      spellCheck={false}
                    />
                    <button
                      type="button"
                      onClick={() => setShowVal((v) => !v)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      tabIndex={-1}
                    >
                      {showVal ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>
              </div>

              {formErr && (
                <p className="text-sm text-destructive flex items-center gap-1.5">
                  <AlertCircle className="h-3.5 w-3.5" />{formErr}
                </p>
              )}
              {formOk && (
                <p className="text-sm text-green-600 dark:text-green-400 flex items-center gap-1.5">
                  <CheckCircle2 className="h-3.5 w-3.5" />{formOk}
                </p>
              )}

              <div className="flex gap-2 justify-end">
                <Button type="button" variant="ghost" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
                <Button type="submit" size="sm" disabled={saving}>
                  {saving && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
                  Save secret
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* ── Secret list ─────────────────────────────────────────────────────── */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : secrets.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16 gap-3">
            <KeyRound className="h-10 w-10 text-muted-foreground/40" />
            <p className="font-medium text-sm">No secrets stored yet</p>
            <p className="text-xs text-muted-foreground text-center max-w-xs">
              Add an API key above. It will be encrypted and accessible by variable name at runtime.
            </p>
            <Button size="sm" variant="outline" onClick={() => setShowForm(true)}>
              <Plus className="h-4 w-4 mr-1.5" />Add your first secret
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            {secrets.length} secret{secrets.length !== 1 ? 's' : ''} stored · values encrypted at rest
          </p>
          {secrets.map((s) => (
            <SecretRow key={s.variable_name} secret={s} onDelete={handleDelete} />
          ))}
        </div>
      )}

      {/* ── Usage reference ─────────────────────────────────────────────────── */}
      {secrets.length > 0 && (
        <Card className="border-border/50 bg-muted/30">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Runtime usage
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-3">
            <p className="text-xs text-muted-foreground">
              Resolve any secret by variable name from the frontend or backend:
            </p>
            <div className="space-y-2">
              <div>
                <Badge variant="secondary" className="text-[10px] mb-1">Frontend (JS)</Badge>
                <pre className="text-[11px] bg-background border border-border rounded-md p-3 overflow-x-auto font-mono leading-relaxed text-foreground">{`const res = await fetch('/api/secrets/YOUR_VAR_NAME/value');
const { value } = await res.json();`}</pre>
              </div>
              <div>
                <Badge variant="secondary" className="text-[10px] mb-1">Backend (Python)</Badge>
                <pre className="text-[11px] bg-background border border-border rounded-md p-3 overflow-x-auto font-mono leading-relaxed text-foreground">{`import httpx
async with httpx.AsyncClient() as c:
    r = await c.get("http://backend:8000/api/secrets/YOUR_VAR_NAME/value")
    token = r.json()["value"]`}</pre>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
