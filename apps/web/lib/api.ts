export type ApiHealth = {
  service: string;
  status: string;
};

export type RiskGateReason = {
  code: string;
  message: string;
};

export type RiskGateDecision = {
  id?: string;
  candidate_asset_id: string;
  strategy_version: string;
  outcome: "TRADE" | "NO_TRADE";
  approved: boolean;
  reasons: RiskGateReason[];
  evaluated_at: string;
  expires_at: string;
  post_cost_reward_risk: number | null;
};

export type LatestRiskDecisionResponse = RiskGateDecision & {
  risk_reasons?: RiskGateReason[];
};

export type ApiClient = {
  getHealth: () => Promise<ApiHealth>;
  getLatestRiskDecision: (candidateAssetId?: string) => Promise<LatestRiskDecisionResponse>;
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function getHealth(): Promise<ApiHealth> {
  const response = await fetch(`${apiBaseUrl}/health`);

  if (!response.ok) {
    throw new Error(`API health request failed with status ${response.status}`);
  }

  return response.json() as Promise<ApiHealth>;
}

async function getLatestRiskDecision(
  candidateAssetId?: string,
): Promise<LatestRiskDecisionResponse> {
  const params = new URLSearchParams();
  if (candidateAssetId) {
    params.set("candidate_asset_id", candidateAssetId);
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  const response = await fetch(`${apiBaseUrl}/api/v1/risk-gates/latest${query}`);

  if (response.status === 404) {
    throw new Error("No published risk decision is available.");
  }
  if (!response.ok) {
    throw new Error(`Risk gate request failed with status ${response.status}`);
  }

  return response.json() as Promise<LatestRiskDecisionResponse>;
}

export const apiClient: ApiClient = {
  getHealth,
  getLatestRiskDecision,
};
