import { http } from "@/utils/http";
export interface DynamicImage {
  src: string;
  alt: string;
}
export interface DynamicItem {
  id: number;
  content: string;
  images: DynamicImage[];
  location: string;
  pinned: boolean;
  is_published: boolean;
  published_at: string;
  updated_at: string;
}
export type DynamicPayload = Pick<
  DynamicItem,
  "content" | "images" | "location" | "pinned" | "is_published" | "published_at"
>;
export const getDynamics = (params: {
  limit: number;
  offset: number;
  search: string;
  state: string;
}) =>
  http.request<{ items: DynamicItem[]; total: number }>(
    "get",
    "/admin/dynamics",
    { params }
  );
export const saveDynamic = (data: Partial<DynamicPayload>, id?: number) =>
  http.request<{ data: DynamicItem }>(
    id ? "put" : "post",
    "/admin/dynamics" + (id ? "/" + id : ""),
    { data }
  );
export const deleteDynamic = (id: number) =>
  http.request<{ success: boolean }>("delete", "/admin/dynamics/" + id);
