import { describe, expect, it } from 'vitest';
import { greet } from '../src/index.ts';

describe('greet', () => {
  it('returns a friendly greeting', () => {
    expect(greet('Claude')).toBe('Hello, Claude!');
  });

  it('handles empty input', () => {
    expect(greet('')).toBe('Hello, !');
  });
});
