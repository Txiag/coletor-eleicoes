export type Candidate = {
  number: string;
  scope: string;
  name: string;
  party: string;
  party_name: string;
  votes: number | null;
  percentage: number | null;
  status?: string | null;
};
export type Territory = {
  winner?: Candidate | null;
  source?: Pick<Dashboard["source"], "label" | "updated_at" | "collected_at" | "url"> & { official_progress?: number | null };
  id: string;
  name: string;
  level: "uf" | "municipality" | "zone";
  votes: number | null;
  candidate_votes: number | null;
  leader: { number: string; name: string; votes: number } | null;
  runner_up: { number: string; name: string; votes: number } | null;
  margin: number | null;
  state: "available" | "pending" | "tie" | "zero" | "unavailable";
};
export type Party = { number: string; name: string };
export type Office = { code: string; name: string; scopes: string[] };
export type Election = {
  code: string;
  name: string;
  round: number;
  offices: Office[];
};
export type Dataset = {
  id: string;
  name: string;
  phase: string;
  elections: Election[];
};
export type Metadata = {
  datasets: Dataset[];
  parties: Party[];
  refresh_seconds: number;
  stale_seconds: number;
};
export type Page<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};
export type Dashboard = {
  map_territory?: Territory | null;
  regions: RegionalProgress[];
  queried_at: string;
  source: {
    kind: "official";
    label: string;
    available: boolean;
    reason: string | null;
    updated_at: string | null;
    collected_at: string | null;
    checked_at: string | null;
    url: string | null;
    error: string | null;
    official_progress: number | null;
    totalized_sections: number | null;
    total_sections: number | null;
  };
  summary: {
    votes: number | null;
    nominal_votes: number | null;
    categories: { type: string; votes: number }[];
  };
  candidates: Page<Candidate> & {
    denominator: number | null;
    denominator_label: string;
    remaining?: { count: number; votes: number | null; percentage: number | null };
  };
  territories: {
    items: Territory[];
    level: Territory["level"];
    limited: boolean;
  };
  parties: Party[];
};
export type RegionalProgress = {
  ranking?: { status: 'available' | 'pending' | 'incomplete' | 'not_applicable'; items: Candidate[]; missing_ufs?: string[] };
  id: string;
  name: string;
  total: number | null;
  totalized: number | null;
  percentage: number | null;
  status: "available" | "incomplete" | "pending" | "not_applicable";
  expected_ufs: string[];
  missing_ufs: string[];
  error_ufs: string[];
  updated_at: string | null;
  collected_at: string | null;
};
