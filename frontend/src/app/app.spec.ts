import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';
import { groupChats } from './core/chat-groups';
import { ChatSummary } from './core/models';

describe('App', () => {
  it('should create the app', async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([])],
    }).compileComponents();
    const fixture = TestBed.createComponent(App);
    expect(fixture.componentInstance).toBeTruthy();
  });
});

describe('groupChats', () => {
  const now = new Date(2026, 10, 21, 15, 0, 0);
  const chat = (id: string, daysAgo: number): ChatSummary => ({
    id,
    title: id,
    model: null,
    token_count: 0,
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_cached_input_tokens: 0,
    total_cost_usd: 0,
    created_at: '',
    updated_at: new Date(now.getTime() - daysAgo * 24 * 3600 * 1000).toISOString(),
  });

  it('buckets chats by recency and keeps newest first', () => {
    const groups = groupChats(
      [chat('old', 60), chat('today-1', 0.01), chat('yesterday', 1), chat('week', 4), chat('today-2', 0.1)],
      now,
    );
    expect(groups.map((g) => g.label)).toEqual(['Today', 'Yesterday', 'Previous 7 days', 'Older']);
    expect(groups[0].chats.map((c) => c.id)).toEqual(['today-1', 'today-2']);
  });
});
