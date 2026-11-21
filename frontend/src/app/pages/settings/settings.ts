import { ChangeDetectionStrategy, Component, ElementRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';

import { AskDataService } from '../../core/ask-data.service';
import { AuthService } from '../../core/auth.service';
import { ModelService, formatPrice, relativeCostLabel } from '../../core/model.service';

@Component({
  selector: 'app-settings',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './settings.html',
  styleUrl: './settings.scss',
})
export class Settings implements OnInit {
  protected readonly auth = inject(AuthService);
  protected readonly models = inject(ModelService);
  private readonly route = inject(ActivatedRoute);
  private readonly host = inject(ElementRef<HTMLElement>);

  protected readonly askData = inject(AskDataService);

  protected readonly price = formatPrice;
  protected readonly relative = relativeCostLabel;

  // Company account form (the password only lives in this field until it is sent).
  protected readonly email = signal('');
  protected readonly password = signal('');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected async connect(): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.askData.connect(this.email().trim(), this.password());
      this.askData.setMode('ask_data');
    } catch (err) {
      this.error.set(AskDataService.errorMessage(err));
    } finally {
      this.password.set('');
      this.busy.set(false);
    }
  }

  protected async disconnect(): Promise<void> {
    this.busy.set(true);
    try {
      await this.askData.disconnect();
      this.askData.setMode('auto');
    } finally {
      this.busy.set(false);
    }
  }

  constructor() {
    // This page scrolls inside its own container, so jump to #pricing manually.
    this.route.fragment.pipe(takeUntilDestroyed()).subscribe((fragment) => {
      if (!fragment) return;
      setTimeout(() => this.host.nativeElement.querySelector(`#${CSS.escape(fragment)}`)?.scrollIntoView());
    });
  }

  ngOnInit(): void {
    void this.models.load();
    void this.askData.load();
  }
}
