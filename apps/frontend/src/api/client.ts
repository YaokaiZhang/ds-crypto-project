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
    const body: unknown = await response.json();
    if (!response.ok) throw new ApiError(response.status, body);
    return body as T;
  }

  streamUrl(path: string): string { return `${this.baseUrl}${path}`; }
}
export const apiClient = new ApiClient();
