import { ChangeDetectionStrategy, Component, ElementRef, computed, effect, inject, signal, viewChild } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ModelService, formatPrice, relativeCostLabel } from '../core/model.service';

/** Cost warning + "re-enter your password" for premium models. Lives in the shell. */
@Component({
  selector: 'app-premium-dialog',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(document:keydown.escape)': 'cancel()' },
  template: `
    @if (request(); as req) {
      <div class="app-dialog-backdrop" (click)="cancel()">
        <form class="app-dialog" role="dialog" aria-modal="true" aria-labelledby="premium-title"
              (click)="$event.stopPropagation()" (submit)="$event.preventDefault(); submit()">
          <h3 id="premium-title">💎 Use {{ req.model.label }}?</h3>
          <div class="cost">
            <span class="badge premium">Premium · {{ relative(req.model) }}</span>
            <span class="prices">{{ price(req.model.input_price) }} in / {{ price(req.model.output_price) }} out per 1M tokens</span>
          </div>
          <p>
            {{ req.model.warning || 'This model costs much more per token than the recommended model.' }}
            <a routerLink="/settings" fragment="pricing" (click)="cancel()">See pricing in Settings</a>
          </p>
          <label class="field">
            <span>Re-enter your login password to unlock premium models for {{ minutes() }} minutes</span>
            <input #password type="password" autocomplete="current-password" [value]="value()"
                   (input)="value.set($any($event.target).value)" />
          </label>
          @if (error(); as message) {
            <p class="error" role="alert">{{ message }}</p>
          }
          <div class="actions">
            <button type="button" class="btn" (click)="cancel()">Cancel</button>
            <button type="submit" class="btn primary" [disabled]="busy() || !value()">
              {{ busy() ? 'Checking…' : 'Unlock and use' }}
            </button>
          </div>
        </form>
      </div>
    }
  `,
  styles: `
    .cost { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }
    .prices { font-size: 0.8rem; color: var(--text-muted); }
    a { color: #7cc4fa; }
    .field { display: flex; flex-direction: column; gap: 6px; font-size: 0.85rem; color: var(--text-muted); }
    input {
      padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm);
      background: var(--bg); outline: none;
    }
    input:focus { border-color: var(--accent); }
    .error {
      margin: 10px 0 0; padding: 8px 12px; border-radius: var(--radius-sm);
      background: var(--danger-bg); color: #fca5a5; font-size: 0.85rem;
    }
  `,
})
export class PremiumDialog {
  private readonly models = inject(ModelService);

  protected readonly request = this.models.unlockRequest;
  protected readonly minutes = computed(() => this.models.catalog()?.premium_unlock_minutes ?? 30);
  protected readonly value = signal('');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  private readonly password = viewChild<ElementRef<HTMLInputElement>>('password');

  protected readonly relative = relativeCostLabel;
  protected readonly price = formatPrice;

  constructor() {
    effect(() => {
      if (this.request()) {
        this.value.set('');
        this.error.set(null);
        setTimeout(() => this.password()?.nativeElement.focus());
      }
    });
  }

  protected async submit(): Promise<void> {
    if (this.busy() || !this.value()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.models.reauth(this.value());
      this.value.set('');
      this.models.finishUnlock(true);
    } catch (err) {
      this.error.set(ModelService.errorMessage(err));
      this.value.set('');
    } finally {
      this.busy.set(false);
    }
  }

  protected cancel(): void {
    if (!this.request()) return;
    this.value.set('');
    this.models.finishUnlock(false);
  }
}
