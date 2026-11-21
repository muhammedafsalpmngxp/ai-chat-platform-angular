import { HttpStatusError, SseEvent, postSse } from './sse';

function streamResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { 'Content-Type': 'text/event-stream' } });
}

describe('postSse', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => (globalThis.fetch = realFetch));

  it('parses events split across network chunks', async () => {
    globalThis.fetch = async () =>
      streamResponse(['event: token\ndata: {"text":"Hel', 'lo"}\n\nevent: done\r\n', 'data: {"ok":true}\r\n\r\n']);
    const events: SseEvent[] = [];
    await postSse('/x', {}, 'tok', new AbortController().signal, (e) => events.push(e));
    expect(events).toEqual([
      { event: 'token', data: { text: 'Hello' } },
      { event: 'done', data: { ok: true } },
    ]);
  });

  it('throws HttpStatusError with the API detail on failure', async () => {
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: 'A reply is already being generated' }), { status: 409 });
    await expect(postSse('/x', {}, null, new AbortController().signal, () => {})).rejects.toEqual(
      new HttpStatusError(409, 'A reply is already being generated'),
    );
  });
});
