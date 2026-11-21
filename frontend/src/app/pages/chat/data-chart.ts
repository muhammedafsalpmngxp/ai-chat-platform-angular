import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export interface ChartPoint {
  label: string;
  value: number;
}

const PALETTE = ['#38bdf8', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#fb923c', '#22d3ee', '#f472b6', '#a3e635', '#94a3b8'];
const MAX_SLICES = 9; // the rest is grouped as "Other"

/** Picks the label column (first non-numeric) and value column (first numeric) of a result table. */
export function chartPoints(columns: string[], rows: Record<string, unknown>[]): ChartPoint[] {
  if (!rows.length || !columns.length) return [];
  const isNum = (v: unknown) => typeof v === 'number' || (typeof v === 'string' && v.trim() !== '' && !isNaN(Number(v)));
  const valueCol = columns.find((c) => rows.every((r) => r[c] == null || isNum(r[c])) && rows.some((r) => isNum(r[c])));
  if (!valueCol) return [];
  const labelCol = columns.find((c) => c !== valueCol && rows.some((r) => r[c] != null && !isNum(r[c])))
    ?? columns.find((c) => c !== valueCol);
  return rows
    .map((r, i) => ({
      label: labelCol ? String(r[labelCol] ?? '—') : `Row ${i + 1}`,
      value: Number(r[valueCol] ?? 0),
    }))
    .filter((p) => isFinite(p.value));
}

/** Small dependency-free SVG charts for Ask Data results. */
@Component({
  selector: 'app-data-chart',
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (title()) { <p class="title">{{ title() }}</p> }
    @switch (type()) {
      @case ('pie') {
        <div class="pie-wrap">
          <svg viewBox="-1.05 -1.05 2.1 2.1" class="pie" role="img" [attr.aria-label]="'Pie chart: ' + (title() || 'results')">
            @for (s of slices(); track s.label) {
              @if (s.full) {
                <circle r="1" [attr.fill]="s.color"><title>{{ s.label }}: {{ s.value | number }}</title></circle>
              } @else {
                <path [attr.d]="s.path" [attr.fill]="s.color" stroke="var(--bg)" stroke-width="0.01">
                  <title>{{ s.label }}: {{ s.value | number }} ({{ s.percent | number: '1.0-1' }}%)</title>
                </path>
              }
            }
          </svg>
          <ul class="legend">
            @for (s of slices(); track s.label) {
              <li>
                <span class="swatch" [style.background]="s.color"></span>
                <span class="lbl" [title]="s.label">{{ s.label }}</span>
                <span class="val">{{ s.value | number }} · {{ s.percent | number: '1.0-1' }}%</span>
              </li>
            }
          </ul>
        </div>
      }
      @case ('line') {
        <svg [attr.viewBox]="'0 0 ' + W + ' ' + H" class="line" role="img" aria-label="Line chart">
          <polyline [attr.points]="linePoints()" fill="none" stroke="#38bdf8" stroke-width="2" />
          @for (p of lineDots(); track $index) {
            <circle [attr.cx]="p.x" [attr.cy]="p.y" r="3" fill="#38bdf8"><title>{{ p.label }}: {{ p.value | number }}</title></circle>
          }
        </svg>
        <div class="axis"><span>{{ points()[0]?.label }}</span><span>{{ points().at(-1)?.label }}</span></div>
      }
      @default {
        <div class="bars" role="img" aria-label="Bar chart">
          @for (p of barPoints(); track $index) {
            <div class="bar-row">
              <span class="lbl" [title]="p.label">{{ p.label }}</span>
              <span class="track"><span class="fill" [style.width.%]="p.width" [style.background]="p.color"></span></span>
              <span class="val">{{ p.value | number }}</span>
            </div>
          }
        </div>
      }
    }
  `,
  styles: `
    :host { display: block; margin-top: 10px; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg-sidebar); }
    .title { margin: 0 0 8px; font-size: 0.85rem; font-weight: 600; }
    .pie-wrap { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; }
    .pie { width: 180px; height: 180px; flex-shrink: 0; transform: rotate(-90deg); }
    .legend { list-style: none; margin: 0; padding: 0; flex: 1; min-width: 180px; font-size: 0.8rem; }
    .legend li { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
    .swatch { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
    .lbl { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; flex: 1; min-width: 0; }
    .val { color: var(--text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
    .bars { display: flex; flex-direction: column; gap: 6px; font-size: 0.8rem; }
    .bar-row { display: grid; grid-template-columns: minmax(80px, 30%) 1fr auto; align-items: center; gap: 8px; }
    .track { height: 14px; border-radius: 4px; background: var(--bg-active); overflow: hidden; }
    .fill { display: block; height: 100%; border-radius: 4px; }
    .line { width: 100%; height: 180px; }
    .axis { display: flex; justify-content: space-between; color: var(--text-faint); font-size: 0.72rem; }
  `,
})
export class DataChart {
  readonly type = input<'pie' | 'bar' | 'line'>('bar');
  readonly points = input.required<ChartPoint[]>();
  readonly title = input<string | null>(null);

  protected readonly W = 600;
  protected readonly H = 180;

  /** Largest slices first; the tail grouped as "Other". */
  private readonly grouped = computed(() => {
    const sorted = [...this.points()].filter((p) => p.value > 0).sort((a, b) => b.value - a.value);
    if (sorted.length <= MAX_SLICES + 1) return sorted;
    const rest = sorted.slice(MAX_SLICES).reduce((sum, p) => sum + p.value, 0);
    return [...sorted.slice(0, MAX_SLICES), { label: 'Other', value: rest }];
  });

  protected readonly slices = computed(() => {
    const items = this.grouped();
    const total = items.reduce((sum, p) => sum + p.value, 0) || 1;
    let angle = 0;
    return items.map((p, i) => {
      const fraction = p.value / total;
      const start = angle;
      angle += fraction * Math.PI * 2;
      const large = fraction > 0.5 ? 1 : 0;
      const [x1, y1] = [Math.cos(start), Math.sin(start)];
      const [x2, y2] = [Math.cos(angle), Math.sin(angle)];
      return {
        ...p,
        color: PALETTE[i % PALETTE.length],
        percent: fraction * 100,
        full: fraction >= 0.9999,
        path: `M0 0 L${x1} ${y1} A1 1 0 ${large} 1 ${x2} ${y2} Z`,
      };
    });
  });

  protected readonly barPoints = computed(() => {
    const pts = this.points().slice(0, 30);
    const max = Math.max(...pts.map((p) => Math.abs(p.value)), 1);
    return pts.map((p, i) => ({ ...p, width: (Math.abs(p.value) / max) * 100, color: PALETTE[i % PALETTE.length] }));
  });

  protected readonly lineDots = computed(() => {
    const pts = this.points();
    if (!pts.length) return [];
    const max = Math.max(...pts.map((p) => p.value));
    const min = Math.min(...pts.map((p) => p.value));
    const span = max - min || 1;
    const step = pts.length > 1 ? (this.W - 20) / (pts.length - 1) : 0;
    return pts.map((p, i) => ({ ...p, x: 10 + i * step, y: 10 + (1 - (p.value - min) / span) * (this.H - 20) }));
  });

  protected readonly linePoints = computed(() => this.lineDots().map((p) => `${p.x},${p.y}`).join(' '));
}
