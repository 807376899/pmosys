const API_BASE = "/api/v1";

export class ApiError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let code = "HTTP_ERROR";
    let message = `请求失败: ${response.status}`;
    try {
      const body = (await response.json()) as { code?: string; message?: string };
      code = body.code ?? code;
      message = body.message ?? message;
    } catch {
      message = await response.text();
    }
    throw new ApiError(code, message);
  }

  return response.json() as Promise<T>;
}

export async function apiGet<T>(path: string, searchParams?: URLSearchParams) {
  const query = searchParams?.toString();
  const response = await fetch(`${API_BASE}${path}${query ? `?${query}` : ""}`);
  return parseResponse<T>(response);
}

export async function apiPost<T>(path: string, body: unknown) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseResponse<T>(response);
}

export async function apiPatch<T>(path: string, body: unknown) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseResponse<T>(response);
}

export async function apiPostForm<T>(path: string, formData: FormData) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    body: formData,
  });
  return parseResponse<T>(response);
}

export function buildExportUrl(searchParams?: URLSearchParams) {
  const query = searchParams?.toString();
  return `${API_BASE}/exports/projects${query ? `?${query}` : ""}`;
}
