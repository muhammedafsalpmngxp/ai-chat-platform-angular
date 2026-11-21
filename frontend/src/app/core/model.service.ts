import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { ModelCatalog, ModelInfo } from './models';

const LAST_MODEL_KEY = 'chatbot.lastModel';

interface UnlockRequest {
  model: ModelInfo;
  resolve: (unlocked: boolean) => void;
}

/** Model catalog, the premium unlock (password re-check) and the remembered model choice. */
@Injectable({ providedIn: 'root' })
export class ModelService {
  private readonly http = inject(HttpClient);

  private readonly _catalog = signal<ModelCatalog | null>(null);
  private readonly _unlock = signal<{ token: string; expiresAt: number } | null>(null);
  private readonly _unlockRequest = signal<UnlockRequest | null>(null);

  readonly catalog = this._catalog.asReadonly();
  readonly models = computed(() => this._catalog()?.models ?? []);
  readonly defaultId = computed(() => this._catalog()?.default_model ?? null);
  readonly defaultModel = computed(() => this.get(this.defaultId()));
  /** Set while the premium password dialog should be shown. */
  readonly unlockRequest = this._unlockRequest.asReadonly();

  private loading: Promise<void> | null = null;

  load(): Promise<void> {
    this.loading ??= firstValueFrom(this.http.get<ModelCatalog>('/api/models'))
      .then((catalog) => this._catalog.set(catalog))
      .catch((err) => {
        this.loading = null;
        throw err;
      });
    return this.loading;
  }

  get(id: string | null | undefined): ModelInfo | null {
    return this.models().find((m) => m.id === id) ?? null;
  }

  /** The model new chats start with: the last one picked, else the default. */
  lastUsed(): string | null {
    try {
      const id = localStorage.getItem(LAST_MODEL_KEY);
      if (id && this.get(id)) return id;
    } catch {
      /* storage blocked */
    }
    return this.defaultId();
  }

  remember(id: string): void {
    try {
      localStorage.setItem(LAST_MODEL_KEY, id);
    } catch {
      /* storage blocked */
    }
  }

  // ---------------------------------------------------------------- premium

  /** Current unlock token, or null if missing or (nearly) expired. */
  unlockToken(): string | null {
    const unlock = this._unlock();
    return unlock && unlock.expiresAt - Date.now() > 5_000 ? unlock.token : null;
  }

  isUnlocked(): boolean {
    return this.unlockToken() !== null;
  }

  /** Throws HttpErrorResponse on a wrong password (403) or lockout (429). */
  async reauth(password: string): Promise<void> {
    const res = await firstValueFrom(
      this.http.post<{ unlock_token: string; expires_in: number }>('/api/auth/reauth', { password }),
    );
    // Kept in memory only: a page reload asks for the password again.
    this._unlock.set({ token: res.unlock_token, expiresAt: Date.now() + res.expires_in * 1000 });
  }

  lock(): void {
    this._unlock.set(null);
  }

  /** Ask for the password (shows the premium dialog). Resolves true once unlocked. */
  requestUnlock(model: ModelInfo): Promise<boolean> {
    if (this.isUnlocked()) return Promise.resolve(true);
    this._unlockRequest()?.resolve(false);
    return new Promise((resolve) => this._unlockRequest.set({ model, resolve }));
  }

  /** Called by the dialog when it closes. */
  finishUnlock(unlocked: boolean): void {
    const request = this._unlockRequest();
    this._unlockRequest.set(null);
    request?.resolve(unlocked);
  }

  static errorMessage(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      if (err.status === 403) return 'Incorrect password.';
      if (err.status === 429) return err.error?.detail ?? 'Too many attempts. Try again later.';
    }
    return 'Could not verify your password. Is the backend running?';
  }
}

/** "≈80×" style label for prices compared with the default model. */
export function relativeCostLabel(model: ModelInfo): string {
  const value = model.relative_cost;
  if (model.is_default) return 'baseline';
  const rounded = value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return `≈${rounded}× Luna`;
}

export function formatPrice(value: number | null): string {
  if (value === null) return '—';
  return `$${value < 1 ? value.toFixed(value < 0.1 ? 3 : 2) : value.toFixed(2)}`;
}

export function formatCost(usd: number): string {
  if (usd === 0) return '$0.00';
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}
