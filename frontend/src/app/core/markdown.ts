import DOMPurify from 'dompurify';
import { Marked, Renderer, Tokens } from 'marked';

const escapeHtml = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export const COPY_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' +
  '<rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15V5a2 2 0 0 1 2-2h10"></path></svg>';
export const CHECK_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">' +
  '<path d="m5 12 5 5 9-10"></path></svg>';

const renderer = new Renderer();
renderer.code = ({ text, lang }: Tokens.Code) => {
  const language = (lang || '').split(/\s+/)[0];
  return (
    `<div class="code-block"><div class="code-head"><span>${escapeHtml(language || 'code')}</span>` +
    `<button type="button" class="copy-code" aria-label="Copy code" title="Copy">${COPY_ICON}</button></div>` +
    `<pre><code>${escapeHtml(text)}</code></pre></div>`
  );
};

const marked = new Marked({ gfm: true, breaks: true, renderer });

// Links from model output open in a new tab and can't reach back into the app.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  }
});

// Same rule as the backend's strip_citations: "[1]", "[2][3]", "[1, 4]" but not "[1](link)".
const CITATION = /[ \t]?\[\d{1,2}(?:\s*[,–-]\s*\d{1,2})*\](?!\()/g;

/** Remove inline citation markers from web answers (sources are listed separately). */
export function stripCitations(text: string): string {
  return text.replace(CITATION, '').replace(/[ \t]+([.,;:!?])/g, '$1');
}

/** Markdown -> sanitized HTML. Safe to bind with bypassSecurityTrustHtml. */
export function renderMarkdown(source: string): string {
  const html = marked.parse(source, { async: false }) as string;
  return DOMPurify.sanitize(html, { ADD_ATTR: ['target'] });
}
