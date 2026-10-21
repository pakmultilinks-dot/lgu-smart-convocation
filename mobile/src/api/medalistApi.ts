// Public medalist board API (Phase 6). No auth: the board is public
// display data served by the student API's unauthenticated endpoints.
// The payload is name + award + picture reference only — private fields
// (reference numbers, publication state) never leave the server.

import { request } from "./client";
import { getApiBaseUrl } from "../store/settings";

const BASE = "/api/student/medalists";

export interface MedalistCard {
  id: number;
  department: string;
  student_name: string;
  award_category: string;
  position: string;
  has_photo: boolean;
}

export interface MedalistBoard {
  convocation: { name: string; year: string } | null;
  total: number;
  departments: string[];
  categories: string[];
  medalists: MedalistCard[];
}

export function fetchBoard(filters?: {
  department?: string;
  category?: string;
}): Promise<MedalistBoard> {
  const params = new URLSearchParams();
  if (filters?.department) params.set("department", filters.department);
  if (filters?.category) params.set("category", filters.category);
  const qs = params.toString();
  return request<MedalistBoard>(qs ? `${BASE}?${qs}` : BASE);
}

/** Base URL of the public picture route (cards append /<id>). */
export async function photoBase(): Promise<string> {
  const base = await getApiBaseUrl();
  return `${base}${BASE}/photo`;
}