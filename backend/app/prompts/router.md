---
version: 2
---
Classify the user's latest message into exactly one intent.

- chitchat: greetings, small talk, opinions, writing, coding, maths, explanations,
  questions about uploaded files, or anything answerable without fresh facts.
  Questions about today's date, the day of the week or the current time are
  chitchat too: the assistant already knows the user's date and time.
- web_search: needs current or factual information that may have changed recently or
  that you may not know: news, recent events, "latest"/"current"/"top"/"highest",
  records and rankings, box office, sports results, product releases, people in office,
  prices of products, anything about the current year or last year.
- realtime: live data that changes minute by minute: weather and forecasts, live stock
  or crypto prices, live scores, traffic, flight status.
{ask_data_option}
Current date: {today}. Use earlier messages to understand follow-ups
(e.g. "what about Dangal?" after a box-office question is still about box office).

Reply with JSON only:
{{"intent": {intents}, "search_queries": ["...", "..."]}}

search_queries (only for web_search, otherwise []): one or two short, specific web
queries. The first answers the question directly (include the year when relevant).
The second, when useful, targets an authoritative overview of the same fact - for
records and rankings, a "list of ..." style query (e.g. "list of highest-grossing
Hindi films worldwide").
