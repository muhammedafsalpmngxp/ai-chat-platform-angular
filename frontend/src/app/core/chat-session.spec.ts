import { applyStep } from './chat-session.service';
import { GraphStep } from './models';

describe('applyStep (live LangGraph trail)', () => {
  const ev = (node: string, status: GraphStep['status'], detail?: string): GraphStep => ({
    node,
    label: node,
    status,
    ...(detail ? { detail } : {}),
  });

  it('adds nodes in order, records details and finishes them', () => {
    let steps: GraphStep[] = [];
    steps = applyStep(steps, ev('input_guard', 'running'));
    steps = applyStep(steps, ev('input_guard', 'done'));
    steps = applyStep(steps, ev('router', 'running'));
    steps = applyStep(steps, ev('router', 'done'));
    steps = applyStep(steps, ev('web_search', 'running'));
    steps = applyStep(steps, ev('web_search', 'running', 'Reading 5 sources'));
    expect(steps.map((s) => `${s.node}:${s.status}`)).toEqual([
      'input_guard:done',
      'router:done',
      'web_search:running',
    ]);
    expect(steps[2].detail).toBe('Reading 5 sources');
    steps = applyStep(steps, ev('web_search', 'done'));
    expect(steps[2]).toEqual({ node: 'web_search', label: 'web_search', status: 'done', detail: 'Reading 5 sources' });
  });

  it('never re-opens a finished node because of a late detail', () => {
    const steps = applyStep([ev('web_search', 'done')], ev('web_search', 'running', 'late'));
    expect(steps[0].status).toBe('done');
  });
});
