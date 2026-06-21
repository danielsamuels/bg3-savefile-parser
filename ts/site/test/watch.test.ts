import { describe, expect, it } from 'vitest';
import {
  findSaves,
  isPermissionError,
  MAX_CONSECUTIVE_FAILURES,
  shouldStopWatching,
} from '../src/watch.ts';

// Minimal stand-ins for the File System Access handles findSaves walks. It
// only reads `.kind`, the entry name, and recurses via `.entries()`; getFile is
// the poller's job, not findSaves's, so file handles need no body.
const fileHandle = { kind: 'file' as const };

function dirHandle(entries: [string, unknown][]) {
  return {
    kind: 'directory' as const,
    async *entries() {
      for (const e of entries) yield e;
    },
  };
}

/** A subfolder caught mid-write: enumerating it throws a transient read error. */
const churningDir = (name: string) => ({
  kind: 'directory' as const,
  entries() {
    throw new DOMException(`${name} is gone`, 'NotFoundError');
  },
});

describe('findSaves resilience', () => {
  it('still returns other saves when one subfolder throws a transient error', async () => {
    const root = dirHandle([
      ['GoodSave', dirHandle([['GoodSave.lsv', fileHandle]])],
      ['MidWrite', churningDir('MidWrite')],
      ['AlsoGood', dirHandle([['AlsoGood.lsv', fileHandle]])],
    ]);
    const saves = await findSaves(root as never);
    expect(saves.map(([p]) => p)).toEqual(['GoodSave/GoodSave.lsv', 'AlsoGood/AlsoGood.lsv']);
  });

  it('propagates a genuine permission revocation instead of swallowing it', async () => {
    const revoked = {
      kind: 'directory' as const,
      entries() {
        throw new DOMException('access denied', 'NotAllowedError');
      },
    };
    const root = dirHandle([['Locked', revoked]]);
    await expect(findSaves(root as never)).rejects.toThrow(/access denied/);
  });
});

describe('error classification', () => {
  it('treats NotAllowedError / SecurityError as permission errors', () => {
    expect(isPermissionError(new DOMException('x', 'NotAllowedError'))).toBe(true);
    expect(isPermissionError(new DOMException('x', 'SecurityError'))).toBe(true);
  });

  it('does not treat transient read errors as permission errors', () => {
    expect(isPermissionError(new DOMException('x', 'NotFoundError'))).toBe(false);
    expect(isPermissionError(new DOMException('x', 'NotReadableError'))).toBe(false);
    expect(isPermissionError(new Error('boom'))).toBe(false);
  });
});

describe('shouldStopWatching', () => {
  it('stops immediately on a permission revocation', () => {
    expect(shouldStopWatching(new DOMException('x', 'NotAllowedError'), 1)).toBe(true);
  });

  it('tolerates transient failures below the threshold', () => {
    const transient = new DOMException('x', 'NotFoundError');
    expect(shouldStopWatching(transient, MAX_CONSECUTIVE_FAILURES - 1)).toBe(false);
  });

  it('gives up once transient failures reach the threshold', () => {
    const transient = new DOMException('x', 'NotFoundError');
    expect(shouldStopWatching(transient, MAX_CONSECUTIVE_FAILURES)).toBe(true);
  });
});
