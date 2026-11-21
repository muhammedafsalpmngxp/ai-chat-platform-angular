import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { TokenResponse, User } from './models';

const TOKEN_KEY = 'chatbot.token';
const EXPIRES_KEY = 'chatbot.tokenExpiresAt';

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Storage blocked (private mode etc.) - token lives in memory only.
  }
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  private readonly _token = signal<string | null>(this.loadValidToken());
  private readonly _user = signal<User | null>(null);

  readonly token = this._token.asReadonly();
  readonly user = this._user.asReadonly();
  readonly isAuthenticated = computed(() => this._token() !== null && this._user() !== null);

  /** Called once at app start: restores the session if a saved token is still valid. */
  async restoreSession(): Promise<void> {
    if (!this._token()) return;
    try {
      this._user.set(await firstValueFrom(this.http.get<User>('/api/auth/me')));
    } catch {
      this.clear();
    }
  }

  async login(username: string, password: string): Promise<void> {
    const res = await firstValueFrom(
      this.http.post<TokenResponse>('/api/auth/login', { username, password }),
    );
    const expiresAt = Date.now() + res.expires_in * 1000;
    writeStorage(TOKEN_KEY, res.access_token);
    writeStorage(EXPIRES_KEY, String(expiresAt));
    this._token.set(res.access_token);
    this._user.set(res.user);
  }

  logout(): void {
    this.clear();
    void this.router.navigate(['/login']);
  }

  private clear(): void {
    writeStorage(TOKEN_KEY, null);
    writeStorage(EXPIRES_KEY, null);
    this._token.set(null);
    this._user.set(null);
  }

  private loadValidToken(): string | null {
    const token = readStorage(TOKEN_KEY);
    const expiresAt = Number(readStorage(EXPIRES_KEY));
    if (!token || !expiresAt || expiresAt <= Date.now()) return null;
    return token;
  }
}
