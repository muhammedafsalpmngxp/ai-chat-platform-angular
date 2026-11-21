import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { ChatDetail, ChatSummary } from './models';

/** The chat list in the sidebar, plus CRUD calls. */
@Injectable({ providedIn: 'root' })
export class ChatService {
  private readonly http = inject(HttpClient);

  private readonly _chats = signal<ChatSummary[]>([]);
  private readonly _loading = signal(false);
  private readonly _error = signal<string | null>(null);

  readonly chats = this._chats.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  async load(): Promise<void> {
    this._loading.set(true);
    this._error.set(null);
    try {
      this._chats.set(await firstValueFrom(this.http.get<ChatSummary[]>('/api/chats')));
    } catch {
      this._error.set('Could not load your chats.');
    } finally {
      this._loading.set(false);
    }
  }

  async create(): Promise<ChatSummary> {
    const chat = await firstValueFrom(this.http.post<ChatSummary>('/api/chats', {}));
    this.upsert(chat);
    return chat;
  }

  get(id: string): Promise<ChatDetail> {
    return firstValueFrom(this.http.get<ChatDetail>(`/api/chats/${encodeURIComponent(id)}`));
  }

  async rename(id: string, title: string): Promise<void> {
    const updated = await firstValueFrom(
      this.http.patch<ChatSummary>(`/api/chats/${encodeURIComponent(id)}`, { title }),
    );
    this.upsert(updated);
  }

  async remove(id: string): Promise<void> {
    await firstValueFrom(this.http.delete<void>(`/api/chats/${encodeURIComponent(id)}`));
    this._chats.update((list) => list.filter((c) => c.id !== id));
  }

  /** Insert or update a chat and move it to the top (most recently updated). */
  upsert(chat: ChatSummary): void {
    this._chats.update((list) => [chat, ...list.filter((c) => c.id !== chat.id)]);
  }

  /** Clears cached chats (on logout). */
  reset(): void {
    this._chats.set([]);
  }
}
