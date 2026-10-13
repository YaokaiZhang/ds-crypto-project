export class ApiError extends Error {
  constructor(public readonly status: number, public readonly body: unknown) {
    super(`API request failed (${status})`);
    this.name = 'ApiError';
  }
}

export class ApiClient {
  constructor(private readonly baseUrl = import.meta.env.VITE_API_BASE_URL ?? '/api/v1') {}

  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers);
    if (options.body !== undefined) headers.set('Content-Type', 'application/json');
    const response = await fetch(`${this.baseUrl}${path}`, { ...options, headers });
    const body: unknown = response.ok ? await response.json() : await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(response.status, body);
    return body as T;
  }

  streamUrl(path: string): string { return `${this.baseUrl}${path}`; }
}
export const apiClient = new ApiClient();

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const body = error.body as { detail?: unknown; message?: string } | null;
    if (typeof body?.detail === 'string') return body.detail;
    if (body?.message) return body.message;
    if (error.status === 404) return 'Analysis not found. Start a new analysis.';
    if (error.status === 422) return 'Check the address and analysis scope.';
    return `The analysis service returned ${error.status}. Please try again.`;
  }
  return error instanceof Error ? error.message : 'The analysis service could not be reached.';
}
