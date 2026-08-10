export interface AuthUser {
  id: string;
  username: string;
  created_at: string;
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}
