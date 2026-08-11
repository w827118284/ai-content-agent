import type { AccessTokenResponse, AuthUser } from "../types/auth";
import { apiRequest } from "./client";


interface Credentials {
  username: string;
  password: string;
}

export function registerUser(credentials: Credentials): Promise<AuthUser> {
  return apiRequest<AuthUser>(
    "/auth/register",
    {
      method: "POST",
      body: JSON.stringify(credentials),
    },
    { authenticated: false },
  );
}

export function loginUser(
  credentials: Credentials,
): Promise<AccessTokenResponse> {
  return apiRequest<AccessTokenResponse>(
    "/auth/login",
    {
      method: "POST",
      body: JSON.stringify(credentials),
    },
    { authenticated: false },
  );
}

export function getCurrentUser(accessToken?: string): Promise<AuthUser> {
  return apiRequest<AuthUser>(
    "/auth/me",
    {},
    { authenticated: true, authToken: accessToken },
  );
}
