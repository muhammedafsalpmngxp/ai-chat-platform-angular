import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { ChatService } from '../../core/chat.service';
import { ModelService } from '../../core/model.service';
import { PremiumDialog } from '../../shared/premium-dialog';
import { Sidebar } from '../sidebar/sidebar';

const MOBILE_QUERY = '(max-width: 767px)';

@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, Sidebar, PremiumDialog],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './shell.html',
  styleUrl: './shell.scss',
})
export class Shell implements OnInit {
  private readonly chats = inject(ChatService);
  private readonly models = inject(ModelService);
  private readonly media = window.matchMedia(MOBILE_QUERY);

  protected readonly isMobile = signal(this.media.matches);
  protected readonly sidebarOpen = signal(!this.media.matches);

  constructor() {
    this.media.addEventListener('change', (e) => {
      this.isMobile.set(e.matches);
      this.sidebarOpen.set(!e.matches);
    });
    // On phones, close the drawer after navigating to a chat.
    inject(Router)
      .events.pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => {
        if (this.isMobile()) this.sidebarOpen.set(false);
      });
  }

  ngOnInit(): void {
    void this.chats.load();
    void this.models.load().catch(() => undefined); // picker shows "Loading…" until it works
  }

  protected toggleSidebar(): void {
    this.sidebarOpen.update((open) => !open);
  }
}
