import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, signal } from '@angular/core';

import { ChatUsage } from '../../core/chat-session.service';
import { formatCost } from '../../core/model.service';

/** Claude-style context indicator: tokens in use, no percentage and no limit. */
@Component({
  selector: 'app-context-meter',
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button
      type="button"
      class="meter"
      [attr.aria-expanded]="open()"
      aria-label="Context window usage"
      (click)="open.set(!open())"
      (blur)="open.set(false)"
    >
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M4 6h16M4 12h10M4 18h6" />
      </svg>
      {{ usage().context | number }} tokens
    </button>
    @if (open()) {
      <div class="panel" role="tooltip">
        <div class="row head"><span>Context window</span><b>{{ usage().context | number }}</b></div>
        <p class="note">Tokens used by the last request (prompt + reply). No limit.</p>
        <div class="row"><span>Total input</span><span>{{ usage().input | number }}</span></div>
        <div class="row indent"><span>of which cached</span><span>{{ usage().cached | number }}</span></div>
        <div class="row"><span>Total output</span><span>{{ usage().output | number }}</span></div>
        <div class="row cost"><span>Estimated cost</span><b>{{ cost(usage().costUsd) }}</b></div>
      </div>
    }
  `,
  styles: `
    :host { position: relative; display: inline-block; }
    .meter {
      display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
      padding: 6px 8px; border: 0; border-radius: var(--radius-sm);
      background: transparent; color: var(--text-faint); font-size: 0.75rem;
      font-variant-numeric: tabular-nums;
    }
    .meter:hover { color: var(--text); background: var(--bg-hover); }
    /* Sits under the message box, so the panel opens upwards. */
    .panel {
      position: absolute; right: 0; bottom: calc(100% + 8px); z-index: 20; width: 250px;
      padding: 12px; border: 1px solid var(--border); border-radius: var(--radius);
      background: var(--bg-elevated); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
      font-size: 0.8rem;
    }
    .row { display: flex; justify-content: space-between; padding: 3px 0; color: var(--text-muted); }
    .row.head { color: var(--text); font-size: 0.875rem; }
    .row.indent { padding-left: 12px; color: var(--text-faint); }
    .note { margin: 2px 0 8px; color: var(--text-faint); font-size: 0.75rem; }
    .row.cost { margin-top: 6px; padding-top: 8px; border-top: 1px solid var(--border); color: var(--text); }
  `,
})
export class ContextMeter {
  readonly usage = input.required<ChatUsage>();
  protected readonly open = signal(false);
  protected readonly cost = formatCost;
}
