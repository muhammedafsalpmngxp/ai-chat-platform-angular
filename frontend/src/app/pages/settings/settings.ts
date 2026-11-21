import { ChangeDetectionStrategy, Component, ElementRef, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';

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

  protected readonly price = formatPrice;
  protected readonly relative = relativeCostLabel;

  constructor() {
    // This page scrolls inside its own container, so jump to #pricing manually.
    this.route.fragment.pipe(takeUntilDestroyed()).subscribe((fragment) => {
      if (!fragment) return;
      setTimeout(() => this.host.nativeElement.querySelector(`#${CSS.escape(fragment)}`)?.scrollIntoView());
    });
  }

  ngOnInit(): void {
    void this.models.load();
  }
}
