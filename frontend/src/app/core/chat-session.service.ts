import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';

import { AskDataService } from './ask-data.service';
import { AuthService } from './auth.service';
import { ChatService } from './chat.service';
import { ModelService } from './model.service';
import { AttachmentInfo, ChatMessage, ChatSummary, GraphStep, MessageStatus, UiMessage } from './models';
import { HttpStatusError, SseEvent, postSse } from './sse';

export interface ChatUsage {
  context: number;
  input: number;
  output: number;
  cached: number;
  costUsd: number;
}

/** Why a message could not be sent (nothing was saved on the server). */
export type SendResult = { ok: true } | { ok: false; reason: 'reauth_required' | 'rejected'; detail: string };
export type SendFailure = Extract<SendResult, { ok: false }> & { text: string; attachments: AttachmentInfo[] };

function browserTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
  } catch {
    return undefined;
  }
}

const EMPTY_USAGE: ChatUsage = { context: 0, input: 0, output: 0, cached: 0, costUsd: 0 };

function usageOf(chat: ChatSummary): ChatUsage {
  return {
    context: chat.token_count,
    input: chat.total_input_tokens,
    output: chat.total_output_tokens,
    cached: chat.total_cached_input_tokens,
    costUsd: chat.total_cost_usd ?? 0,
  };
}

/**
 * The open conversation and its streaming reply.
 * Lives outside the page component so a reply keeps streaming while the
 * router swaps "/" for "/c/:id" after the first message.
 */
@Injectable({ providedIn: 'root' })
export class ChatSessionService {
  private readonly chats = inject(ChatService);
  private readonly auth = inject(AuthService);
  private readonly modelService = inject(ModelService);
  private readonly askData = inject(AskDataService);

  private readonly _chatId = signal<string | null>(null);
  private readonly _messages = signal<UiMessage[]>([]);
  private readonly _loading = signal(false);
  private readonly _streaming = signal(false);
  private readonly _usage = signal<ChatUsage>(EMPTY_USAGE);
  private readonly _model = signal<string | null>(null);
  private readonly _failure = signal<SendFailure | null>(null);

  readonly chatId = this._chatId.asReadonly();
  readonly messages = this._messages.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly streaming = this._streaming.asReadonly();
  readonly usage = this._usage.asReadonly();
  readonly isEmpty = computed(() => this._messages().length === 0);
  /** Model used for the next message in this chat. */
  readonly modelId = computed(() => this._model() ?? this.modelService.lastUsed());
  readonly model = computed(() => this.modelService.get(this.modelId()));
  /** Last message the server refused to accept (to restore the draft and explain why). */
  readonly failure = this._failure.asReadonly();

  clearFailure(): void {
    this._failure.set(null);
  }

  private abort: AbortController | null = null;
  private loadSeq = 0;

  /** Show a chat (null = the empty "new chat" screen). Throws HttpErrorResponse 404 if missing. */
  async open(id: string | null): Promise<void> {
    if (id === this._chatId() && (id === null || this._messages().length || this._streaming())) return;
    if (this._streaming()) this.stop();

    this._chatId.set(id);
    this._messages.set([]);
    this._usage.set(EMPTY_USAGE);
    this._model.set(null);
    if (!id) return;

    const seq = ++this.loadSeq;
    this._loading.set(true);
    try {
      const chat = await this.chats.get(id);
      if (seq !== this.loadSeq) return;
      this._messages.set(chat.messages);
      this._usage.set(usageOf(chat));
      this._model.set(this.modelService.get(chat.model) ? chat.model : null);
    } finally {
      if (seq === this.loadSeq) this._loading.set(false);
    }
  }

  /** Pick the model for this chat (and for new chats). */
  selectModel(id: string): void {
    this._model.set(id);
    this.modelService.remember(id);
  }

  /** Make sure there is a chat to send into; creates one on the empty screen. */
  async ensureChat(): Promise<string> {
    const current = this._chatId();
    if (current) return current;
    const chat = await this.chats.create();
    this.loadSeq++; // cancel any pending load
    this._chatId.set(chat.id);
    this._loading.set(false);
    return chat.id;
  }

  /**
   * Send a message and stream the reply. Resolves when the stream ends.
   * If the server refuses before anything starts (e.g. premium unlock expired),
   * the optimistic messages are removed and the reason is returned.
   */
  async send(content: string, attachments: AttachmentInfo[] = []): Promise<SendResult> {
    const chatId = this._chatId();
    const text = content.trim();
    if (!chatId || (!text && !attachments.length) || this._streaming()) return { ok: true };

    const model = this.model();
    const headers: Record<string, string> = {};
    if (model?.requires_reauth) {
      const unlock = this.modelService.unlockToken();
      if (unlock) headers['X-Premium-Unlock'] = unlock;
    }

    const now = new Date().toISOString();
    const userTempId = `local-user-${Date.now()}`;
    const replyId = `local-reply-${Date.now()}`;
    this._messages.update((list) => [
      ...list,
      { id: userTempId, role: 'user', content: text, status: 'complete', model: null, attachments, created_at: now },
      { id: replyId, role: 'assistant', content: '', status: 'complete', model: null, created_at: now, pending: true },
    ]);

    const controller = new AbortController();
    this.abort = controller;
    this._streaming.set(true);
    let replyKey = replyId;
    let result: SendResult = { ok: true };
    let finished = false; // a "done" or "error" event arrived

    const patchReply = (patch: Partial<UiMessage> | ((m: UiMessage) => Partial<UiMessage>)) =>
      this._messages.update((list) =>
        list.map((m) => (m.id === replyKey ? { ...m, ...(typeof patch === 'function' ? patch(m) : patch) } : m)),
      );

    const onEvent = ({ event, data }: SseEvent) => {
      if (this._chatId() !== chatId) return;
      const d = data as Record<string, any>;
      switch (event) {
        case 'start':
          this._messages.update((list) => list.map((m) => (m.id === userTempId ? (d['user_message'] as ChatMessage) : m)));
          patchReply({ model: d['model'] });
          break;
        case 'step':
          patchReply((m) => ({ steps: applyStep(m.steps ?? [], d as GraphStep) }));
          break;
        case 'token':
          patchReply((m) => ({ content: m.content + d['text'] }));
          break;
        case 'replace':
          patchReply({ content: d['text'], status: d['status'] as MessageStatus });
          break;
        case 'done': {
          finished = true;
          const message = d['message'] as ChatMessage | null;
          if (message) {
            patchReply({ ...message, pending: false });
            replyKey = message.id;
          } else {
            patchReply({ pending: false });
          }
          const chat = d['chat'] as ChatSummary | null;
          if (chat) {
            this.chats.upsert(chat);
            this._usage.set(usageOf(chat));
          }
          break;
        }
        case 'title':
          this.chats.upsert(d['chat'] as ChatSummary);
          break;
        case 'error':
          finished = true;
          patchReply({ pending: false, error: d['detail'] });
          break;
      }
    };

    try {
      await postSse(
        `/api/chats/${encodeURIComponent(chatId)}/messages`,
        {
          content: text,
          model: model?.id,
          attachment_ids: attachments.map((a) => a.id),
          timezone: browserTimezone(),
          mode: this.askData.mode(),
        },
        this.auth.token(),
        controller.signal,
        onEvent,
        headers,
      );
      if (!finished && this._chatId() === chatId) {
        // The stream closed without "done": never leave an empty or half-finished bubble silently.
        patchReply((m) => ({
          error: m.content
            ? 'The reply may be incomplete: it ended unexpectedly and may not have been saved.'
            : 'No reply came back. Please try again.',
        }));
      }
    } catch (err) {
      if (controller.signal.aborted) {
        patchReply((m) => ({ pending: false, status: m.content ? 'stopped' : m.status }));
        if (this._chatId() === chatId) {
          // The server saved the partial answer; drop the empty placeholder if nothing came.
          this._messages.update((list) => list.filter((m) => !(m.id === replyKey && !m.content)));
        }
        void this.chats.load();
      } else if (err instanceof HttpStatusError && err.status === 401) {
        this.auth.logout();
      } else if (err instanceof HttpStatusError && err.status < 500) {
        // Refused before anything was saved: undo the optimistic messages.
        this._messages.update((list) => list.filter((m) => m.id !== userTempId && m.id !== replyId));
        if (err.code === 'reauth_required') this.modelService.lock();
        result = {
          ok: false,
          reason: err.code === 'reauth_required' ? 'reauth_required' : 'rejected',
          detail: err.detail,
        };
        // Picked up by whichever chat page is on screen (navigation may have replaced it).
        this._failure.set({ ...result, text, attachments });
      } else {
        const detail = err instanceof HttpStatusError ? err.detail : 'Connection lost. Please try again.';
        patchReply({ pending: false, error: detail });
      }
    } finally {
      patchReply({ pending: false });
      if (this.abort === controller) {
        this.abort = null;
        this._streaming.set(false);
      }
    }
    return result;
  }

  stop(): void {
    this.abort?.abort();
  }

  reset(): void {
    this.stop();
    this._chatId.set(null);
    this._messages.set([]);
    this._usage.set(EMPTY_USAGE);
    this._model.set(null);
  }
}

/** Merge a LangGraph step event into the list (start, detail update, or finish). */
export function applyStep(steps: GraphStep[], event: GraphStep): GraphStep[] {
  const index = steps.findIndex((s) => s.node === event.node);
  if (index === -1) return [...steps, { ...event }];
  const current = steps[index];
  const next: GraphStep = {
    ...current,
    // A late "detail" never re-opens a finished step.
    status: current.status === 'done' && event.detail ? 'done' : event.status,
    detail: event.detail ?? current.detail,
  };
  return steps.map((s, i) => (i === index ? next : s));
}

export function isNotFound(err: unknown): boolean {
  return err instanceof HttpErrorResponse && err.status === 404;
}
