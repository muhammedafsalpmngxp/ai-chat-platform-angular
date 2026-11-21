import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { TitleCasePipe } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { Router, RouterLink } from '@angular/router';

import { AskDataService } from '../../core/ask-data.service';
import { AttachmentService, formatBytes } from '../../core/attachment.service';
import { AuthService } from '../../core/auth.service';
import { ChatService } from '../../core/chat.service';
import { ChatSessionService, SendFailure, isNotFound } from '../../core/chat-session.service';
import { CHECK_ICON, COPY_ICON, renderMarkdown, stripCitations } from '../../core/markdown';
import { ModelService } from '../../core/model.service';
import { GraphStep, PendingFile, UiMessage } from '../../core/models';
import { AskDataResultView } from './ask-data-result';
import { AttachmentChip } from './attachment-chip';
import { ContextMeter } from './context-meter';
import { ModelPicker } from './model-picker';

@Component({
  selector: 'app-chat-page',
  imports: [ContextMeter, ModelPicker, AttachmentChip, AskDataResultView, RouterLink, TitleCasePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './chat-page.html',
  styleUrl: './chat-page.scss',
})
export class ChatPage {
  private readonly chatService = inject(ChatService);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly modelService = inject(ModelService);
  protected readonly session = inject(ChatSessionService);
  protected readonly files = inject(AttachmentService);
  protected readonly askData = inject(AskDataService);

  /** The Ask Data toggle (only when the server has Ask Data configured). */
  protected readonly askDataOn = computed(
    () => !!this.files.config()?.ask_data_enabled && this.askData.mode() === 'ask_data',
  );

  /** Route param /c/:id (bound via withComponentInputBinding). */
  readonly id = input<string>();

  protected readonly draft = signal('');
  protected readonly loadError = signal<string | null>(null);
  protected readonly copiedId = signal<string | null>(null);
  protected readonly sendError = signal<string | null>(null);
  protected readonly dragging = signal(false);
  protected readonly bytes = formatBytes;

  private readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');
  private readonly textarea = viewChild<ElementRef<HTMLTextAreaElement>>('composer');
  private readonly fileInput = viewChild<ElementRef<HTMLInputElement>>('fileInput');
  private stickToBottom = true;
  private readonly htmlCache = new Map<string, { source: string; html: SafeHtml }>();

  protected readonly title = computed(() => {
    const id = this.id();
    return id ? (this.chatService.chats().find((c) => c.id === id)?.title ?? '') : '';
  });

  protected readonly greeting = computed(() => {
    const name = this.auth.user()?.display_name;
    return name ? `How can I help you today, ${name}?` : 'How can I help you today?';
  });

  /** Files already sent in this chat (they count towards the per-chat limit). */
  private readonly usedFiles = computed(() =>
    this.session.messages().reduce((n, m) => n + (m.attachments?.length ?? 0), 0),
  );

  protected readonly canAttach = computed(() => {
    const config = this.files.config();
    if (!config || this.session.streaming()) return false;
    return this.usedFiles() + this.files.pending().filter((p) => !p.error).length < config.max_files_per_chat;
  });

  protected readonly canSend = computed(
    () =>
      !this.session.streaming() &&
      !this.files.uploading() &&
      (this.draft().trim().length > 0 || this.files.ready().length > 0),
  );

  constructor() {
    void this.files.loadConfig();
    void this.askData.load();

    effect(() => {
      const id = this.id() ?? null;
      untracked(() => void this.open(id));
    });

    effect(() => {
      const failure = this.session.failure();
      if (failure) untracked(() => void this.handleFailure(failure));
    });

    // Keep the newest text in view while streaming (unless the user scrolled up).
    effect(() => {
      this.session.messages();
      if (this.stickToBottom) requestAnimationFrame(() => this.scrollToBottom());
    });
  }

  private async open(id: string | null): Promise<void> {
    this.loadError.set(null);
    this.stickToBottom = true;
    try {
      await this.session.open(id);
      await this.files.syncFor(id, this.session.messages());
      requestAnimationFrame(() => {
        this.scrollToBottom();
        this.textarea()?.nativeElement.focus();
      });
    } catch (err) {
      if (isNotFound(err)) await this.router.navigate(['/']);
      else this.loadError.set('Could not load this chat.');
    }
  }

  protected async submit(): Promise<void> {
    if (!this.canSend()) return;
    const text = this.draft().trim();
    this.sendError.set(null);

    // Premium model: ask for the password before anything is sent.
    const model = this.session.model();
    if (model?.requires_reauth && !(await this.modelService.requestUnlock(model))) return;

    let chatId: string;
    try {
      chatId = await this.session.ensureChat();
    } catch {
      this.loadError.set('Could not start a new chat. Is the backend running?');
      return;
    }
    this.draft.set('');
    this.resizeComposer();
    this.stickToBottom = true;
    void this.session.send(text, this.files.take()); // starts synchronously, before navigation
    if (this.id() !== chatId) await this.router.navigate(['/c', chatId]);
  }

  protected toggleAskData(): void {
    this.askData.setMode(this.askDataOn() ? 'auto' : 'ask_data');
    this.textarea()?.nativeElement.focus();
  }

  /** A suggested follow-up under an Ask Data answer. */
  protected async askFollowup(question: string): Promise<void> {
    if (this.session.streaming()) return;
    this.draft.set(question);
    await this.submit();
  }

  // ---------------------------------------------------------------- uploads

  protected pickFiles(): void {
    this.fileInput()?.nativeElement.click();
  }

  protected async onFilesChosen(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const chosen = Array.from(input.files ?? []);
    input.value = ''; // allow choosing the same file again
    await this.addFiles(chosen);
  }

  protected onDragOver(event: DragEvent): void {
    if (!event.dataTransfer?.types.includes('Files')) return;
    event.preventDefault();
    this.dragging.set(true);
  }

  protected async onDrop(event: DragEvent): Promise<void> {
    event.preventDefault();
    this.dragging.set(false);
    await this.addFiles(Array.from(event.dataTransfer?.files ?? []));
  }

  protected async onPaste(event: ClipboardEvent): Promise<void> {
    const pasted = Array.from(event.clipboardData?.files ?? []);
    if (!pasted.length) return;
    event.preventDefault();
    await this.addFiles(pasted);
  }

  private async addFiles(chosen: File[]): Promise<void> {
    if (!chosen.length || this.session.streaming()) return;
    this.sendError.set(null);
    const problem = this.files.check(chosen, this.usedFiles());
    if (problem) {
      this.sendError.set(problem);
      return;
    }
    let chatId: string;
    try {
      chatId = await this.session.ensureChat();
    } catch {
      this.sendError.set('Could not start a new chat. Is the backend running?');
      return;
    }
    const upload = this.files.upload(chatId, chosen);
    if (this.id() !== chatId) await this.router.navigate(['/c', chatId]);
    await upload;
  }

  protected removeFile(file: PendingFile): void {
    void this.files.remove(this.session.chatId(), file);
  }

  // ------------------------------------------------------------- composer

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void this.submit();
    }
  }

  protected onInput(event: Event): void {
    this.draft.set((event.target as HTMLTextAreaElement).value);
    this.sendError.set(null);
    this.resizeComposer();
  }

  /** The server refused a message (e.g. premium unlock expired): restore it and explain. */
  private async handleFailure(failure: SendFailure): Promise<void> {
    this.session.clearFailure();
    this.draft.set(failure.text);
    this.files.restore(failure.attachments);
    requestAnimationFrame(() => this.resizeComposer());
    const model = this.session.model();
    if (failure.reason === 'reauth_required' && model) {
      if (await this.modelService.requestUnlock(model)) {
        await this.submit(); // retry with the fresh unlock
        return;
      }
    }
    this.sendError.set(failure.detail);
  }

  protected onScroll(): void {
    const el = this.scroller()?.nativeElement;
    if (el) this.stickToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  // ------------------------------------------------------------- messages

  protected html(message: UiMessage): SafeHtml {
    const cached = this.htmlCache.get(message.id);
    if (cached && cached.source === message.content) return cached.html;
    // Web answers: hide [1]-style markers even while streaming and in older saved replies.
    const isWebAnswer = !!message.sources?.length || !!message.steps?.some((s) => s.node === 'synthesizer');
    const text = isWebAnswer ? stripCitations(message.content) : message.content;
    const html = this.sanitizer.bypassSecurityTrustHtml(renderMarkdown(text));
    this.htmlCache.set(message.id, { source: message.content, html });
    return html;
  }

  /** Replies whose source list is expanded (collapsed by default). */
  protected readonly openSources = signal<ReadonlySet<string>>(new Set());

  protected toggleSources(messageId: string): void {
    this.openSources.update((open) => {
      const next = new Set(open);
      if (next.has(messageId)) next.delete(messageId);
      else next.add(messageId);
      return next;
    });
  }

  protected confidenceHint(level: string): string {
    return (
      {
        high: 'Several reputable sources agree on this answer.',
        medium: 'Sources mostly agree, with some differences.',
        low: 'Few sources or conflicting figures - double-check before relying on it.',
      } as Record<string, string>
    )[level] ?? '';
  }

  /** The LangGraph node working right now (else the last one that ran). */
  protected currentStep(message: UiMessage): GraphStep | null {
    const steps = message.steps ?? [];
    return [...steps].reverse().find((s) => s.status === 'running') ?? steps.at(-1) ?? null;
  }

  protected domain(url: string): string {
    try {
      return new URL(url).hostname.replace(/^www\./, '');
    } catch {
      return url;
    }
  }

  /** Handles the "Copy" buttons inside rendered code blocks. */
  protected async onMessagesClick(event: MouseEvent): Promise<void> {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>('.copy-code');
    const code = button?.closest('.code-block')?.querySelector('code');
    if (!button || !code) return;
    try {
      await navigator.clipboard.writeText(code.textContent ?? '');
    } catch {
      return; // clipboard blocked: keep the copy icon
    }
    button.innerHTML = CHECK_ICON;
    button.setAttribute('aria-label', 'Copied');
    setTimeout(() => {
      button.innerHTML = COPY_ICON;
      button.setAttribute('aria-label', 'Copy code');
    }, 1500);
  }

  protected async copyMessage(message: UiMessage): Promise<void> {
    try {
      await navigator.clipboard.writeText(message.content);
    } catch {
      return; // clipboard blocked (permissions / insecure context): keep the copy icon
    }
    this.copiedId.set(message.id);
    setTimeout(() => this.copiedId.set(null), 1500);
  }

  private resizeComposer(): void {
    const el = this.textarea()?.nativeElement;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  private scrollToBottom(): void {
    const el = this.scroller()?.nativeElement;
    if (el) el.scrollTop = el.scrollHeight;
  }
}
