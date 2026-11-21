import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';

import { AskDataResult } from '../../core/models';
import { DataChart, chartPoints } from './data-chart';

const PREVIEW_ROWS = 20;

/** Under an Ask Data answer: source, SQL query, result table and follow-up questions. */
@Component({
  selector: 'app-ask-data-result',
  imports: [DecimalPipe, DataChart],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let d = data();
    <div class="bar">
      <span class="badge-data" title="Answered from the company database">
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" /><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></svg>
        Company data{{ d.source_name ? ' · ' + d.source_name : '' }}
      </span>
      @if (points().length && d.chart_type) {
        <button type="button" class="toggle" [attr.aria-expanded]="showChart()" (click)="showChart.set(!showChart())">
          Chart
          <svg class="chevron" [class.open]="showChart()" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
        </button>
      }
      @if (d.sql) {
        <button type="button" class="toggle" [attr.aria-expanded]="showSql()" (click)="showSql.set(!showSql())">
          Query
          <svg class="chevron" [class.open]="showSql()" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
        </button>
      }
      @if (d.rows.length) {
        <button type="button" class="toggle" [attr.aria-expanded]="showTable()" (click)="showTable.set(!showTable())">
          Table · {{ total() | number }} row{{ total() === 1 ? '' : 's' }}
          <svg class="chevron" [class.open]="showTable()" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
        </button>
      }
    </div>

    @if (showChart() && d.chart_type && points().length) {
      <app-data-chart [type]="d.chart_type" [points]="points()" [title]="d.chart_title ?? null" />
    }

    @if (showSql() && d.sql) {
      <pre class="sql"><code>{{ d.sql }}</code></pre>
    }

    @if (showTable() && d.rows.length) {
      <div class="table-wrap">
        <table>
          <thead>
            <tr>@for (col of d.columns; track col) { <th scope="col" [class.num]="isNumber(d.rows[0]?.[col])">{{ col }}</th> }</tr>
          </thead>
          <tbody>
            @for (row of preview(); track $index) {
              <tr>@for (col of d.columns; track col) { <td [class.num]="isNumber(row[col])">{{ cell(row[col]) }}</td> }</tr>
            }
          </tbody>
        </table>
      </div>
      <p class="note">
        Showing {{ preview().length | number }} of {{ total() | number }} row{{ total() === 1 ? '' : 's' }}
      </p>
    }

    @if (d.followups.length && showFollowups()) {
      <div class="followups">
        @for (q of d.followups; track q) {
          <button type="button" class="followup" (click)="ask.emit(q)">{{ q }}</button>
        }
      </div>
    }
  `,
  styles: `
    :host { display: block; margin-top: 10px; }
    .bar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
    .badge-data {
      display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px; border-radius: 999px;
      background: rgba(56, 189, 248, 0.14); color: #7dd3fc; font-size: 0.72rem; font-weight: 600;
    }
    .toggle {
      display: inline-flex; align-items: center; gap: 5px; padding: 3px 8px 3px 10px;
      border: 1px solid var(--border); border-radius: 999px; background: transparent;
      color: var(--text-muted); font-size: 0.75rem;
    }
    .toggle:hover { color: var(--text); background: var(--bg-hover); }
    .chevron { transition: transform 0.15s; }
    .chevron.open { transform: rotate(90deg); }
    .sql {
      margin: 8px 0 0; padding: 10px 12px; border-radius: var(--radius-sm); background: #0d0d0d;
      overflow-x: auto; font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; font-size: 0.8rem;
      white-space: pre-wrap; color: #e5e7eb;
    }
    .table-wrap { margin-top: 8px; max-height: 360px; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius-sm); }
    table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
    th, td { padding: 6px 10px; border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap; }
    th { position: sticky; top: 0; background: var(--bg-elevated); color: var(--text-muted); font-weight: 600; }
    td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
    .note { margin: 4px 0 0; color: var(--text-faint); font-size: 0.72rem; }
    .followups { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .followup {
      padding: 5px 12px; border: 1px solid var(--border); border-radius: 999px; background: transparent;
      color: var(--text-muted); font-size: 0.78rem; text-align: left;
    }
    .followup:hover { color: var(--text); background: var(--bg-hover); border-color: #7dd3fc; }
  `,
})
export class AskDataResultView {
  readonly data = input.required<AskDataResult>();
  /** Only offer follow-ups under the latest answer. */
  readonly showFollowups = input(false);
  readonly ask = output<string>();

  protected readonly showSql = signal(false);
  protected readonly showTable = signal(false);
  protected readonly showChart = signal(true); // a requested chart is shown right away
  protected readonly points = computed(() => chartPoints(this.data().columns, this.data().rows));
  protected readonly total = computed(() => this.data().total_rows ?? this.data().rows.length);
  protected readonly preview = computed(() => this.data().rows.slice(0, PREVIEW_ROWS));

  protected isNumber(value: unknown): boolean {
    return typeof value === 'number';
  }

  protected cell(value: unknown): string {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'number') return value.toLocaleString();
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }
}
