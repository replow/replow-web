export interface Book {
  id: string;
  title: string;
  author: string;
  cover: string;
  total: number;
  description: string;
}
export interface Chapter {
  id: string;
  title: string;
  index: number;
}
export interface Job {
  job_id: string;
  book_id: string;
  format: string;
  title: string;
  author: string;
  cover_url: string;
  status: 'queued' | 'running' | 'retry' | 'completed' | 'failed';
  queue_position: number;
  completed_chapters: number;
  total_chapters: number;
  catalog_total: number;
  start_chapter: number;
  end_chapter: number | null;
  expires_at: number | null;
  download_url: string | null;
  file_available: boolean;
  expired: boolean;
  progress: number;
  added_chapters: number;
  reused_chapters: number;
  error: string | null;
  created_at: number;
}
export interface Updates {
  has_updates: boolean;
  new_chapters: number;
  current_total_chapters: number;
  latest_chapter_title: string;
}
export interface History {
  items: Job[];
  page: number;
  total: number;
  has_more: boolean;
}
export type ViewMode = 'search' | 'confirm' | 'history';
