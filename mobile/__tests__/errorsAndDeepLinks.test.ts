/**
 * @jest-environment node
 */
import {
  AppError,
  classifyHttpStatus,
  userFacingMessage,
} from '../utils/errors';
import { resolveSafeInternalRoute } from '../utils/deepLinks';

describe('error classification', () => {
  it('maps HTTP statuses', () => {
    expect(classifyHttpStatus(401)).toBe('unauthorized');
    expect(classifyHttpStatus(403)).toBe('forbidden');
    expect(classifyHttpStatus(409)).toBe('conflict');
    expect(classifyHttpStatus(429)).toBe('rate_limited');
    expect(classifyHttpStatus(500)).toBe('server');
  });

  it('exposes safe user-facing messages', () => {
    expect(userFacingMessage(new AppError('unauthorized', 'x'))).toMatch(
      /Session expired/,
    );
    expect(userFacingMessage(new AppError('forbidden', 'x'))).toMatch(
      /permission/,
    );
    expect(userFacingMessage(new AppError('conflict', 'x'))).toMatch(
      /changed since it was loaded/i,
    );
    expect(userFacingMessage(new AppError('offline', 'x'))).toMatch(/network/i);
    expect(
      userFacingMessage(new Error('password=secret traceback dump')),
    ).toBe('Something went wrong.');
  });
});

describe('deep link allowlist', () => {
  it('allows internal tab routes only', () => {
    expect(resolveSafeInternalRoute('/(tabs)/today')).toBe('/(tabs)/today');
    expect(resolveSafeInternalRoute('/(tabs)/system')).toBe('/(tabs)/system');
  });

  it('rejects action / oauth / absolute URLs', () => {
    expect(resolveSafeInternalRoute('https://evil.example/x')).toBeNull();
    expect(resolveSafeInternalRoute('/oauth/callback')).toBeNull();
    expect(resolveSafeInternalRoute('/approve/foo')).toBeNull();
    expect(resolveSafeInternalRoute('/items/1/actions/retry')).toBeNull();
  });
});
