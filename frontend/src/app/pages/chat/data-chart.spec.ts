import { chartPoints } from './data-chart';

describe('chartPoints', () => {
  it('uses the text column as labels and the numeric column as values', () => {
    const points = chartPoints(
      ['Cluster', 'Wells'],
      [
        { Cluster: 'North', Wells: 120 },
        { Cluster: 'South', Wells: '80' },
      ],
    );
    expect(points).toEqual([
      { label: 'North', value: 120 },
      { label: 'South', value: 80 },
    ]);
  });

  it('finds the value column even when it is not first', () => {
    const points = chartPoints(['Wells', 'Cluster'], [{ Wells: 5, Cluster: 'East' }]);
    expect(points).toEqual([{ label: 'East', value: 5 }]);
  });

  it('returns nothing when there is no numeric column', () => {
    expect(chartPoints(['Name'], [{ Name: 'A' }])).toEqual([]);
  });
});
