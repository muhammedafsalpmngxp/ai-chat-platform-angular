import { ChangeDetectionStrategy, Component, ElementRef, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ChatSessionService } from '../../core/chat-session.service';
import { ModelService, formatPrice, relativeCostLabel } from '../../core/model.service';
import { ModelInfo } from '../../core/models';

/** Claude-style model switcher with tier colours, price hints and warnings. */
@Component({
  selector: 'app-model-picker',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './model-picker.html',
  styleUrl: './model-picker.scss',
  host: {
    '(document:click)': 'onDocumentClick($event)',
    '(document:keydown.escape)': 'open.set(false); lowWarning.set(null)',
  },
})
export class ModelPicker {
  private readonly host = inject(ElementRef<HTMLElement>);
  protected readonly modelService = inject(ModelService);
  protected readonly session = inject(ChatSessionService);

  protected readonly open = signal(false);
  protected readonly lowWarning = signal<ModelInfo | null>(null);

  protected readonly relative = relativeCostLabel;
  protected readonly price = formatPrice;

  protected toggle(event: Event): void {
    event.stopPropagation();
    this.open.update((v) => !v);
  }

  protected async choose(model: ModelInfo): Promise<void> {
    this.open.set(false);
    if (model.id === this.session.modelId()) return;
    if (model.tier === 'low') {
      this.lowWarning.set(model);
      return;
    }
    if (model.requires_reauth && !(await this.modelService.requestUnlock(model))) return;
    this.session.selectModel(model.id);
  }

  protected useAnyway(): void {
    const model = this.lowWarning();
    this.lowWarning.set(null);
    if (model) this.session.selectModel(model.id);
  }

  protected useRecommended(): void {
    this.lowWarning.set(null);
    const id = this.modelService.defaultId();
    if (id) this.session.selectModel(id);
  }

  protected isLocked(model: ModelInfo): boolean {
    return model.requires_reauth && !this.modelService.isUnlocked();
  }

  protected onDocumentClick(event: Event): void {
    if (!this.host.nativeElement.contains(event.target as Node)) this.open.set(false);
  }
}
