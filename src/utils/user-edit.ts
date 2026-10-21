import type { UserItem, UserPayload, UserUpdateResponse } from "@/api/replow";
export function sensitiveChanges(
  original: UserItem | null,
  next: Partial<UserPayload>
): string[] {
  const changes: string[] = [];
  if (next.uid && next.uid !== original?.uid)
    changes.push("UID：" + (original?.uid || "自动分配") + " → " + next.uid);
  if (next.role && next.role !== (original?.role || "user"))
    changes.push(
      "角色：" + (next.role === "admin" ? "设为管理员" : "设为普通用户")
    );
  if (next.status && next.status !== (original?.status || "active"))
    changes.push(
      "状态：" +
        (next.status === "disabled" ? "停用账号，现有登录将失效" : "启用账号")
    );
  if (original && (next.password || next.generate_password))
    changes.push("重置密码：该用户其他登录将失效");
  return changes;
}
export function isOwnSession(
  result: UserUpdateResponse,
  editedUsername: string,
  currentUsername: string
): boolean {
  return (
    editedUsername === currentUsername &&
    result.session?.username === currentUsername
  );
}
