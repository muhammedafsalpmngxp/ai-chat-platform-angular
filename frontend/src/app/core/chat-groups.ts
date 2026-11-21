import { ChatSummary } from './models';

export interface ChatGroup {
  label: string;
  chats: ChatSummary[];
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Groups chats like ChatGPT: Today / Yesterday / Previous 7 days / Previous 30 days / Older. */
export function groupChats(chats: ChatSummary[], now: Date = new Date()): ChatGroup[] {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const buckets: [string, number][] = [
    ['Today', startOfToday],
    ['Yesterday', startOfToday - DAY_MS],
    ['Previous 7 days', startOfToday - 7 * DAY_MS],
    ['Previous 30 days', startOfToday - 30 * DAY_MS],
    ['Older', -Infinity],
  ];

  const groups = new Map<string, ChatSummary[]>(buckets.map(([label]) => [label, []]));
  const sorted = [...chats].sort(
    (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at),
  );
  for (const chat of sorted) {
    const time = Date.parse(chat.updated_at);
    const [label] = buckets.find(([, start]) => time >= start)!;
    groups.get(label)!.push(chat);
  }
  return [...groups].filter(([, list]) => list.length).map(([label, list]) => ({ label, chats: list }));
}
