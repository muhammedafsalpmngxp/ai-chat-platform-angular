import { renderMarkdown, stripCitations } from './markdown';

describe('stripCitations', () => {
  it('removes [n] markers but keeps markdown links', () => {
    expect(stripCitations('Dangal leads [1][4]. Baahubali 2 is Telugu [3, 5].')).toBe(
      'Dangal leads. Baahubali 2 is Telugu.',
    );
    expect(stripCitations('see [docs](https://x.y)')).toBe('see [docs](https://x.y)');
  });
});

describe('renderMarkdown', () => {
  it('renders markdown and wraps code blocks with a copy button', () => {
    const html = renderMarkdown('**bold**\n\n```python\nprint("<hi>")\n```');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('class="copy-code"');
    expect(html).toContain('aria-label="Copy code"');
    expect(html).toContain('<svg'); // copy icon survives sanitizing
    expect(html).toContain('<span>python</span>');
    expect(html).toContain('print("&lt;hi&gt;")');
  });

  it('strips scripts and event handlers from model output', () => {
    const html = renderMarkdown('<img src=x onerror="alert(1)"><script>alert(2)</script>[x](javascript:alert(3))');
    expect(html).not.toContain('onerror');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('javascript:');
  });

  it('opens links in a new tab safely', () => {
    const html = renderMarkdown('[site](https://example.com)');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });
});
