import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AttachmentInfo, ChatMessage, ClientConfig, PendingFile } from './models';

const IMAGE_EXT = /\.(png|jpe?g|webp|gif)$/i;

/**
 * Files waiting in the composer for the open chat, upload limits,
 * and cached image previews. Root-scoped so uploads survive the
 * "/" -> "/c/:id" navigation after the first file is attached.
 */
@Injectable({ providedIn: 'root' })
export class AttachmentService {
  private readonly http = inject(HttpClient);

  private readonly _config = signal<ClientConfig | null>(null);
  private readonly _pending = signal<PendingFile[]>([]);
  private readonly blobUrls = new Map<string, Promise<string>>();
  private pendingChatId: string | null = null;
  private seq = 0;

  readonly config = this._config.asReadonly();
  readonly pending = this._pending.asReadonly();
  readonly uploading = computed(() => this._pending().some((p) => !p.info && !p.error));
  readonly ready = computed(() => this._pending().filter((p) => p.info).map((p) => p.info!));

  async loadConfig(): Promise<void> {
    if (this._config()) return;
    try {
      this._config.set(await firstValueFrom(this.http.get<ClientConfig>('/api/config')));
    } catch {
      /* the attach button stays disabled until it loads */
    }
  }

  /** Show the files still waiting to be sent in this chat (e.g. after a reload). */
  async syncFor(chatId: string | null, messages: ChatMessage[]): Promise<void> {
    if (chatId === this.pendingChatId) return;
    this.clear();
    this.pendingChatId = chatId;
    if (!chatId) return;
    try {
      const all = await firstValueFrom(
        this.http.get<AttachmentInfo[]>(`/api/chats/${encodeURIComponent(chatId)}/attachments`),
      );
      if (this.pendingChatId !== chatId) return;
      const used = new Set(messages.flatMap((m) => (m.attachments ?? []).map((a) => a.id)));
      this._pending.set(
        all.filter((a) => !used.has(a.id)).map((info) => ({
          key: `srv-${info.id}`,
          name: info.name,
          size: info.size,
          kind: info.kind,
          previewUrl: null,
          info,
          error: null,
        })),
      );
    } catch {
      /* nothing pending */
    }
  }

  /** Check limits on the client first, for instant feedback. Returns an error or null. */
  check(files: File[], alreadyInChat: number): string | null {
    const config = this._config();
    if (!config) return 'Uploads are not available yet. Please try again.';
    const slots = config.max_files_per_chat - alreadyInChat - this._pending().filter((p) => !p.error).length;
    if (files.length > slots) {
      return slots <= 0
        ? `A chat can have at most ${config.max_files_per_chat} files.`
        : `You can add ${slots} more file${slots === 1 ? '' : 's'} to this chat (max ${config.max_files_per_chat}).`;
    }
    const tooBig = files.find((f) => f.size > config.max_upload_mb * 1024 * 1024);
    if (tooBig) return `${tooBig.name} is larger than ${config.max_upload_mb} MB.`;
    return null;
  }

  /** Upload files to the chat; each shows in the composer while uploading. */
  async upload(chatId: string, files: File[]): Promise<void> {
    this.pendingChatId = chatId;
    const entries = files.map((file) => {
      const isImage = IMAGE_EXT.test(file.name);
      const entry: PendingFile = {
        key: `local-${++this.seq}`,
        name: file.name,
        size: file.size,
        kind: isImage ? 'image' : 'document',
        previewUrl: isImage ? URL.createObjectURL(file) : null,
        info: null,
        error: null,
      };
      return { file, entry };
    });
    this._pending.update((list) => [...list, ...entries.map((e) => e.entry)]);

    await Promise.all(
      entries.map(async ({ file, entry }) => {
        const form = new FormData();
        form.append('file', file, file.name);
        try {
          const info = await firstValueFrom(
            this.http.post<AttachmentInfo>(`/api/chats/${encodeURIComponent(chatId)}/attachments`, form),
          );
          this.patch(entry.key, { info, kind: info.kind });
        } catch (err) {
          const detail =
            err instanceof HttpErrorResponse && typeof err.error?.detail === 'string'
              ? err.error.detail
              : 'Upload failed.';
          this.patch(entry.key, { error: detail });
        }
      }),
    );
  }

  async remove(chatId: string | null, file: PendingFile): Promise<void> {
    this._pending.update((list) => list.filter((p) => p.key !== file.key));
    if (file.previewUrl) URL.revokeObjectURL(file.previewUrl);
    if (chatId && file.info) {
      try {
        await firstValueFrom(
          this.http.delete(`/api/chats/${encodeURIComponent(chatId)}/attachments/${file.info.id}`),
        );
      } catch {
        /* already gone */
      }
    }
  }

  /** Hand the ready files to a message being sent and clear the composer. */
  take(): AttachmentInfo[] {
    const ready = this.ready();
    for (const p of this._pending()) if (p.previewUrl) URL.revokeObjectURL(p.previewUrl);
    this._pending.set([]);
    return ready;
  }

  /** Put files back after a send was refused. */
  restore(infos: AttachmentInfo[]): void {
    this._pending.update((list) => [
      ...infos.map((info) => ({
        key: `srv-${info.id}`,
        name: info.name,
        size: info.size,
        kind: info.kind,
        previewUrl: null,
        info,
        error: null,
      })),
      ...list,
    ]);
  }

  clear(): void {
    for (const p of this._pending()) if (p.previewUrl) URL.revokeObjectURL(p.previewUrl);
    this._pending.set([]);
    this.pendingChatId = null;
  }

  /** Authenticated image preview as an object URL (cached). */
  imageUrl(chatId: string, attachmentId: string): Promise<string> {
    const key = `${chatId}/${attachmentId}`;
    let url = this.blobUrls.get(key);
    if (!url) {
      url = firstValueFrom(
        this.http.get(`/api/chats/${encodeURIComponent(chatId)}/attachments/${attachmentId}`, {
          responseType: 'blob',
        }),
      ).then((blob) => URL.createObjectURL(blob));
      url.catch(() => this.blobUrls.delete(key));
      this.blobUrls.set(key, url);
    }
    return url;
  }

  async download(chatId: string, info: AttachmentInfo): Promise<void> {
    const blob = await firstValueFrom(
      this.http.get(`/api/chats/${encodeURIComponent(chatId)}/attachments/${info.id}`, { responseType: 'blob' }),
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = info.name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  private patch(key: string, patch: Partial<PendingFile>): void {
    this._pending.update((list) => list.map((p) => (p.key === key ? { ...p, ...patch } : p)));
  }
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
