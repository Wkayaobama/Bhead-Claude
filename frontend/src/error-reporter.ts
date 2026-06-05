// Captures uncaught browser errors and forwards them to the backend so the
// App Builder can show a "Send to agent" popup. Imported once from main.tsx.
//
// Sends:
//   POST /api/__app_errors
//   { source, message, stack?, url? }

const ENDPOINT = '/api/__app_errors';

function send(payload: Record<string, unknown>): void {
  // best-effort, fire-and-forget; never throw
  try {
    void fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    });
  } catch {
    // ignore
  }
}

window.addEventListener('error', (event) => {
  send({
    source: 'frontend',
    message: event.message || String(event.error || 'unknown error'),
    stack: event.error instanceof Error ? event.error.stack : undefined,
    url: window.location.pathname + window.location.search,
  });
});

window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason;
  send({
    source: 'frontend',
    message:
      reason instanceof Error
        ? `unhandled rejection: ${reason.message}`
        : `unhandled rejection: ${String(reason)}`,
    stack: reason instanceof Error ? reason.stack : undefined,
    url: window.location.pathname + window.location.search,
  });
});

// Wrap fetch so non-2xx responses become trackable error reports too.
const _originalFetch = window.fetch.bind(window);
window.fetch = async (...args: Parameters<typeof fetch>): Promise<Response> => {
  const r = await _originalFetch(...args);
  if (r.status >= 400) {
    const url = typeof args[0] === 'string' ? args[0] : (args[0] as Request).url;
    let bodyPreview = '';
    try {
      bodyPreview = (await r.clone().text()).slice(0, 500);
    } catch {
      // ignore
    }
    // Don't recurse on /api/__app_errors itself.
    if (!url.includes('/api/__app_errors')) {
      send({
        source: 'fetch',
        message: `HTTP ${r.status} from ${url}: ${bodyPreview}`,
        url,
      });
    }
  }
  return r;
};

export {};
