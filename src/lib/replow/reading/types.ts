export interface ShelfBook {
  id: string;
  source: 'fanqie' | 'local';
  source_id: string;
  title: string;
  author: string;
  cover: string;
  description: string;
  cfi: string;
  percentage: number;
  chapter: string;
  updated_at: number;
  read_chapters?: number;
  total_chapters?: number;
}
export interface ChapterText {
  chapter_id: string;
  title: string;
  text: string;
}
export interface LocalFile {
  blob: Blob;
  updated: number;
  chapters?: number;
  chapterIndices?: number[];
}
export interface Progress {
  read_chapters?: number;
  total_chapters?: number;
  cfi: string;
  percentage: number;
  chapter: string;
  updated: number;
}

export interface ReadingBookmark {
  id: string;
  cfi: string;
  chapter: string;
  percentage: number;
  created: number;
}

export interface ReadingStats {
  seconds: number;
  updated: number;
}
