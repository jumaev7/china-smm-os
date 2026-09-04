import { apiRequest } from '@/api/client';
import type {
  MobileControlHomeResponse,
  MobileControlSystemResponse,
} from '@/types/mobileControl';
import type {
  AttentionCategory,
  OperatorWorkspaceItemsResponse,
} from '@/types/workspace';

export async function fetchMobileHome(
  urgentLimit = 10,
): Promise<MobileControlHomeResponse> {
  return apiRequest<MobileControlHomeResponse>({
    method: 'GET',
    path: `/mobile-control/home?urgent_limit=${urgentLimit}`,
  });
}

export async function fetchMobileSystem(): Promise<MobileControlSystemResponse> {
  return apiRequest<MobileControlSystemResponse>({
    method: 'GET',
    path: '/mobile-control/system',
  });
}

export async function fetchWorkspaceItems(opts?: {
  category?: AttentionCategory;
  page?: number;
  pageSize?: number;
}): Promise<OperatorWorkspaceItemsResponse> {
  const params = new URLSearchParams();
  if (opts?.category) params.set('category', opts.category);
  params.set('page', String(opts?.page ?? 1));
  params.set('page_size', String(opts?.pageSize ?? 50));
  return apiRequest<OperatorWorkspaceItemsResponse>({
    method: 'GET',
    path: `/operator-workspace/items?${params.toString()}`,
  });
}
