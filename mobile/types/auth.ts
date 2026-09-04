export type TenantUserRole = 'owner' | 'manager' | 'sales' | 'operator' | 'viewer';
export type TenantUserStatus = 'invited' | 'active' | 'suspended' | 'removed';

export interface AuthTenantSummary {
  id: string;
  company_name: string;
  status: string;
  plan?: string | null;
}

export interface AuthUser {
  id: string;
  tenant_id: string;
  email: string;
  role: TenantUserRole;
  status: TenantUserStatus;
  created_at?: string | null;
  updated_at?: string | null;
  last_login_at?: string | null;
  has_password?: boolean;
  permissions?: string[];
}

export interface AuthLoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: AuthUser;
  tenant: AuthTenantSummary;
}

export interface AuthRefreshResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface AuthMeResponse {
  user: AuthUser;
  tenant: AuthTenantSummary;
  permissions: string[];
  roles_available: TenantUserRole[];
}

export interface SessionSnapshot {
  user: AuthUser;
  tenant: AuthTenantSummary;
  permissions: string[];
}
