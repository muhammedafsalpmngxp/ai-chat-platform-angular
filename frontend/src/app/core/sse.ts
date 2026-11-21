/** Minimal Server-Sent Events client over fetch (EventSource can't POST or send headers). */

export interface SseEvent {
  event: string;
  data: unknown;
}

export class HttpStatusError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    /** Machine-readable reason from the X-Error-Code header, e.g. "reauth_required". */
    readonly code: string | null = null,
  ) {
    super(detail);
  }
}

export async function postSse(
  url: string,
  body: unknown,
  token: string | null,
  signal: AbortSignal,
  onEvent: (event: SseEvent) => void,
  extraHeaders: Record<string, string> = {},
): Promise<void> {
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...extraHeaders,
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    let detail = `Request failed (${res.status})`;
    try {
      const json = await res.json();
      if (typeof json?.detail === 'string') detail = json.detail;
    } catch {
      /* not JSON */
    }
    throw new HttpStatusError(res.status, detail, res.headers.get('X-Error-Code'));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    let boundary: number;
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseBlock(block);
      if (parsed) onEvent(parsed);
    }
  }
}

function parseBlock(block: string): SseEvent | null {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join('\n')) };
  } catch {
    return null;
  }
}
