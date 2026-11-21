import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AskDataStatus, ChatMode } from './models';

const MODE_KEY = 'chatbot.chatMode';

/**
 * The user's company account for Ask Data, and the Ask Data toggle.
 * The company password goes to our backend once (to sign in) and is never stored.
 */
@Injectable({ providedIn: 'root' })
export class AskDataService {
  private readonly http = inject(HttpClient);

  private readonly _status = signal<AskDataStatus | null>(null);
  private readonly _mode = signal<ChatMode>(this.readMode());

  readonly status = this._status.asReadonly();
  /** "ask_data" = send messages to the company data agent. */
  readonly mode = this._mode.asReadonly();

  async load(): Promise<void> {
    try {
      this._status.set(await firstValueFrom(this.http.get<AskDataStatus>('/api/ask-data/status')));
    } catch {
      this._status.set(null);
    }
  }

  async connect(email: string, password: string): Promise<void> {
    this._status.set(
      await firstValueFrom(this.http.post<AskDataStatus>('/api/ask-data/connect', { email, password })),
    );
  }

  async disconnect(): Promise<void> {
    this._status.set(await firstValueFrom(this.http.post<AskDataStatus>('/api/ask-data/disconnect', {})));
  }

  setMode(mode: ChatMode): void {
    this._mode.set(mode);
    try {
      localStorage.setItem(MODE_KEY, mode);
    } catch {
      /* storage blocked */
    }
  }

  static errorMessage(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      if (typeof err.error?.detail === 'string') return err.error.detail;
      if (err.status === 0) return 'Could not reach the backend.';
    }
    return 'Could not connect to the company server.';
  }

  private readMode(): ChatMode {
    try {
      return localStorage.getItem(MODE_KEY) === 'ask_data' ? 'ask_data' : 'auto';
    } catch {
      return 'auto';
    }
  }
}
