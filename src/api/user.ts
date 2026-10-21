import { http } from "@/utils/http";

export type UserResult = {
  success: boolean;
  data: {
    /** 头像 */
    avatar: string;
    /** 用户名 */
    username: string;
    /** 昵称 */
    nickname: string;
    /** 当前登录用户的角色 */
    roles: Array<string>;
    /** 按钮级别权限 */
    permissions: Array<string>;
    /** `token` */
    accessToken: string;
    /** 用于调用刷新`accessToken`的接口时所需的`token` */
    refreshToken: string;
    /** `accessToken`的过期时间（格式'xxxx/xx/xx xx:xx:xx'） */
    expires: Date;
  };
};

export type RefreshTokenResult = {
  success: boolean;
  data: {
    /** `token` */
    accessToken: string;
    /** 用于调用刷新`accessToken`的接口时所需的`token` */
    refreshToken: string;
    /** `accessToken`的过期时间（格式'xxxx/xx/xx xx:xx:xx'） */
    expires: Date;
  };
};

/** 登录 */
export const getLogin = (data?: object) => {
  return http.request<UserResult>("post", "/auth/login", { data });
};

/** SilverCode 邮箱验证码 */
export const sendVerificationCode = (data: {
  email: string;
  purpose: "login" | "register" | "reset";
  username?: string;
  display_name?: string;
}) => http.request<{ success: boolean; expires_in: number }>("post", "/auth/verification/send", { data });

export const codeLogin = (data: { email: string; code: string }) =>
  http.request<UserResult>("post", "/auth/code-login", { data });

export const registerVerify = (data: {
  username: string;
  display_name?: string;
  email: string;
  code: string;
}) =>
  http.request<{ success: boolean; signupToken: string }>("post", "/auth/register/verify", { data });

export const setupPassword = (data: { signup_token: string; password: string }) =>
  http.request<UserResult>("post", "/auth/password/setup", { data });

export const verifyPasswordReset = (data: { email: string; code: string }) =>
  http.request<{ success: boolean; resetToken: string; expiresIn: number }>(
    "post",
    "/auth/password-reset/verify",
    { data }
  );

export const confirmPasswordReset = (data: {
  reset_token: string;
  password: string;
}) => http.request<UserResult>("post", "/auth/password-reset/confirm", { data });

export const changeMyPassword = (data: {
  old_password?: string;
  new_password: string;
}) => http.request<UserResult>("post", "/auth/me/password", { data });

/** 刷新`token` */
export const refreshTokenApi = (data?: object) => {
  return http.request<RefreshTokenResult>("post", "/auth/refresh", { data });
};
