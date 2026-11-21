import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map } from 'rxjs';

import { AuthService } from '../../core/auth.service';
import { ChatService } from '../../core/chat.service';
import { ChatSessionService } from '../../core/chat-session.service';
import { ModelService } from '../../core/model.service';
import { groupChats } from '../../core/chat-groups';
import { ChatSummary } from '../../core/models';

@Component({
  selector: 'app-sidebar',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sidebar.html',
  styleUrl: './sidebar.scss',
  host: {
    '(document:click)': 'closeMenus($event)',
    '(document:keydown.escape)': 'onEscape()',
  },
})
export class Sidebar {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly host = inject(ElementRef<HTMLElement>);
  protected readonly chatService = inject(ChatService);
  private readonly session = inject(ChatSessionService);
  private readonly models = inject(ModelService);

  readonly collapse = output<void>();

  protected readonly user = this.auth.user;
  protected readonly search = signal('');
  protected readonly menuFor = signal<string | null>(null);
  protected readonly renamingId = signal<string | null>(null);
  protected readonly confirmDelete = signal<ChatSummary | null>(null);
  protected readonly userMenuOpen = signal(false);
  protected readonly busy = signal(false);
  protected readonly actionError = signal<string | null>(null);

  private readonly renameInput = viewChild<ElementRef<HTMLInputElement>>('renameInput');

  /** Id of the chat currently open in the router (/c/:id). */
  protected readonly activeId = toSignal(
    this.router.events.pipe(
      filter((e) => e instanceof NavigationEnd),
      map(() => this.currentChatId()),
    ),
    { initialValue: this.currentChatId() },
  );

  protected readonly groups = computed(() => {
    const term = this.search().trim().toLowerCase();
    const chats = this.chatService.chats();
    return groupChats(term ? chats.filter((c) => c.title.toLowerCase().includes(term)) : chats);
  });

  protected readonly initials = computed(() => {
    const name = this.user()?.display_name || this.user()?.username || '?';
    return name
      .split(/\s+/)
      .map((p) => p[0])
      .join('')
      .slice(0, 2)
      .toUpperCase();
  });

  /** Like ChatGPT: opens the empty screen; the chat is created on the first message. */
  protected async newChat(): Promise<void> {
    this.search.set('');
    this.actionError.set(null);
    await this.router.navigate(['/']);
  }

  protected toggleMenu(chatId: string, event: Event): void {
    event.stopPropagation();
    event.preventDefault();
    this.userMenuOpen.set(false);
    this.menuFor.update((current) => (current === chatId ? null : chatId));
  }

  protected startRename(chat: ChatSummary): void {
    this.menuFor.set(null);
    this.renamingId.set(chat.id);
    setTimeout(() => {
      const input = this.renameInput()?.nativeElement;
      input?.focus();
      input?.select();
    });
  }

  protected async commitRename(chat: ChatSummary, value: string): Promise<void> {
    if (this.renamingId() !== chat.id) return;
    this.renamingId.set(null);
    const title = value.trim();
    if (!title || title === chat.title) return;
    try {
      await this.chatService.rename(chat.id, title);
    } catch {
      this.actionError.set('Could not rename the chat.');
    }
  }

  protected cancelRename(): void {
    this.renamingId.set(null);
  }

  protected askDelete(chat: ChatSummary): void {
    this.menuFor.set(null);
    this.confirmDelete.set(chat);
  }

  protected async deleteConfirmed(): Promise<void> {
    const chat = this.confirmDelete();
    if (!chat) return;
    this.confirmDelete.set(null);
    try {
      await this.chatService.remove(chat.id);
      if (this.activeId() === chat.id) await this.router.navigate(['/']);
    } catch {
      this.actionError.set('Could not delete the chat.');
    }
  }

  protected toggleUserMenu(event: Event): void {
    event.stopPropagation();
    this.menuFor.set(null);
    this.userMenuOpen.update((open) => !open);
  }

  protected logout(): void {
    this.userMenuOpen.set(false);
    this.session.reset();
    this.chatService.reset();
    this.models.lock();
    this.auth.logout();
  }

  protected closeMenus(event: Event): void {
    if (!this.host.nativeElement.contains(event.target as Node)) {
      this.menuFor.set(null);
      this.userMenuOpen.set(false);
      return;
    }
    const target = event.target as HTMLElement;
    if (!target.closest('.menu, .menu-trigger')) {
      this.menuFor.set(null);
      this.userMenuOpen.set(false);
    }
  }

  protected onEscape(): void {
    this.menuFor.set(null);
    this.userMenuOpen.set(false);
    this.confirmDelete.set(null);
  }

  protected inputValue(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  private currentChatId(): string | null {
    const match = this.router.url.match(/^\/c\/([^/?#]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }
}
