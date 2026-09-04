export type AppErrorKind =
  | 'unauthorized'
  | 'forbidden'
  | 'conflict'
  | 'rate_limited'
  | 'server'
  | 'network'
  | 'offline'
  | 'timeout'
  | 'validation'
  | 'mutation_blocked'
  | 'unknown';

export class AppError extends Error {
  readonly kind: AppErrorKind;
  readonly status?: number;
  readonly retryable: boolean;

  constructor(
    kind: AppErrorKind,
    message: string,
    opts?: { status?: number; retryable?: boolean; cause?: unknown },
  ) {
    super(message);
    this.name = 'AppError';
    this.kind = kind;
    this.status = opts?.status;
    this.retryable = opts?.retryable ?? false;
    if (opts?.cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = opts.cause;
    }
  }
}

export function classifyHttpStatus(status: number): AppErrorKind {
  if (status === 401) return 'unauthorized';
  if (status === 403) return 'forbidden';
  if (status === 409) return 'conflict';
  if (status === 429) return 'rate_limited';
  if (status >= 500) return 'server';
  if (status >= 400) return 'validation';
  return 'unknown';
}

export function userFacingMessage(error: unknown): string {
  if (error instanceof AppError) {
    switch (error.kind) {
      case 'unauthorized':
        return 'Session expired. Please sign in again.';
      case 'forbidden':
        return 'You do not have permission for this action.';
      case 'conflict':
        return 'Data changed. Pull to refresh and try again.';
      case 'rate_limited':
        return 'Too many requests. Please wait a moment.';
      case 'server':
        return 'Server temporarily unavailable.';
      case 'network':
      case 'offline':
        return 'No network connection.';
      case 'timeout':
        return 'Request timed out. Check your connection.';
      case 'mutation_blocked':
        return 'Actions are disabled in this app version.';
      case 'validation':
        return error.message || 'Request could not be completed.';
      default:
        return error.message || 'Something went wrong.';
    }
  }
  if (error instanceof Error && error.message) {
    // Never surface raw stack / provider payloads.
    if (/password|token|authorization|traceback|stack/i.test(error.message)) {
      return 'Something went wrong.';
    }
    return error.message;
  }
  return 'Something went wrong.';
}

export function isNetworkLikeError(error: unknown): boolean {
  if (error instanceof AppError) {
    return error.kind === 'network' || error.kind === 'offline' || error.kind === 'timeout';
  }
  if (error instanceof TypeError) return true;
  if (error instanceof Error) {
    return /network|fetch|dns|offline|timeout|failed to connect/i.test(error.message);
  }
  return false;
}
