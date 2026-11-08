export type ApiHealth = {
  service: string;
  status: string;
};

export type ApiClient = {
  getHealth: () => Promise<ApiHealth>;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function getHealth(): Promise<ApiHealth> {
  const response = await fetch(`${apiBaseUrl}/health`);

  if (!response.ok) {
    throw new Error(`API health request failed with status ${response.status}`);
  }

  return response.json() as Promise<ApiHealth>;
}

export const apiClient: ApiClient = {
  getHealth,
};
