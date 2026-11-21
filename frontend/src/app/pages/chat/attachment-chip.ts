import { ChangeDetectionStrategy, Component, effect, inject, input, output, signal } from '@angular/core';

import { AttachmentService, formatBytes } from '../../core/attachment.service';
import { AttachmentInfo } from '../../core/models';

/**
 * One file: image thumbnail or document chip.
 * Used in the composer (removable, may be uploading) and in sent messages.
 */
@Component({
  selector: 'app-attachment-chip',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="chip" [class.image]="kind() === 'image'" [class.error]="!!error()" [title]="error() || name()">
      @if (kind() === 'image') {
        @if (src(); as url) {
          <img [src]="url" [alt]="name()" />
        } @else {
          <span class="thumb-placeholder" aria-hidden="true">🖼️</span>
        }
      } @else {
        <span class="icon" aria-hidden="true">{{ icon() }}</span>
        <span class="text">
          <span class="name">{{ name() }}</span>
          <span class="meta">{{ error() || subtitle() }}</span>
        </span>
      }
      @if (uploading()) {
        <span class="spinner" aria-label="Uploading"></span>
      }
      @if (removable()) {
        <button type="button" class="remove" (click)="remove.emit()" [attr.aria-label]="'Remove ' + name()">×</button>
      } @else if (info() && chatId()) {
        <button type="button" class="open" (click)="download()" [attr.aria-label]="'Download ' + name()"></button>
      }
    </div>
  `,
  styles: `
    :host { display: inline-block; }
    .chip {
      position: relative; display: flex; align-items: center; gap: 8px;
      max-width: 240px; height: 52px; padding: 6px 28px 6px 8px;
      border: 1px solid var(--border); border-radius: 12px; background: var(--bg);
    }
    .chip.image { width: 52px; padding: 0; overflow: hidden; }
    .chip.error { border-color: rgba(239, 68, 68, 0.6); }
    img { width: 100%; height: 100%; object-fit: cover; }
    .thumb-placeholder { margin: auto; }
    .icon {
      display: grid; place-items: center; flex: 0 0 36px; height: 36px; border-radius: 8px;
      background: #e5484d; color: #fff; font-size: 0.65rem; font-weight: 700;
    }
    .text { display: flex; flex-direction: column; min-width: 0; }
    .name { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-size: 0.8rem; font-weight: 500; }
    .meta { font-size: 0.7rem; color: var(--text-faint); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
    .chip.error .meta { color: #fca5a5; }
    .remove {
      position: absolute; top: 3px; right: 3px; width: 20px; height: 20px; padding: 0;
      border: 0; border-radius: 50%; background: #444; color: #fff; font-size: 0.9rem; line-height: 1;
    }
    .remove:hover { background: #666; }
    .open { position: absolute; inset: 0; border: 0; background: transparent; cursor: pointer; }
    .spinner {
      position: absolute; top: 50%; left: 50%; width: 18px; height: 18px; margin: -9px 0 0 -9px;
      border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff; border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    .chip:not(.image) .spinner { left: auto; right: 8px; margin-left: 0; }
    @keyframes spin { to { transform: rotate(360deg); } }
  `,
})
export class AttachmentChip {
  private readonly files = inject(AttachmentService);

  readonly name = input.required<string>();
  readonly kind = input.required<'image' | 'document'>();
  readonly size = input(0);
  readonly info = input<AttachmentInfo | null>(null);
  readonly chatId = input<string | null>(null);
  /** Local object URL for a just-picked image (before/while uploading). */
  readonly previewUrl = input<string | null>(null);
  readonly uploading = input(false);
  readonly error = input<string | null>(null);
  readonly removable = input(false);
  readonly remove = output<void>();

  protected readonly src = signal<string | null>(null);

  constructor() {
    effect(() => {
      const local = this.previewUrl();
      const info = this.info();
      const chatId = this.chatId();
      if (local) {
        this.src.set(local);
      } else if (info?.kind === 'image' && chatId) {
        this.files.imageUrl(chatId, info.id).then((url) => this.src.set(url), () => this.src.set(null));
      }
    });
  }

  protected icon(): string {
    const ext = this.name().split('.').pop()?.toUpperCase() ?? 'FILE';
    return ext.length > 4 ? 'FILE' : ext;
  }

  protected subtitle(): string {
    const info = this.info();
    if (this.uploading()) return 'Uploading…';
    if (info?.kind === 'document' && info.text_chars === 0) return 'No readable text';
    return formatBytes(this.size());
  }

  protected download(): void {
    const info = this.info();
    const chatId = this.chatId();
    if (info && chatId) void this.files.download(chatId, info);
  }
}
