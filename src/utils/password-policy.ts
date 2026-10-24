export const PASSWORD_POLICY_MESSAGE =
  "密码需要 6-128 位，且包含大写字母、小写字母、数字、符号中的至少三类";

/** Login validates length only; the server verifies the stored password. */
export function validLoginPassword(password: string): boolean {
  const length = Array.from(password).length;
  return length >= 6 && length <= 128;
}

export function validNewPassword(password: string): boolean {
  const chars = Array.from(password);
  if (chars.length < 6 || chars.length > 128) return false;
  const kinds = [
    /[A-Z]/.test(password),
    /[a-z]/.test(password),
    /[0-9]/.test(password),
    /[^\p{L}\p{N}\s]/u.test(password)
  ];
  return kinds.filter(Boolean).length >= 3;
}
