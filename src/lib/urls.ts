import { SITE_URL } from '../config';

/** `2026-11-17-my-post` -> `my-post`. Must match scripts/posts.py slug_from_filename. */
export function slugFromId(id: string): string {
  return id.replace(/^\d{4}-\d{2}-\d{2}-/, '');
}

export function postPath(slug: string): string {
  return `/posts/${slug}/`;
}

/** Canonical URL for a post, derived from the one site URL config value. */
export function canonicalUrl(slug: string): string {
  return `${SITE_URL}${postPath(slug)}`;
}

export function absoluteUrl(path: string): string {
  return `${SITE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

export function tagPath(tag: string): string {
  return `/tags/${encodeURIComponent(tag.toLowerCase())}/`;
}
