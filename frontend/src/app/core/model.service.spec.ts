import { formatCost, formatPrice, relativeCostLabel } from './model.service';
import { ModelInfo } from './models';

const model = (overrides: Partial<ModelInfo>): ModelInfo => ({
  id: 'm',
  label: 'M',
  tier: 'standard',
  input_price: 1,
  output_price: 5,
  cached_input_price: 0.05,
  is_default: false,
  requires_reauth: false,
  warning: null,
  relative_cost: 1,
  ...overrides,
});

describe('price helpers', () => {
  it('labels cost relative to the default model', () => {
    expect(relativeCostLabel(model({ is_default: true }))).toBe('baseline');
    expect(relativeCostLabel(model({ relative_cost: 80 }))).toBe('≈80× Luna');
    expect(relativeCostLabel(model({ relative_cost: 8.25 }))).toBe('≈8.3× Luna');
  });

  it('formats per-token prices and chat costs', () => {
    expect(formatPrice(0.01)).toBe('$0.010');
    expect(formatPrice(0.5)).toBe('$0.50');
    expect(formatPrice(40)).toBe('$40.00');
    expect(formatPrice(null)).toBe('—');
    expect(formatCost(0)).toBe('$0.00');
    expect(formatCost(0.000736)).toBe('$0.0007');
    expect(formatCost(1.234)).toBe('$1.23');
  });
});
