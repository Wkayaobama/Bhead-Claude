import { useEffect, useRef, useState } from 'react';
import {
  Brain,
  Globe,
  Loader2,
  Plus,
  RotateCcw,
  Save,
  Tag,
  Target,
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

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentConfig {
  system_prompt: string;
  domain_focus: string[];
  goal: string;
  updated_at: string | null;
}

interface ScrapeTarget {
  id: string;
  name: string;
  url: string;
  goal: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string | null): string {
  if (!iso) return 'Never';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function truncateUrl(url: string, max = 50): string {
  try {
    const { hostname, pathname } = new URL(url);
    const combined = hostname + pathname;
    if (combined.length <= max) return combined;
    return combined.slice(0, max) + '…';
  } catch {
    return url.length <= max ? url : url.slice(0, max) + '…';
  }
}

// ---------------------------------------------------------------------------
// Section 1 — Agent Prompt Configuration
// ---------------------------------------------------------------------------

function AgentPromptCard() {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Editable fields
  const [systemPrompt, setSystemPrompt] = useState('');
  const [domainFocus, setDomainFocus] = useState<string[]>([]);
  const [goal, setGoal] = useState('');
  const [tagInput, setTagInput] = useState('');

  // Save state
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Reset state
  const [resetting, setResetting] = useState(false);

  const tagInputRef = useRef<HTMLInputElement>(null);

  // ---- fetch on mount ----
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/agent-config');
        if (!res.ok) throw new Error(await res.text());
        const data: AgentConfig = await res.json();
        setConfig(data);
        setSystemPrompt(data.system_prompt);
        setDomainFocus(data.domain_focus ?? []);
        setGoal(data.goal ?? '');
      } catch (e) {
        setLoadError(e instanceof Error ? e.message : 'Failed to load config.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // ---- tag management ----
  const addTag = () => {
    const trimmed = tagInput.trim();
    if (!trimmed) return;
    if (domainFocus.includes(trimmed)) {
      setTagInput('');
      return;
    }
    setDomainFocus((prev) => [...prev, trimmed]);
    setTagInput('');
    tagInputRef.current?.focus();
  };

  const removeTag = (tag: string) => {
    setDomainFocus((prev) => prev.filter((t) => t !== tag));
  };

  const handleTagKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addTag();
    }
  };

  // ---- save ----
  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const res = await fetch('/api/agent-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          system_prompt: systemPrompt,
          domain_focus: domainFocus,
          goal,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Save failed.');
      }
      const updated: AgentConfig = await res.json();
      setConfig(updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'An error occurred.');
    } finally {
      setSaving(false);
    }
  };

  // ---- reset ----
  const handleReset = async () => {
    if (!confirm('Reset the agent configuration to defaults? This cannot be undone.')) return;
    setResetting(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const res = await fetch('/api/agent-config/reset', { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Reset failed.');
      }
      const data: AgentConfig = await res.json();
      setConfig(data);
      setSystemPrompt(data.system_prompt);
      setDomainFocus(data.domain_focus ?? []);
      setGoal(data.goal ?? '');
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'An error occurred.');
    } finally {
      setResetting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Brain className="h-4 w-4 text-primary" />
          </div>
          <div>
            <CardTitle>Agent Prompt Configuration</CardTitle>
            <CardDescription className="mt-0.5">
              Tune how the AI agent evaluates and filters job postings.
            </CardDescription>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : loadError ? (
          <p className="text-sm text-destructive">{loadError}</p>
        ) : (
          <>
            {/* System Prompt */}
            <div className="space-y-2">
              <Label htmlFor="system-prompt" className="flex items-center gap-1.5">
                <Brain className="h-3.5 w-3.5 text-muted-foreground" />
                System Prompt
              </Label>
              <textarea
                id="system-prompt"
                className={cn(
                  'w-full min-h-[220px] rounded-md border border-input bg-background px-3 py-2',
                  'font-mono text-sm text-foreground placeholder:text-muted-foreground',
                  'ring-offset-background focus-visible:outline-none focus-visible:ring-2',
                  'focus-visible:ring-ring focus-visible:ring-offset-2 resize-y',
                )}
                placeholder="You are an expert HR recruiter…"
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
              />
            </div>

            {/* Overall Goal */}
            <div className="space-y-2">
              <Label htmlFor="agent-goal" className="flex items-center gap-1.5">
                <Target className="h-3.5 w-3.5 text-muted-foreground" />
                Overall Goal
              </Label>
              <Input
                id="agent-goal"
                placeholder="e.g. Find senior software engineers open to remote roles in FinTech"
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
              />
            </div>

            {/* Domain Focus Tags */}
            <div className="space-y-2">
              <Label className="flex items-center gap-1.5">
                <Tag className="h-3.5 w-3.5 text-muted-foreground" />
                Domain Focus
              </Label>

              {/* Existing tags */}
              {domainFocus.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {domainFocus.map((tag) => (
                    <Badge
                      key={tag}
                      variant="secondary"
                      className="flex items-center gap-1 pl-2.5 pr-1.5 py-0.5 text-sm"
                    >
                      {tag}
                      <button
                        type="button"
                        aria-label={`Remove ${tag}`}
                        onClick={() => removeTag(tag)}
                        className="ml-0.5 rounded-full hover:bg-muted-foreground/20 p-0.5 transition-colors"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
              )}

              {/* Tag input */}
              <div className="flex gap-2">
                <Input
                  ref={tagInputRef}
                  placeholder="e.g. Software Engineering"
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={handleTagKeyDown}
                  className="flex-1"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addTag}
                  disabled={!tagInput.trim()}
                >
                  <Plus className="h-3.5 w-3.5 mr-1" />
                  Add
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Press Enter or click Add. Examples: "Software Engineering", "FinTech", "Remote Only".
              </p>
            </div>

            {/* Last updated */}
            {config?.updated_at && (
              <p className="text-xs text-muted-foreground">
                Last updated: {formatDate(config.updated_at)}
              </p>
            )}

            {/* Feedback */}
            {saveError && (
              <p className="text-sm text-destructive">{saveError}</p>
            )}
            {saveSuccess && (
              <p className="text-sm text-green-600 dark:text-green-400">
                Configuration saved successfully.
              </p>
            )}

            {/* Actions */}
            <div className="flex items-center gap-3 pt-1">
              <Button onClick={handleSave} disabled={saving || resetting} size="sm">
                {saving ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5 mr-1.5" />
                )}
                {saving ? 'Saving…' : 'Save'}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleReset}
                disabled={saving || resetting}
              >
                {resetting ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                ) : (
                  <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
                )}
                {resetting ? 'Resetting…' : 'Reset to Defaults'}
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Section 2 — Target Goals
// ---------------------------------------------------------------------------

interface TargetRowProps {
  target: ScrapeTarget;
  onSaved: (id: string, newGoal: string) => void;
}

function TargetGoalRow({ target, onSaved }: TargetRowProps) {
  const [goalValue, setGoalValue] = useState(target.goal ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const isDirty = goalValue !== (target.goal ?? '');

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const res = await fetch(`/api/targets/${target.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: goalValue }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Save failed.');
      }
      onSaved(target.id, goalValue);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'An error occurred.');
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && isDirty) handleSave();
  };

  return (
    <div className="py-3 border-b last:border-b-0">
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted">
          <Globe className="h-3.5 w-3.5 text-muted-foreground" />
        </div>

        {/* Name + URL */}
        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium truncate">{target.name}</span>
            <span
              className="text-xs text-muted-foreground font-mono truncate max-w-[240px]"
              title={target.url}
            >
              {truncateUrl(target.url)}
            </span>
          </div>

          {/* Goal inline edit */}
          <div className="flex gap-2">
            <Input
              value={goalValue}
              onChange={(e) => setGoalValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Goal for this source (e.g. Senior React roles)"
              className="text-sm h-8"
            />
            <Button
              size="sm"
              variant={isDirty ? 'default' : 'outline'}
              className="h-8 shrink-0"
              disabled={saving || !isDirty}
              onClick={handleSave}
            >
              {saving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              <span className="ml-1.5 hidden sm:inline">Save</span>
            </Button>
          </div>

          {/* Feedback */}
          {error && <p className="text-xs text-destructive">{error}</p>}
          {success && (
            <p className="text-xs text-green-600 dark:text-green-400">Goal saved.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function TargetGoalsCard() {
  const [targets, setTargets] = useState<ScrapeTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/targets');
        if (!res.ok) throw new Error(await res.text());
        const data: ScrapeTarget[] = await res.json();
        setTargets(data);
      } catch (e) {
        setLoadError(e instanceof Error ? e.message : 'Failed to load targets.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleGoalSaved = (id: string, newGoal: string) => {
    setTargets((prev) =>
      prev.map((t) => (t.id === id ? { ...t, goal: newGoal } : t))
    );
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Target className="h-4 w-4 text-primary" />
          </div>
          <div>
            <CardTitle>Target Goals</CardTitle>
            <CardDescription className="mt-0.5">
              Set a specific goal for each URL target to refine what the agent looks for on that source.
            </CardDescription>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : loadError ? (
          <p className="text-sm text-destructive">{loadError}</p>
        ) : targets.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 gap-2">
            <Globe className="h-9 w-9 text-muted-foreground/30" />
            <p className="text-sm text-muted-foreground">No targets configured yet.</p>
            <p className="text-xs text-muted-foreground">
              Add URL targets on the URL Manager page first.
            </p>
          </div>
        ) : (
          <div>
            {targets.map((t) => (
              <TargetGoalRow key={t.id} target={t} onSaved={handleGoalSaved} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AgentConfigPage() {
  return (
    <div className="space-y-6 animate-fade-in">
      {/* Page header */}
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Agent Configuration</h2>
        <p className="text-sm text-muted-foreground mt-0.5">
          Control the AI agent's behaviour, system prompt, and per-source goals.
        </p>
      </div>

      {/* Section 1 — Agent Prompt */}
      <AgentPromptCard />

      {/* Section 2 — Target Goals */}
      <TargetGoalsCard />
    </div>
  );
}
